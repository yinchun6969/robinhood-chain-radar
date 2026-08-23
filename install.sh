#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/robinhood-radar}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 root 执行：sudo bash install.sh"
  exit 1
fi

echo "[1/6] 安装系统依赖..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip ca-certificates curl

echo "[2/6] 安装 Robinhood Chain Radar..."
mkdir -p "$APP_DIR"
cp monitor.py requirements.txt .env.example "$APP_DIR/"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi

echo
echo "请输入 Telegram Bot Token（可稍后编辑 /opt/robinhood-radar/.env）："
read -r TG_TOKEN
echo "请输入 Telegram Chat ID："
read -r TG_CHAT

python3 - "$APP_DIR/.env" "$TG_TOKEN" "$TG_CHAT" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1])
token=sys.argv[2]
chat=sys.argv[3]
lines=p.read_text().splitlines()
out=[]
for line in lines:
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        out.append("TELEGRAM_BOT_TOKEN="+token)
    elif line.startswith("TELEGRAM_CHAT_ID="):
        out.append("TELEGRAM_CHAT_ID="+chat)
    else:
        out.append(line)
p.write_text("\n".join(out)+"\n")
PY

echo "[3/6] 创建 systemd 服务..."
cat >/etc/systemd/system/robinhood-radar.service <<EOF
[Unit]
Description=Robinhood Chain Million Dollar Radar
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/monitor.py
Restart=always
RestartSec=3
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "[4/6] 自检..."
set -a
source "$APP_DIR/.env"
set +a
"$APP_DIR/venv/bin/python" "$APP_DIR/monitor.py" --self-test

echo "[5/6] 启动服务..."
systemctl daemon-reload
systemctl enable --now robinhood-radar

echo "[6/6] 完成"
echo
systemctl --no-pager --full status robinhood-radar || true
echo
echo "实时日志：journalctl -u robinhood-radar -f"
echo "配置文件：$APP_DIR/.env"
echo "重启：systemctl restart robinhood-radar"
