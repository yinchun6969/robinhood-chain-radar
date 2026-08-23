#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$HOME/robinhood-radar" 2>/dev/null || cd "$(dirname "$0")"
if [[ -f supervisor.pid ]]; then
  PID="$(cat supervisor.pid 2>/dev/null || true)"
  [[ -n "$PID" ]] && kill "$PID" 2>/dev/null || true
  rm -f supervisor.pid
fi
command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock || true
echo "Stopped / 已停止"
