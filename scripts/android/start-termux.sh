#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
# When installed, this script is copied to ~/robinhood-radar.
[[ -f radar_supervisor.py ]] || cd "$HOME/robinhood-radar"
PIDFILE=supervisor.pid
alive(){ [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; }
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true
if ! alive; then
  nohup .venv/bin/python radar_supervisor.py >/dev/null 2>&1 &
  echo $! > "$PIDFILE"
  sleep 2
fi
alive || { echo "Supervisor failed / 启动失败"; exit 1; }
echo "Robinhood Chain Radar LIVE PID=$(cat "$PIDFILE")"
echo "ZH: http://127.0.0.1:8787/zh"
echo "EN: http://127.0.0.1:8787/en"
