import socket

server_ip = "127.0.0.255"  # Замени на реальный IP-адрес сервера
server_port = 8888       # Замени на реальный порт сервера

map_name = "Map1"      # Название карты, которую ты хочешь использовать
player_ip = "192.168.1.100"  # IP-адрес игрока (может быть фиктивным, если не нужен)

message = f"{map_name}|{player_ip}"

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

client_socket.connect((server_ip, server_port))
client_socket.sendall(message.encode("utf-8"))

while(True):
    response = client_socket.recv(1024).decode("utf-8")
    print("Ответ сервера:", response)



