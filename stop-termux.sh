#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f supervisor.pid ]]; then
  PID="$(cat supervisor.pid 2>/dev/null || true)"
  if [[ -n "${PID:-}" ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    for i in 1 2 3 4 5; do
      kill -0 "$PID" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$PID" 2>/dev/null || true
    echo "已停止 Supervisor PID=$PID"
  fi
  rm -f supervisor.pid
fi
rm -f .wake-lock-requested
if command -v termux-wake-unlock >/dev/null 2>&1; then termux-wake-unlock || true; fi
