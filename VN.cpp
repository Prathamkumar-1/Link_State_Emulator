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
#include <algorithm>
#include <ctime>

using namespace std;

const int ORACLE_PORT = 5000;
const int MSG_CONNECT = 1;
const int MSG_LINK_STATE = 2;
const int HEADER_LEN = 3;
const int MAX_NODES = 26;
const int LSP_INTERVAL = 15;   // seconds between re-sends of my own LSP
const int PRINT_INTERVAL = 15; // seconds between graph printouts
const int LSP_COPY = 2;        // send each LSP this many times

struct Tuple
{
    char letter;
    string ip;
    int port;
    int cost;
};

struct Link
{
    char letter;
    int cost;
};

struct LsdbEntry
{
    bool known = false;
    unsigned int seq = 0;
    vector<Link> links;
};

struct VNstate
{
    char my_letter = 0;
    string my_ip;
    int my_port = 0;
    vector<Tuple> neighbours;
    unsigned int my_seq = 0;
    LsdbEntry lsdb[MAX_NODES];
    int last_lsp_time = 0;
    int last_print_time = 0;
};

int make_udp_socket(string &ip, int port)
{
    int fd = socket(AF_INET, SOCK_DGRAM, 0);

    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, ip.c_str(), &addr.sin_addr);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0)
    {
        perror("UDP bind failed");
        exit(1);
    }
    return fd;
}

int connect_to_oracle(string &oracle_ip)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);

    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(ORACLE_PORT);
    inet_pton(AF_INET, oracle_ip.c_str(), &addr.sin_addr);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0)
    {
        perror("Oracle connect failed");
        exit(1);
    }
    return fd;
}

void send_connect(int tcp_fd, string &my_ip, int my_port)
{
    uint8_t msg[9] = {MSG_CONNECT, 0, 6}; // Header

    inet_pton(AF_INET, my_ip.c_str(), &msg[3]);
    msg[7] = my_port >> 8;
    msg[8] = my_port & 0xFF;

    printf("Sending CONNECT hex: ");
    for (int i = 0; i < 9; i++)
        printf("%02x ", msg[i]);
    printf("\n");

    send(tcp_fd, msg, 9, 0);
}

vector<uint8_t> pack_lsp(char origin, unsigned int seq, vector<Link> &links)
{
    vector<uint8_t> msg;
    msg.push_back(static_cast<uint8_t>(origin));
    msg.push_back((seq >> 24) & 0XFF);
    msg.push_back((seq >> 16) & 0XFF);
    msg.push_back((seq >> 8) & 0XFF);
    msg.push_back(seq & 0XFF);
    msg.push_back(static_cast<uint8_t>(links.size()));

    for (auto &link : links)
    {
        msg.push_back(static_cast<uint8_t>(link.letter));
        msg.push_back((link.cost >> 8) & 0XFF);
        msg.push_back(link.cost & 0XFF);
    }
    return msg;
}

bool parse_Lsp(uint8_t *data, int len, char &origin, unsigned int &seq, vector<Link> &links)
{
    if (len < 6)
        return false;

    origin = static_cast<char>(data[0]);
    if (origin < 'A' || origin > 'Z')
        return false;

    seq = (static_cast<unsigned int>(data[1]) << 24) |
          (static_cast<unsigned int>(data[2]) << 16) |
          (static_cast<unsigned int>(data[3]) << 8) |
          static_cast<unsigned int>(data[4]);
    int count = data[5];
    if (count > MAX_NODES || len != 6 + count * 3)
        return false;
    links.clear();

    int offset = 6;
    for (int i = 0; i < count; i++)
    {
        char letter = static_cast<char>(data[offset]);
        int cost = (data[offset + 1] << 8) | data[offset + 2];
        if (letter < 'A' || letter > 'Z')
            return false;
        links.push_back({letter, cost});
        offset += 3;
    }
    return true;
}

