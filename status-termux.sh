#!/data/data/com.termux/files/usr/bin/bash
set -u
cd "$(dirname "$0")"
echo "=== Robinhood 链资金雷达 V1.2.5 ==="
if [[ -f supervisor.pid ]] && kill -0 "$(cat supervisor.pid)" 2>/dev/null; then
  PID="$(cat supervisor.pid)"
  echo "Supervisor：运行中 PID=$PID"
  grep -E 'VmRSS|Threads' "/proc/$PID/status" 2>/dev/null || true
else
  echo "Supervisor：已停止"
fi
[[ -f .wake-lock-requested ]] && echo "Wake Lock：已请求" || echo "Wake Lock：未请求"
if command -v termux-job-scheduler >/dev/null 2>&1; then
  echo "Android JobScheduler：可用（15 分钟兜底检查）"
else
  echo "Android JobScheduler：未启用（可选 Termux:API）"
fi
echo "Dashboard：http://127.0.0.1:8787"
