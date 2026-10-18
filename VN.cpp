#include <arpa/inet.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <string>
#include <vector>

static const uint16_t ORACLE_PORT = 5000;
static const uint8_t MSG_CONNECT = 1;
static const uint8_t MSG_LINK_STATE = 2;
static const size_t HEADER_LEN = 3;

struct Tuple {
    char letter;
    std::string ip;
    uint16_t port;
    uint16_t cost;
};

int make_udp_socket(const std::string& ip, uint16_t port) {
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    
    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, ip.c_str(), &addr.sin_addr);

    if (bind(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("UDP bind failed");
        exit(1);
    }
    return fd;
}

int connect_to_oracle(const std::string& oracle_ip) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);

    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(ORACLE_PORT);
    inet_pton(AF_INET, oracle_ip.c_str(), &addr.sin_addr);

    if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("Oracle connect failed");
        exit(1);
    }
    return fd;
}

void send_connect(int tcp_fd, const std::string& my_ip, uint16_t my_port) {
    uint8_t msg[9] = {MSG_CONNECT, 0, 6}; // Header
    
    inet_pton(AF_INET, my_ip.c_str(), &msg[3]);
    msg[7] = my_port >> 8;
    msg[8] = my_port & 0xFF;

    printf("Sending CONNECT hex: ");
    for (int i = 0; i < 9; i++) printf("%02x ", msg[i]);
    printf("\n");

    send(tcp_fd, msg, 9, 0);
}

void handle_link_state(const std::vector<uint8_t>& body) {
    int count = body[0];
    std::vector<Tuple> tuples(count);
    int offset = 1;

    for (int i = 0; i < count; i++) {
        tuples[i].letter = body[offset];
        
        char ip[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &body[offset + 1], ip, sizeof(ip));
        tuples[i].ip = ip;
        
        tuples[i].port = (body[offset + 5] << 8) | body[offset + 6];
        tuples[i].cost = (body[offset + 7] << 8) | body[offset + 8];
        offset += 9;
    }

    std::string out;
    // Print self (cost 0) first
    for (const auto& t : tuples) {
        if (t.cost == 0) out += std::string(1, t.letter) + "=0";
    }
    // Print neighbours
    for (const auto& t : tuples) {
        if (t.cost > 0) out += "," + std::string(1, t.letter) + "=" + std::to_string(t.cost);
    }

    printf("LINK-STATE: %s\n", out.c_str());
}

void process_buffer(std::vector<uint8_t>& buf) {
    while (buf.size() >= HEADER_LEN) {
        uint8_t type = buf[0];
        int body_len = (buf[1] << 8) | buf[2];

        if (buf.size() < HEADER_LEN + body_len) break; // wait for more data

        std::vector<uint8_t> body(buf.begin() + HEADER_LEN, buf.begin() + HEADER_LEN + body_len);
        buf.erase(buf.begin(), buf.begin() + HEADER_LEN + body_len);

        if (type == MSG_LINK_STATE) {
            handle_link_state(body);
        }
    }
}

int main(int argc, char* argv[]) {
    if (argc != 4) {
        printf("Usage: %s <oracle_ip> <my_ip> <my_udp_port>\n", argv[0]);
        return 1;
    }

    std::string oracle_ip = argv[1];
    std::string my_ip = argv[2];
    uint16_t my_port = atoi(argv[3]);

    int udp_fd = make_udp_socket(my_ip, my_port);
    int tcp_fd = connect_to_oracle(oracle_ip);
    send_connect(tcp_fd, my_ip, my_port);

    std::vector<uint8_t> rx_buf;

    while (true) {
        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(tcp_fd, &readfds);

        struct timeval timeout{1, 0}; // 1 second timeout
        
        if (select(tcp_fd + 1, &readfds, nullptr, nullptr, &timeout) < 0) {
            perror("select");
            break;
        }

        if (FD_ISSET(tcp_fd, &readfds)) {
            uint8_t temp[1024];
            int bytes = recv(tcp_fd, temp, sizeof(temp), 0);
            
            if (bytes <= 0) {
                printf("Oracle connection closed.\n");
                break;
            }

            rx_buf.insert(rx_buf.end(), temp, temp + bytes);
            process_buffer(rx_buf);
        }
    }

    close(tcp_fd);
    close(udp_fd);
    return 0;
}