#!/usr/bin/env python3
import paramiko
import socket
import sys

# Configuration
ZOMBIE_IPS = ["209.97.160.87", "167.71.209.10", "152.42.222.108"]
SSH_USER = "root"
SSH_PASS = "km=Mtht12345vu"
CLEANUP_CMD = "killall -9 .cache_x .s 2>/dev/null; rm -f /dev/shm/.cache_x /tmp/.s"

def run_remote_cleanup(ip):
    print(f"[*] Connecting to {ip}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(
            ip, 
            username=SSH_USER, 
            password=SSH_PASS, 
            timeout=10,
            allow_agent=False,
            look_for_keys=False
        )
        print(f"[✓] Connected. Executing cleanup...")
        
        # Execute the command
        stdin, stdout, stderr = client.exec_command(CLEANUP_CMD)
        
        # We don't necessarily need to wait for output since the shell command has 2>/dev/null
        # but calling exit_status_code ensures it finished.
        exit_status = stdout.channel.recv_exit_status()
        
        print(f"[✓] {ip}: Cleanup finished (exit code: {exit_status})")
        
    except paramiko.AuthenticationException:
        print(f"[✗] {ip}: Authentication failed.")
    except socket.timeout:
        print(f"[✗] {ip}: Connection timed out.")
    except Exception as e:
        print(f"[✗] {ip}: Error: {e}")
    finally:
        client.close()

def main():
    print(f"Starting cleanup on {len(ZOMBIE_IPS)} VPS...")
    for ip in ZOMBIE_IPS:
        run_remote_cleanup(ip)
    print("\nAll tasks completed.")

if __name__ == "__main__":
    main()
