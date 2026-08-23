#!/data/data/com.termux/files/usr/bin/bash
APP="$HOME/robinhood-radar"
cd "$APP" || exit 0
if [[ ! -f supervisor.pid ]] || ! kill -0 "$(cat supervisor.pid 2>/dev/null)" 2>/dev/null; then
  bash start-termux.sh >> keepalive.log 2>&1
fi
