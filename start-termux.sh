#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
PIDFILE="supervisor.pid"
alive(){ [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; }

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock || true
  touch .wake-lock-requested
fi

if alive; then
  echo "Robinhood Radar V1.3.1 已运行 / already running, PID=$(cat "$PIDFILE")"
else
  nohup .venv/bin/python launcher.py >/dev/null 2>&1 &
  echo $! > "$PIDFILE"
  sleep 2
  if ! alive; then
    echo "❌ Launcher 启动失败 / failed"
    tail -n 100 supervisor.log 2>/dev/null || true
    exit 1
  fi
  echo "✅ Robinhood Radar V1.3.1 已启动 / started, PID=$(cat "$PIDFILE")"
fi

if command -v termux-job-scheduler >/dev/null 2>&1 && [[ -f keepalive-job.sh ]]; then
  termux-job-scheduler --job-id 4663 --script "$PWD/keepalive-job.sh" --period-ms 900000 --persisted true >/dev/null 2>&1 || true
fi

echo "RPC Failover Health: http://127.0.0.1:18766/health"
echo "Dashboard 中文: http://127.0.0.1:8787/zh"
echo "Dashboard English: http://127.0.0.1:8787/en"
echo "Doctor / 自检: .venv/bin/python doctor.py"
echo "状态 / status: bash status-termux.sh"
echo "Android: 按 Home 键最小化 Termux，不要强制停止。"
