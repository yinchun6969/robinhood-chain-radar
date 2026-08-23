#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_DIR="$HOME/robinhood-radar"

pkg update -y
pkg install -y python
mkdir -p "$APP_DIR"

cp "$REPO_DIR"/{monitor.py,address_intel.py,token_intel.py,dashboard.py,fast_scanner.py,event_worker.py,swap_filter.py,v4_resolver.py,native_scanner.py,radar_supervisor.py,requirements.txt,test_static.py,.env.example} "$APP_DIR/"
cp "$SCRIPT_DIR"/{start-termux.sh,stop-termux.sh,status-termux.sh,enable-boot.sh,disable-boot.sh,keepalive-job.sh} "$APP_DIR/"
chmod +x "$APP_DIR"/*.sh

cd "$APP_DIR"
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
[[ -f .env ]] || cp .env.example .env

echo "Edit / 编辑: nano $APP_DIR/.env"
echo "Start / 启动: cd $APP_DIR && bash start-termux.sh"
echo "ZH Dashboard: http://127.0.0.1:8787/zh"
echo "EN Dashboard: http://127.0.0.1:8787/en"
