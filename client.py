import socket 

SERVER = "127.0.0.1"
PORT = 14450 

client_socket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

client_socket.connect((SERVER,PORT))

msg = "HELLO SERVER"
client_socket.sendall(msg.encode())

client_socket.close()
