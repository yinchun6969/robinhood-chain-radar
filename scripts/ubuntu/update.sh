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
cp "$APP_DIR/.env" "$APP_DIR/.env.backup.$(date +%s)" 2>/dev/null || true
cp "$APP_DIR/radar.db" "$APP_DIR/radar.db.backup.$(date +%s)" 2>/dev/null || true

for f in \
  monitor.py address_intel.py token_intel.py token_radar.py token_worker.py fast_scanner.py event_worker.py \
  swap_filter.py v4_resolver.py native_scanner.py dashboard.py radar_supervisor.py \
  requirements.txt test_static.py test_integration.py; do
  cp "$SRC_DIR/$f" "$APP_DIR/$f"
done

"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
ensure_env(){ local k="$1" v="$2"; grep -q "^${k}=" "$APP_DIR/.env" 2>/dev/null || echo "${k}=${v}" >> "$APP_DIR/.env"; }
ensure_env TOKEN_RADAR_MIN_EVENT_USD 100000
ensure_env TOKEN_SIGNAL_MIN_SCORE 55
ensure_env TOKEN_CORRELATION_WINDOW_MIN 180
ensure_env TOKEN_DEEP_SCAN_TTL_SEC 600
ensure_env TOKEN_SIGNAL_COOLDOWN_MIN 30
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/test_static.py"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/test_integration.py"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/monitor.py" --self-test
systemctl restart robinhood-chain-radar.service
systemctl status robinhood-chain-radar.service --no-pager
