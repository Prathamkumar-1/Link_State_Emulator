import sys
import socket
import select
import struct
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

    n = len(rows) + 1
    matrix = np.full((n, n), -1, dtype=int)
    np.fill_diagonal(matrix, 0)

    for i, row in enumerate(rows):
        for k, cost in enumerate(row):
            j = i + k + 1
            matrix[i][j] = cost
            matrix[j][i] = cost

    return matrix


def get_link_state_tuples(matrix, node_letter, registry):
    """Returns [(letter, ip, port, cost), ...] for node_letter."""
    n = len(matrix)
    idx = ord(node_letter) - ord('A')

    # island node: no matrix row, only itself
    if idx >= n:
        ip, port = registry[node_letter]
        return [(node_letter, ip, port, 0)]

    tuples = []
    for j, cost in enumerate(matrix[idx]):
        if cost > 0 or j == idx:
            letter = chr(ord('A') + j)
            if letter not in registry:    #neighbour is down
                continue
            ip, port = registry[letter]   # KeyError here means a real bug
            tuples.append((letter, ip, port, int(cost)))
    return tuples


def build_registry(clients):
    """Return {letter: (ip, port)} for every VN whose CONNECT has arrived."""
    registry = {}

    for client in clients.values():
        letter = client["letter"]
        identity = client["vn"]      # (ip, port), or None if no CONNECT yet

        if identity is None:
            continue                 # this VN hasn't told us its ip/port yet

        registry[letter] = identity

    return registry


def send_link_state(sock, matrix, clients):
    registry = build_registry(clients)
    letter = clients[sock]["letter"]
    tuples = get_link_state_tuples(matrix, letter, registry)

    # Start body with the tuple count
    body = bytearray(struct.pack('!B', len(tuples)))

    # Pack each tuple: letter(1), IP(4), port(2), cost(2)
    for t_letter, t_ip, t_port, t_cost in tuples:
        ip_bytes = socket.inet_aton(t_ip)
        body.extend(struct.pack('!B4sHH', ord(t_letter), ip_bytes, t_port, t_cost))

    # Prepend header: type 2 (1 byte), body length (2 bytes)
    header = struct.pack('!BH', 2, len(body))
    msg = header + body
    
    print(f"LINK-STATE for {letter}: {tuples}")
    print(f"Hex dump for {letter}: {msg.hex()}")
    
    try:
        sock.send(msg)
    except OSError as e:
        print(f"Error sending LINK-STATE for {letter}: {e}")


def run_oracle(filename):
    path = Path(filename)

    matrix = parse_content(path.read_text(encoding="utf-8"))
    n = len(matrix)
    last_modified = path.stat().st_mtime_ns

    clients = {}   # sock -> {"letter", "buf", "addr", "vn"}
    next_index = 0
    sent_initial = False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()
        server.setblocking(False)

        print(f"Oracle listening on port {PORT} (expecting {n} nodes)")

        try:
            while True:
                readable, _, _ = select.select([server] + list(clients), [], [], 1.0)

                for sock in readable:
                    if sock is server:
                        client_sock, address = server.accept()
                        client_sock.setblocking(False)
                        letter = chr(ord('A') + next_index)
                        clients[client_sock] = {"letter": letter, "buf": bytearray(),
                                                "addr": address, "vn": None}
                        next_index += 1
                        print(f"VN {letter} connected from {address}")
                        continue

                    try:
                        data = sock.recv(1024)
                    except OSError:
                        data = b""

                    if not data:
                        print(f"VN {clients[sock]['letter']} disconnected.")
                        del clients[sock]
                        sock.close()
                        continue

                    buf = clients[sock]["buf"]
                    buf += data

                    while len(buf) >= 3:
                        msg_type, body_len = struct.unpack('!BH', buf[:3])
                        if len(buf) < 3 + body_len:
                            break
                        body = bytes(buf[3:3 + body_len])
                        del buf[:3 + body_len]

                        if msg_type == 1 and body_len == 6:   # CONNECT
                            ip = socket.inet_ntoa(body[:4])
                            port = struct.unpack('!H', body[4:6])[0]
                            clients[sock]["vn"] = (ip, port)
                            print(f"CONNECT: VN {clients[sock]['letter']} = {ip}:{port}")

                    # send once, when all N expected nodes have sent CONNECT
                    if not sent_initial:
                        ready = sum(1 for c in clients.values()
                                    if c["vn"] is not None
                                    and ord(c["letter"]) - ord('A') < n)
                        if ready == n:
                            sent_initial = True
                            for s, c in clients.items():
                                if c["vn"] is not None:
                                    send_link_state(s, matrix, clients)

                # config reload
                current_modified = path.stat().st_mtime_ns
                if current_modified != last_modified:
                    last_modified = current_modified
                    matrix = parse_content(path.read_text(encoding="utf-8"))
                    print(matrix)
                    if sent_initial:
                        for s, c in clients.items():
                            if c["vn"] is not None:
                                send_link_state(s, matrix, clients)

        except KeyboardInterrupt:
            print("Oracle shutting down.")
            for s in list(clients):
                s.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python oracle.py <config.txt>")
        sys.exit(1)

    run_oracle(sys.argv[1])