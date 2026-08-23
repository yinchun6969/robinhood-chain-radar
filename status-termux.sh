#!/data/data/com.termux/files/usr/bin/bash
set -u
cd "$(dirname "$0")"
echo "=== Robinhood Chain Radar V1.3.1 ==="
if [[ -f supervisor.pid ]] && kill -0 "$(cat supervisor.pid)" 2>/dev/null; then
  PID="$(cat supervisor.pid)"
  echo "Launcher/Supervisor: LIVE PID=$PID"
  grep -E 'VmRSS|Threads' "/proc/$PID/status" 2>/dev/null || true
else
  echo "Launcher/Supervisor: STOPPED"
fi
[[ -f .wake-lock-requested ]] && echo "Wake Lock: requested" || echo "Wake Lock: not requested"
if command -v termux-job-scheduler >/dev/null 2>&1; then
  echo "Android JobScheduler: available"
else
  echo "Android JobScheduler: optional (Termux:API)"
fi
if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 2 http://127.0.0.1:18766/health >/dev/null 2>&1; then
    echo "RPC Failover Proxy: LIVE http://127.0.0.1:18766/health"
  else
    echo "RPC Failover Proxy: unavailable"
  fi
fi
echo "Dashboard 中文: http://127.0.0.1:8787/zh"
echo "Dashboard English: http://127.0.0.1:8787/en"
echo "Doctor / 自检: .venv/bin/python doctor.py"