void send_to_neighbours(int udp_fd, VNstate &st, const vector<uint8_t> &msg, char except)
{
    for (const auto &neighbour : st.neighbours)
    {
        if (except != 0 && neighbour.letter == except)
            continue;

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(neighbour.port);
        if (inet_pton(AF_INET, neighbour.ip.c_str(), &addr.sin_addr) <= 0)
        {
            continue;
        }
        for (int i = 0; i < LSP_COPY; i++)
        {
            int sent = sendto(udp_fd, msg.data(), msg.size(), 0, (struct sockaddr *)&addr, sizeof(addr));
            if (sent < 0)
            {
                perror("sendto failed");
            }
        }
    }
}

void originate_lsp(int udp_fd, VNstate &st)
{
    if (st.my_letter < 'A' || st.my_letter > 'Z')
        return;
    vector<Link> links;
    for (const auto &neighbour : st.neighbours)
    {
        links.push_back({neighbour.letter, neighbour.cost});
    }

    st.my_seq++;
    int index = st.my_letter - 'A';
    st.lsdb[index].known = true;
    st.lsdb[index].seq = st.my_seq;
    st.lsdb[index].links = links;

    vector<uint8_t> msg = pack_lsp(st.my_letter, st.my_seq, links);
    send_to_neighbours(udp_fd, st, msg, 0);
    st.last_lsp_time = time(nullptr);
}

void handle_udp(int udp_fd, VNstate &st)
{
    uint8_t buffer[1024];
    sockaddr_in sender{};
    socklen_t sender_len = sizeof(sender);
    int bytes = recvfrom(udp_fd, buffer, sizeof(buffer), 0, (struct sockaddr *)&sender, &sender_len);
    if (bytes <= 0)
        return;
    char origin;
    unsigned int seq;
    vector<Link> links;
    if (!parse_Lsp(buffer, static_cast<int>(bytes), origin, seq, links))
        return;
    int index = origin - 'A';
    if (st.lsdb[index].known && seq <= st.lsdb[index].seq)
        return;
    st.lsdb[index].known = true;
    st.lsdb[index].seq = seq;
    st.lsdb[index].links = links;
    char sender_letter = 0;
    char sender_ip[INET_ADDRSTRLEN];
    if (inet_ntop(AF_INET, &sender.sin_addr, sender_ip, sizeof(sender_ip)) != nullptr)
    {
        for (const auto &neighbour : st.neighbours)
        {
            if (neighbour.ip == sender_ip && neighbour.port == ntohs(sender.sin_port))
            {
                sender_letter = neighbour.letter;
                break;
            }
        }
    }

    vector<uint8_t> msg(buffer, buffer + bytes);
    send_to_neighbours(udp_fd, st, msg, sender_letter);
}

void print_graph(VNstate &st)
{
    int highest = -1;
    for (int i = 0; i < MAX_NODES; i++)
    {
        if (st.lsdb[i].known)
            highest = i;
    }
    if (highest < 0)
        return;

    int graph[MAX_NODES][MAX_NODES];
    for (int i = 0; i <= highest; i++)
    {
        for (int j = 0; j <= highest; j++)
        {
            graph[i][j] = (i == j) ? 0 : -1;
        }
    }

    // Use each origin's own report. If only one endpoint is known, mirror its cost.
    for (int i = 0; i <= highest; i++)
    {
        if (!st.lsdb[i].known)
            continue;
        for (const auto &link : st.lsdb[i].links)
        {
            int j = link.letter - 'A';
            if (j < 0 || j > highest || j == i)
                continue;
            graph[i][j] = link.cost;
            if (!st.lsdb[j].known && graph[j][i] == -1)
                graph[j][i] = link.cost;
        }
    }

    printf("Known link-state graph (-1 means unknown/no link):\n    ");
    for (int j = 0; j <= highest; j++)
        printf("%c ", 'A' + j);
    printf("\n");
    for (int i = 0; i <= highest; i++)
    {
        printf("%c:  ", 'A' + i);
        for (int j = 0; j <= highest; j++)
            printf("%d ", graph[i][j]);
        printf("\n");
    }
}

