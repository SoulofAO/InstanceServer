import socket
import threading
import subprocess
import json
import os
import sys
import time
import uuid

active_servers = {}

if getattr(sys, 'frozen', False):
    # Если программа запущена как исполняемый файл
    config_path = os.path.join(os.path.dirname(sys.executable), "config.json")
    print(config_path)
    print("программа запущена как исполняемый файл")
else:
    # Если программа запущена из исходников
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    print(config_path)
    print("программа запущена как исходник")

with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)


path_to_server_build = config.get("path_to_server_build")
game_levels = config.get("game_levels")
server_port = config.get("server_port")

if not path_to_server_build:
    raise ValueError("Путь к серверу не указан в конфиге")

def find_free_port(start_port=7777, max_attempts=100):
    for i in range(max_attempts):
        port = start_port + i + len(active_servers)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
    raise RuntimeError("Не удалось найти свободный порт")

def generate_server():
    while(True):
        for map_name, game_level in game_levels.items():
            if len(game_level["waiting_players"]) >= game_level["required_players"]:
                players = game_level["waiting_players"][:game_level["required_players"]]
                del game_level["waiting_players"][:game_level["required_players"]]
                instance_server_generator = threading.Thread(target=start_game_server, args=(map_name, players,))
                instance_server_generator.start()

def wait_for_server_ready(process):
    """Ждет загрузки сервера, анализируя логи"""
    while True:
        output = process.stdout.readline().strip()  # Удаляем decode(), так как вывод уже в строковом формате
        if "Engine is initialized. Leaving FEngineLoop::Init()" in output:
            return  # Сервер запущен



def server_close(server_id):
    """Закрытие сервера после завершения процесса"""
    server_data = active_servers.pop(server_id, None)
    if server_data:
        server_data["process"].wait()  # Ждем завершения процесса
        print(f"Server {server_id} on port {server_data['port']} closed.")


def server_launch(server_id):
    """Ожидание загрузки сервера и уведомление игроков"""
    server_data = active_servers.get(server_id)
    if not server_data:
        print(f"No active server found for {server_id}")
        return

    wait_for_server_ready(server_data["process"])  # Ждем загрузки
    print("Engine Is Launch")
    for player in server_data["players"]:
        player.respounse_after_create_server(server_data["port"])


def start_game_server(map_name, players):
    """Запуск сервера с ожиданием загрузки"""
    port = find_free_port()
    server_id = str(uuid.uuid4())  # Уникальный идентификатор сервера

    command = [
        path_to_server_build,
        f"{map_name}?listen",
        "-server",
        "-log",
        f"-port={port}"
    ]

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               creationflags=subprocess.CREATE_NEW_CONSOLE)

    active_servers[server_id] = {
        "map_name": map_name,
        "port": port,
        "process": process,
        "players": players
    }
    print(f"Launching server {server_id} ({map_name}) on port {port} for players {players}")

    server_launch(server_id)  # Ожидаем загрузки сервера и уведомляем игроков

    return server_id  # Возвращаем ID сервера для управления


def is_socket_alive(sock):
    try:
        data = sock.recv(1, socket.MSG_PEEK)  # Заглядываем в поток
        return bool(data)  # True, если данные есть
    except (socket.error, OSError):
        return False  # Ошибка — соединение разорвано


class USocketWarper:
    def __init__(self, client_socket):
        self.client_socket = client_socket
        self.player_ip = "NotSetup"
        self.map_name = "NotSetup"

        self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)   # 10 сек ожидания перед проверкой
        self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)   # 5 сек между проверками
        self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)     # 3 неудачные попытки → разрыв

    def respounse_after_create_server(self, port):
        server_ip = socket.gethostbyname(socket.gethostname())
        response = json.dumps({"ServerIP": server_ip, "Port": port})
        self.send_response(response)

    def handle_client(self):
        while True:
            if not is_socket_alive(self.client_socket):
                if hasattr(self, "map_name") and self.map_name in game_levels:
                    if self in game_levels[self.map_name]["waiting_players"]:
                        game_levels[self.map_name]["waiting_players"].remove(self)
                        self.notify_queue_update(self.map_name)  # Обновление при выходе

                self.client_socket.close()
                print("Close")
                return

            data = self.client_socket.recv(1024).decode("utf-8")
            new_map_name, self.player_ip = data.split("|")
            if hasattr(self, "map_name") and self.map_name in game_levels:
                if self in game_levels[self.map_name]["waiting_players"]:
                    game_levels[self.map_name]["waiting_players"].remove(self)
                    self.notify_queue_update(self.map_name)  # Обновление для старого уровня

            self.map_name = new_map_name
            if self.map_name in game_levels:
                game_levels[self.map_name]["waiting_players"].append(self)
                self.notify_queue_update(self.map_name)  # Обновление для нового уровня


    def notify_queue_update(self, map_name):
        """Отправляет всем ожидающим игрокам обновленное количество ожидающих."""
        waiting = len(game_levels[map_name]["waiting_players"])
        response = json.dumps({"Queue": waiting})
        for player in game_levels[map_name]["waiting_players"]:
            player.send_response(response)

    def send_response(self, message):
        self.client_socket .sendall(message.encode("utf-8"))

def create_soket(client_socket):
    new_soket_warper = USocketWarper(client_socket)
    new_soket_warper.handle_client()


def start_server():
    server_generator = threading.Thread(target=generate_server)
    server_generator.start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_ip = socket.gethostbyname(socket.gethostname())
    server.bind((server_ip, server_port))
    server.listen(5)
    print("Waiting for connections...")
    print(f"Запущен сервер. IP адрес {server_ip}, порт {server_port}")

    while True:
        client_socket, _ = server.accept()
        if(client_socket):
            client_generator = threading.Thread(target=create_soket, args = (client_socket,))
            client_generator.start()
            print("NewClientSoket")

if __name__ == "__main__":
    start_server()



