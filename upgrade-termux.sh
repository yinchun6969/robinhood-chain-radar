#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/robinhood-radar"
[[ -d "$APP_DIR" ]] || { echo "未发现 $APP_DIR"; exit 1; }

echo "[1/7] 停止旧 V1.2.3..."
cd "$APP_DIR"
bash stop-termux.sh 2>/dev/null || true
pkill -f "$APP_DIR/.venv/bin/python" 2>/dev/null || true
sleep 1

echo "[2/7] 备份..."
STAMP="$(date +%s)"
cp .env ".env.backup.$STAMP" 2>/dev/null || true
cp radar.db "radar.db.backup.$STAMP" 2>/dev/null || true

echo "[3/7] 安装 V1.2.5 单进程 Supervisor..."
cp "$SRC_DIR"/{monitor.py,address_intel.py,dashboard.py,fast_scanner.py,event_worker.py,swap_filter.py,v4_resolver.py,native_scanner.py,radar_supervisor.py,start-termux.sh,stop-termux.sh,status-termux.sh,enable-boot.sh,disable-boot.sh,requirements.txt,test_static.py} "$APP_DIR/"
cd "$APP_DIR"
.venv/bin/pip install -r requirements.txt >/dev/null

ensure_env(){
  local key="$1" value="$2"
  grep -q "^${key}=" .env 2>/dev/null || echo "${key}=${value}" >> .env
}
ensure_env SUPERVISOR_SCANNER_STALE_SEC 180
ensure_env SUPERVISOR_MAX_RSS_MB 700
ensure_env MAINTENANCE_INTERVAL_SEC 60
ensure_env SWAP_BACKLOG_MAX 50000
ensure_env SWAP_MAX_AGE_MIN 30
ensure_env FAST_MAX_AGE_MIN 30

echo "[4/7] 数据库迁移..."
.venv/bin/python - <<'PYDB'
import sqlite3
import fast_scanner
import monitor

d=sqlite3.connect("radar.db",timeout=30)
d.execute("PRAGMA journal_mode=WAL")
d.execute("PRAGMA busy_timeout=20000")
fast_scanner.ensure(d)
d.execute("UPDATE raw_events SET status=0,claimed_at=NULL WHERE status=1")
d.execute("UPDATE swap_events SET status=0,claimed_at=NULL WHERE status=1")
# New priority classes.
d.execute("UPDATE raw_events SET priority=130 WHERE topic0=?",(monitor.TOPIC_DEPOSIT_FINALIZED.lower(),))
d.execute("UPDATE raw_events SET priority=120 WHERE topic0 IN (?,?,?,?,?)",(
    monitor.TOPIC_V2_MINT.lower(),monitor.TOPIC_V2_BURN.lower(),
    monitor.TOPIC_V3_MINT.lower(),monitor.TOPIC_V3_BURN.lower(),
    monitor.TOPIC_V4_MODIFY_LIQUIDITY.lower()
))
d.execute("UPDATE raw_events SET priority=90 WHERE topic0 IN (?,?,?)",(
    monitor.TOPIC_V2_PAIR_CREATED.lower(),monitor.TOPIC_V3_POOL_CREATED.lower(),
    monitor.TOPIC_V4_INITIALIZE.lower()
))
d.commit()
print("Bridge queue:",d.execute("SELECT COUNT(*) FROM raw_events WHERE status=0 AND priority=130").fetchone()[0])
print("LP queue:",d.execute("SELECT COUNT(*) FROM raw_events WHERE status=0 AND priority=120").fetchone()[0])
print("Metadata:",d.execute("SELECT COUNT(*) FROM raw_events WHERE status=0 AND priority<120").fetchone()[0])
print("Swap:",d.execute("SELECT COUNT(*) FROM swap_events WHERE status=0").fetchone()[0])
d.close()
PYDB

echo "[5/7] 自检..."
.venv/bin/python monitor.py --self-test
.venv/bin/python test_static.py

echo "[6/7] 启动 Supervisor..."
bash start-termux.sh
sleep 4
bash status-termux.sh

echo "[7/7] 完成"
echo
echo "浏览器：http://127.0.0.1:8787"
echo
echo "建议再执行："
echo "  cd $APP_DIR && bash enable-boot.sh"
echo "然后安装并至少打开一次 Termux:Boot。"
