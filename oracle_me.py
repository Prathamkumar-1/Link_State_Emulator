import sys
import time
import socket
import select
import struct
from pathlib import Path
import numpy as np


HOST = "10.51.14.255"
PORT = 5000


def parse_content(content):
    rows = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(list(map(int, line.split())))

    n = len(rows) + 1
    matrix = np.full((n, n), -1, dtype=int)
    np.fill_diagonal(matrix, 0)

    for i, row in enumerate(rows):
        for k, cost in enumerate(row):
            j = i + k + 1
            matrix[i][j] = cost
            matrix[j][i] = cost

    return matrix


def get_all_link_state_tuples(matrix, vn_sockets):
    """Returns {letter: [(letter, ip, port, cost), ...]} for all nodes."""

    n = len(matrix)

    registry = {}  # {letter: (ip, port)}

    for vn in vn_sockets.values():
        letter = vn["letter"]
        registry[letter] = (vn["ipaddress"], vn["udpport"])

    all_tuples = {}

    # Process nodes represented in the matrix
    for idx in range(n):
        node_letter = chr(ord('A') + idx)
        tuples = []

        for j, cost in enumerate(matrix[idx]):
            if cost > 0 or j == idx:
                letter = chr(ord('A') + j)

                if letter in registry:
                    ip, port = registry[letter]
                    tuples.append((letter, ip, port, int(cost)))

        all_tuples[node_letter] = tuples

    # Include island nodes (nodes not represented in the matrix)
    for letter, (ip, port) in registry.items():
        idx = ord(letter) - ord('A')

        if idx >= n:
            all_tuples[letter] = [(letter, ip, port, 0)]

    return all_tuples

def run_oracle(filename):
    path = Path(filename)

    content = path.read_text(encoding="utf-8")
    matrix = parse_content(content)
    n = len(matrix)
    last_modified = path.stat().st_mtime_ns

    connections = []
    vn_sockets = {}       # sock -> {"letter", "ipaddress", "udpport"}
    no_of_connect_messages = 0

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as on_socket:
        on_socket.bind((HOST, PORT))
        on_socket.listen()

        print(f"Oracle listening on port {PORT}")

        try:
            while True:
                ready_to_read_sockets, _, _ = select.select([on_socket] + connections, [], [], 1.0)

                for sock in ready_to_read_sockets:
                    if sock is on_socket:
                        vn_socket, vn_address = on_socket.accept()
                        letter = chr(ord('A') + len(connections))
                        connections.append(vn_socket)
                        vn_sockets[vn_socket] = {"letter": letter, "ipaddress": vn_address, "udpport": int}
                        print(f"VN {letter} connected from {vn_address}")
                    else:
                        data = sock.recv(1024)
                        ip_bytes, port = struct.unpack('!4sH', data[:6])
                        ip_address = socket.inet_ntoa(ip_bytes)
                        vn_sockets[sock]["udpport"] = port
                        print(f"Recieved CONNECT Message from VN {vn_sockets[sock]}: ({ip_address}, {port})")
                        if (ord(vn_sockets[sock]["letter"]) - ord('A')) < n: no_of_connect_messages += 1

                # Check for config file changes after atleast n connections
                if(no_of_connect_messages >= n):
                    all_tuples = get_all_link_state_tuples(matrix, vn_sockets)
                    for vn_socket, c in vn_sockets.items():
                        letter = c["letter"]
                        # Start body with the tuple count
                        body = bytearray(struct.pack('!B', len(all_tuples[letter])))

                        # Pack each tuple: letter(1), IP(4), port(2), cost(2)
                        for t_letter, t_ip, t_port, t_cost in all_tuples[letter]:
                            ip_bytes = socket.inet_aton(t_ip)
                            body.extend(struct.pack('!B4sHH', ord(t_letter), ip_bytes, t_port, t_cost))

                        # Prepend header: type 2 (1 byte), body length (2 bytes)
                        header = struct.pack('!BH', 2, len(body))
                        msg = header + body
                        vn_socket.send(msg)
                        print(f"Sending LINK-STATE Message to VN {letter}: {all_tuples[letter]}")

                current_modified = path.stat().st_mtime_ns
                if current_modified != last_modified:
                    new_content = path.read_text(encoding="utf-8")
                    matrix = parse_content(new_content)
                    all_tuples = get_all_link_state_tuples(matrix, vn_sockets)
                    print("\n--- Config file changed! ---")
                    last_modified = current_modified

        except KeyboardInterrupt:
            print("Oracle shutting down.")

            for vn_socket in connections:
                vn_socket.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python oracle.py <config.txt>")
        sys.exit(1)

    run_oracle(sys.argv[1])