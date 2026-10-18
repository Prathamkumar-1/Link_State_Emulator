import socket
import struct
import time

ON_ADDR = ("127.0.0.1", 5000)   # throwaway test only; the oracle runs on this machine

# identities the fake VNs will announce (just bytes, they don't need to be real)
NODES = {
    'A': ("10.0.0.1", 5000),
    'B': ("10.0.0.1", 5001),
    'C': ("10.0.0.2", 5000),
    'D': ("10.0.0.2", 5001),
    'E': ("10.0.0.2", 5002),
}


def recv_exact(s, n):
    data = b""
    while len(data) < n:
        chunk = s.recv(n - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


def read_link_state(s):
    msg_type, body_len = struct.unpack('!BH', recv_exact(s, 3))
    body = recv_exact(s, body_len)
    count = body[0]
    tuples = []
    for i in range(count):
        letter, ip, port, cost = struct.unpack('!B4sHH', body[1 + 9 * i: 10 + 9 * i])
        tuples.append((chr(letter), socket.inet_ntoa(ip), port, cost))
    return tuples


def read_all(socks):
    for letter, s in socks.items():
        try:
            print(letter, read_link_state(s))
        except (socket.timeout, ConnectionError):
            print(letter, "-> nothing received")


socks = {}
for letter, (ip, port) in NODES.items():          # connect in order A..E
    s = socket.create_connection(ON_ADDR)
    s.settimeout(3)
    s.sendall(struct.pack('!BH', 1, 6) + socket.inet_aton(ip) + struct.pack('!H', port))
    socks[letter] = s
    time.sleep(0.3)                               # keeps the letter order A, B, C, D, E

print("\n--- initial LINK-STATE ---")
read_all(socks)

input("\nPress Enter to kill C, then edit and save config.txt (change any cost), then press Enter again... ")
socks['C'].close()
del socks['C']
input("Press Enter once config.txt is saved... ")

print("\n--- after C died + config change ---")
read_all(socks)