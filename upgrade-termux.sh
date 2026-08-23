#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/robinhood-radar"
[[ -d "$APP_DIR" ]] || { echo "未发现 / not found: $APP_DIR"; exit 1; }

echo "[1/6] Stop current radar / 停止当前版本"
cd "$APP_DIR"
bash stop-termux.sh 2>/dev/null || true
sleep 1

echo "[2/6] Backup config + database / 备份配置与数据库"
STAMP="$(date +%s)"
cp .env ".env.backup.$STAMP" 2>/dev/null || true
cp radar.db "radar.db.backup.$STAMP" 2>/dev/null || true

echo "[3/6] Copy V1.3.1 files / 更新文件"
FILES=(
  monitor.py address_intel.py token_intel.py token_radar.py token_worker.py dashboard.py
  fast_scanner.py event_worker.py swap_filter.py v4_resolver.py native_scanner.py radar_supervisor.py
  launcher.py rpc_pool.py rpc_proxy.py lp_rug.py doctor.py
  start-termux.sh stop-termux.sh status-termux.sh enable-boot.sh disable-boot.sh keepalive-job.sh
  requirements.txt test_static.py test_integration.py test_v131.py
)
for f in "${FILES[@]}"; do cp "$SRC_DIR/$f" "$APP_DIR/$f"; done
chmod +x "$APP_DIR"/*.sh
cd "$APP_DIR"
.venv/bin/pip install -r requirements.txt >/dev/null

ensure_env(){ local k="$1" v="$2"; grep -q "^${k}=" .env 2>/dev/null || echo "${k}=${v}" >> .env; }
ensure_env RH_RPC_URLS ""
ensure_env RPC_FAILBACK_SEC 300
ensure_env RPC_PROXY_PORT 18766
ensure_env LP_RUG_MIN_REMOVE_USD 250000
ensure_env LP_RUG_ABSOLUTE_USD 1000000
ensure_env LP_RUG_P0_DRAIN_PCT 50
ensure_env LP_RUG_P1_DRAIN_PCT 30
ensure_env LP_RUG_BASELINE_MIN_USD 500000
ensure_env LP_RUG_WINDOW_HOURS 24
ensure_env LP_RUG_COOLDOWN_MIN 15
ensure_env TOKEN_RADAR_MIN_EVENT_USD 100000
ensure_env TOKEN_SIGNAL_MIN_SCORE 55
ensure_env TOKEN_CORRELATION_WINDOW_MIN 180
ensure_env TOKEN_DEEP_SCAN_TTL_SEC 600
ensure_env TOKEN_SIGNAL_COOLDOWN_MIN 30
ensure_env SUPERVISOR_SCANNER_STALE_SEC 180
ensure_env SUPERVISOR_MAX_RSS_MB 700
ensure_env MAINTENANCE_INTERVAL_SEC 60
ensure_env SWAP_BACKLOG_MAX 50000
ensure_env SWAP_MAX_AGE_MIN 30
ensure_env FAST_MAX_AGE_MIN 30

echo "[4/6] Offline migration/static test / 离线迁移与自检"
.venv/bin/python test_static.py
.venv/bin/python test_integration.py
.venv/bin/python test_v131.py
.venv/bin/python - <<'PY'
import monitor
import lp_rug
lp_rug.ensure(monitor.db)
print('DB schema V1.3.1: OK')
PY

echo "[5/6] RPC self-test"
.venv/bin/python monitor.py --self-test

echo "[6/6] Start V1.3.1"
bash start-termux.sh
sleep 3
bash status-termux.sh

echo
echo "Doctor / 自检: .venv/bin/python doctor.py"
