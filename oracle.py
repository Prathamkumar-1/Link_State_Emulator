import sys
import socket
import select
import struct
from pathlib import Path

HOST = "192.168.153.181"
PORT = 5000


def parse_content(content):
    rows = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(list(map(int, line.split())))

    n = len(rows) + 1
    matrix = [[-1] * n for _ in range(n)]
    for i in range(n):
        matrix[i][i] = 0

    for i, row in enumerate(rows):
        for k, cost in enumerate(row):
            j = i + k + 1
            matrix[i][j] = cost
            matrix[j][i] = cost
    return matrix


def build_link_state(letter, matrix, registry):
    n = len(matrix)
    idx = ord(letter) - ord('A')

    if idx >= n:                      # island node: only itself
        candidates = [(idx, 0)]
    else:                             # self (cost 0) + neighbours (cost > 0)
        candidates = [(j, c) for j, c in enumerate(matrix[idx]) if c > 0 or j == idx]

    body = bytearray()
    count = 0
    for j, cost in candidates:
        l = chr(ord('A') + j)
        if l not in registry:         # that neighbour hasn't connected / is down
            continue
        ip, port = registry[l]
        # letter(1), IP(4), port(2), cost(2)
        body += struct.pack('!B4sHH', ord(l), socket.inet_aton(ip), port, cost)
        count += 1

    # header: type 2 (1 byte), body length (2 bytes)
    # body = count(1 byte) + tuples
    return struct.pack('!BHB', 2, len(body) + 1, count) + bytes(body)


def send_link_state(sock, clients, matrix, registry):
    letter = clients[sock]["letter"]
    msg = build_link_state(letter, matrix, registry)
    print(f"Sending LINK-STATE to VN {letter}: {msg.hex()}")
    try:
        sock.send(msg)
    except OSError as e:
        print(f"Send to VN {letter} failed: {e}")


def broadcast(clients, matrix):
    #registry = {letter: (ip, port)} for every VN whose CONNECT has arrived.
    registry = {c["letter"]: c["vn"] for c in clients.values() if c["vn"] is not None}
    for s, c in clients.items():
        if c["vn"] is not None:
            send_link_state(s, clients, matrix, registry)


def run_oracle(filename):
    path = Path(filename)
    matrix = parse_content(path.read_text(encoding="utf-8"))
    n = len(matrix)
    last_modified = path.stat().st_mtime_ns

    clients = {}          # sock -> {"letter", "vn"}  (vn = (ip, port) or None)
    next_index = 0
    connects = 0          # CONNECTs received from nodes that are in the matrix
    sent_initial = False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()

        print(f"Oracle Node listening on port {PORT}")

        try:
            while True:
                readable, _, _ = select.select([server] + list(clients), [], [], 1.0)

                for sock in readable:
                    if sock is server:
                        vn_sock, vn_addr = server.accept()
                        letter = chr(ord('A') + next_index)
                        next_index += 1
                        clients[vn_sock] = {"letter": letter, "vn": None}
                        print(f"VN {letter} connected from {vn_addr}")
                        continue

                    data = sock.recv(1024)
                    if not data:
                        print(f"VN {clients[sock]['letter']} disconnected.")
                        del clients[sock]
                        sock.close()
                        continue

                    # CONNECT: header(3 bytes) + ip(4 bytes) + port(2 bytes)
                    # dont want to read header as we already configured the packet info
                    ip = socket.inet_ntoa(data[3:7])
                    port = struct.unpack('!H', data[7:9])[0]
                    c = clients[sock]
                    c["vn"] = (ip, port)
                    print(f"Recieved CONNECT Message from VN {c['letter']} = {ip}:{port} \nRaw Data = {data}")

                    if ord(c["letter"]) - ord('A') < n:
                        connects += 1
                    elif sent_initial:
                        # late island node: it only needs its own tuple
                        send_link_state(sock, clients, matrix, {c["letter"]: c["vn"] for c in clients.values() if c["vn"] is not None})

                # send once, when all N expected nodes have sent CONNECT
                if not sent_initial and connects >= n:
                    sent_initial = True
                    broadcast(clients, matrix)

                # config reload -> resend to everyone
                try:
                    current_modified = path.stat().st_mtime_ns
                except OSError:
                    continue
                if current_modified != last_modified:
                    last_modified = current_modified
                    matrix = parse_content(path.read_text(encoding="utf-8"))
                    print("--- Config file changed ---")
                    if sent_initial:
                        broadcast(clients, matrix)

        except KeyboardInterrupt:
            print("Oracle shutting down.")
            for s in list(clients):
                s.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python oracle.py <config.txt>")
        sys.exit(1)

    run_oracle(sys.argv[1])