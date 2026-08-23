#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${HOME}/robinhood-radar"
FILES=(
  monitor.py address_intel.py token_intel.py token_radar.py token_worker.py
  dashboard.py fast_scanner.py event_worker.py swap_filter.py v4_resolver.py
  native_scanner.py radar_supervisor.py requirements.txt test_static.py test_integration.py .env.example
)
RUNTIME=(start-termux.sh stop-termux.sh status-termux.sh enable-boot.sh disable-boot.sh keepalive-job.sh)

echo "[1/6] Install Termux dependencies / 安装 Termux 依赖"
pkg update -y
pkg install -y python

echo "[2/6] Install Robinhood Chain Radar V1.3.0"
mkdir -p "$APP_DIR"
for f in "${FILES[@]}"; do cp "$SRC_DIR/$f" "$APP_DIR/$f"; done
for f in "${RUNTIME[@]}"; do cp "$SRC_DIR/$f" "$APP_DIR/$f"; chmod +x "$APP_DIR/$f"; done
cd "$APP_DIR"

echo "[3/6] Python virtualenv"
[[ -d .venv ]] || python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
[[ -f .env ]] || cp .env.example .env

echo "[4/6] Telegram (press Enter to keep current / 回车保留现有配置)"
printf "Bot Token (hidden / 隐藏输入): "; read -r -s TG_TOKEN || true; echo
printf "Chat ID: "; read -r TG_CHAT || true
python - "$APP_DIR/.env" "${TG_TOKEN:-}" "${TG_CHAT:-}" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]); token=sys.argv[2]; chat=sys.argv[3]
lines=p.read_text(encoding='utf-8').splitlines(); out=[]
for line in lines:
    if line.startswith('TELEGRAM_BOT_TOKEN=') and token: out.append('TELEGRAM_BOT_TOKEN='+token)
    elif line.startswith('TELEGRAM_CHAT_ID=') and chat: out.append('TELEGRAM_CHAT_ID='+chat)
    else: out.append(line)
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY

echo "[5/6] Offline/static test"
.venv/bin/python test_static.py

echo "[6/6] RPC self-test"
.venv/bin/python monitor.py --self-test

echo
echo "✅ Robinhood Chain Radar V1.3.0 installed / 安装完成"
echo "Config / 配置: $APP_DIR/.env"
echo "Start / 启动: cd $APP_DIR && bash start-termux.sh"
echo "Status / 状态: cd $APP_DIR && bash status-termux.sh"
echo "ZH Dashboard: http://127.0.0.1:8787/zh"
echo "EN Dashboard: http://127.0.0.1:8787/en"
