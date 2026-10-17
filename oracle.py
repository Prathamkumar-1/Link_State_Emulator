import sys
import time
import socket
import select
from pathlib import Path
import numpy as np


HOST = "0.0.0.0"
PORT = 5000


def parse_content(content):
    rows = []

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(list(map(int, line.split())))

    n = len(rows)
    matrix = np.full((n, n), -1 , dtype=int)
    np.fill_diagonal(matrix,0)

    for i, row in enumerate(rows):
        for j, cost in enumerate(row):
            if i!=j:
                matrix[i][j] = cost
            

    return matrix


def run_oracle(filename):
    path = Path(filename)

    content = path.read_text(encoding="utf-8")
    matrix = parse_content(content)
    n = len(matrix)
    last_modified = path.stat().st_mtime_ns

    connections = []

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()
        server.setblocking(False)
        
        print(f"Oracle listening on port {PORT}")

        try:
            while True:
                readable , _ , _ = select.select([server] + connections , [] , [] , 1.0)
                
                for sock in readable:
                    if sock is server:
                        
                        client_sock, address = server.accept()
                        connections.append(client_sock)
                        print(
                    f"VN {chr(ord('A') + len(connections) - 1)} connected: "
                    f"from {address}"
                        )
                    else:
                        data = sock.recv(1024)
                        if not data:
                            connections.remove(sock)
                            sock.close()
                            print(f"VN {chr(ord('A') + len(connections))} disconnected.")

                # Check for config file changes after atleast n connections
                current_modified = path.stat().st_mtime_ns
                if current_modified != last_modified:
                    last_modified = current_modified
                    new_content = path.read_text(encoding="utf-8")
                    matrix = parse_content(new_content)
                    print(matrix)
                    
                

        except KeyboardInterrupt:
            print("\n--- Sending LINK-STATE messages ---")

            print("Oracle shutting down.")

            for client_sock in connections:
                client_sock.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python oracle.py <config.txt>")
        sys.exit(1)

    run_oracle(sys.argv[1])