void handle_link_state(vector<uint8_t> &body, VNstate &st, int udp_fd)
{
    int count = body[0];
    if (count > MAX_NODES || body.size() < 1 + count * 9)
        return;
    vector<Tuple> tuples(count);
    int offset = 1;

    for (int i = 0; i < count; i++)
    {
        tuples[i].letter = body[offset];

        char ip[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &body[offset + 1], ip, sizeof(ip));
        tuples[i].ip = ip;

        tuples[i].port = (body[offset + 5] << 8) | body[offset + 6];
        tuples[i].cost = (body[offset + 7] << 8) | body[offset + 8];
        offset += 9;
    }

    string out;
    // Print self (cost 0) first
    for (const auto &t : tuples)
    {
        if (t.cost == 0)
            out += std::string(1, t.letter) + "=0";
    }
    // Print neighbours
    for (const auto &t : tuples)
    {
        if (t.cost > 0)
            out += "," + std::string(1, t.letter) + "=" + std::to_string(t.cost);
    }

    printf("LINK-STATE: %s\n", out.c_str());
    st.neighbours.clear();

    for (const auto &t : tuples)
    {
        if (t.cost == 0)
            st.my_letter = t.letter;
        else
            st.neighbours.push_back(t);
    }

    if (st.my_letter >= 'A' && st.my_letter <= 'Z')
    {
        originate_lsp(udp_fd, st);
    }
}

void process_buffer(vector<uint8_t> &buf, VNstate &st, int udp_fd)
{
    while (buf.size() >= HEADER_LEN)
    {
        uint8_t type = buf[0];
        int body_len = (buf[1] << 8) | buf[2];

        if (buf.size() < HEADER_LEN + body_len)
            break;

        vector<uint8_t> body(buf.begin() + HEADER_LEN, buf.begin() + HEADER_LEN + body_len);
        buf.erase(buf.begin(), buf.begin() + HEADER_LEN + body_len);

        if (type == MSG_LINK_STATE)
        {
            handle_link_state(body, st, udp_fd);
        }
    }
}

int main(int argc, char *argv[])
{
    if (argc != 4)
    {
        printf("Usage: %s <oracle_ip> <my_ip> <my_udp_port>\n", argv[0]);
        return 1;
    }

    string oracle_ip = argv[1];
    string my_ip = argv[2];
    int my_port = atoi(argv[3]);

    int udp_fd = make_udp_socket(my_ip, my_port);
    int tcp_fd = connect_to_oracle(oracle_ip);
    send_connect(tcp_fd, my_ip, my_port);

    VNstate st;
    st.my_ip = my_ip;
    st.my_port = my_port;
    st.last_print_time = time(nullptr);
    st.last_lsp_time = time(nullptr);

    vector<uint8_t> rx_buf;

    while (true)
    {
        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(tcp_fd, &readfds);
        FD_SET(udp_fd, &readfds);
        int maxfd = max(tcp_fd, udp_fd);

        struct timeval timeout{1, 0}; // 1 second timeout

        if (select(maxfd + 1, &readfds, nullptr, nullptr, &timeout) < 0)
        {
            perror("select");
            break;
        }

        if (FD_ISSET(tcp_fd, &readfds))
        {
            uint8_t temp[1024];
            int bytes = recv(tcp_fd, temp, sizeof(temp), 0);

            if (bytes <= 0)
            {
                printf("Oracle connection closed.\n");
                break;
            }

            rx_buf.insert(rx_buf.end(), temp, temp + bytes);
            process_buffer(rx_buf, st, udp_fd);
        }

        if (FD_ISSET(udp_fd, &readfds))
        {
            handle_udp(udp_fd, st);
        }

        int now = time(nullptr);
        if (st.my_letter != 0 && now - st.last_lsp_time >= LSP_INTERVAL)
        {
            originate_lsp(udp_fd, st);
            st.last_lsp_time = now;
        }
        if (now - st.last_print_time >= PRINT_INTERVAL)
        {
            print_graph(st);
            st.last_print_time = now;
        }
    }

    close(tcp_fd);
    close(udp_fd);
    return 0;
}