import socket 

HOST = ""
PORT = 14450 

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

server_socket.bind((HOST,PORT))

server_socket.listen(1)

client_socket, client_addr = server_socket.accept()

data = client_socket.recv(1024)
     
print(data.decode())

server_socket.close()
client_socket.close()

