#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "请使用 sudo 运行"
  exit 1
fi
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="${ROBINHOOD_RADAR_DIR:-/opt/robinhood-chain-radar}"
APP_USER="${ROBINHOOD_RADAR_USER:-robinhood-radar}"

systemctl stop robinhood-chain-radar.service || true
STAMP="$(date +%s)"
cp "$APP_DIR/.env" "$APP_DIR/.env.backup.$STAMP" 2>/dev/null || true
cp "$APP_DIR/radar.db" "$APP_DIR/radar.db.backup.$STAMP" 2>/dev/null || true

for f in \
  monitor.py address_intel.py token_intel.py token_radar.py token_worker.py fast_scanner.py event_worker.py \
  swap_filter.py v4_resolver.py native_scanner.py dashboard.py radar_supervisor.py \
  launcher.py rpc_pool.py rpc_proxy.py lp_rug.py doctor.py \
  requirements.txt test_static.py test_integration.py test_v131.py; do
  cp "$SRC_DIR/$f" "$APP_DIR/$f"
done

"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
ensure_env(){ local k="$1" v="$2"; grep -q "^${k}=" "$APP_DIR/.env" 2>/dev/null || echo "${k}=${v}" >> "$APP_DIR/.env"; }
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

# Existing V1.3.0 units started radar_supervisor.py directly. Switch them to
# launcher.py so RPC failover remains active after the upgrade.
UNIT=/etc/systemd/system/robinhood-chain-radar.service
if [[ -f "$UNIT" ]]; then
  sed -i 's#ExecStart=.*radar_supervisor.py#ExecStart='"$APP_DIR"'/.venv/bin/python '"$APP_DIR"'/launcher.py#' "$UNIT"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"
systemctl daemon-reload
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/test_static.py"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/test_integration.py"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/test_v131.py"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/monitor.py" --self-test
systemctl restart robinhood-chain-radar.service
systemctl status robinhood-chain-radar.service --no-pager

echo "Doctor: sudo -u $APP_USER $APP_DIR/.venv/bin/python $APP_DIR/doctor.py"
