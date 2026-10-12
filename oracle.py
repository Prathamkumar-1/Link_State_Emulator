import sys
import time
import socket
import select
from pathlib import Path
import numpy as np


HOST = "0.0.0.0"
PORT = 5000
POLL_INTERVAL = 0.5


def parse_content(content):
    rows = []

    for line in content.splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        rows.append(list(map(int, line.split())))

    n = len(rows)
    matrix = np.zeros((n, n), dtype=int)

    for i, row in enumerate(rows):
        for j, cost in enumerate(row, start=i + 1):
            matrix[i, j] = cost
            matrix[j, i] = cost

    return matrix


def run_oracle(filename):
    path = Path(filename)

    content = path.read_text(encoding="utf-8")
    matrix = parse_content(content)
    n = len(matrix)
    last_modified = path.stat().st_mtime_ns

    connections = []

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((HOST, PORT))
        server.listen()

        print(f"Oracle listening on port {PORT}")

        try:
            while True:
                socket, address = server.accept()

                connections.append(socket)
                print(
                    f"VN {chr(ord('A') + len(connections))} connected: "
                    f"from {address}"
                )

                # Check for config file changes after atleast n connections
                if(len(connections) >= n):
                    current_modified = path.stat().st_mtime_ns
                    if current_modified != last_modified:
                        new_content = path.read_text(encoding="utf-8")
                        new_matrix = parse_content(new_content)
                        print("\n--- Config file changed! ---")
                        last_modified = current_modified

        except KeyboardInterrupt:
            print("\n--- Sending LINK-STATE messages ---")

            print("Oracle shutting down.")

            for socket in connections:
                socket.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python oracle.py <config.txt>")
        sys.exit(1)

    run_oracle(sys.argv[1])