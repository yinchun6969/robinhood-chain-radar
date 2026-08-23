#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${HOME}/robinhood-radar"

echo "[1/6] 安装 Termux 依赖..."
pkg update -y
pkg install -y python

echo "[2/6] 复制程序到 Termux 内部目录..."
mkdir -p "$APP_DIR"
cp "$SRC_DIR/monitor.py" "$SRC_DIR/address_intel.py" "$SRC_DIR/dashboard.py" "$SRC_DIR/fast_scanner.py" "$SRC_DIR/event_worker.py" "$SRC_DIR/swap_filter.py" "$SRC_DIR/v4_resolver.py" "$SRC_DIR/native_scanner.py" "$SRC_DIR/radar_supervisor.py" "$SRC_DIR/start-termux.sh" "$SRC_DIR/stop-termux.sh" "$SRC_DIR/status-termux.sh" "$SRC_DIR/enable-boot.sh" "$SRC_DIR/disable-boot.sh" "$SRC_DIR/requirements.txt" "$SRC_DIR/test_static.py" "$SRC_DIR/.env.example" "$APP_DIR/"

cd "$APP_DIR"

echo "[3/6] 创建 Python 环境..."
if [[ ! -d ".venv" ]]; then
  python -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [[ ! -f ".env" ]]; then
  cp .env.example .env
fi

echo "[4/6] Telegram 配置"
printf "Telegram Bot Token（暂时不填可直接回车）: "
read -r TG_TOKEN
printf "Telegram Chat ID（暂时不填可直接回车）: "
read -r TG_CHAT

python - "$APP_DIR/.env" "$TG_TOKEN" "$TG_CHAT" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
token, chat = sys.argv[2], sys.argv[3]
lines = p.read_text(encoding="utf-8").splitlines()
out = []
for line in lines:
    if line.startswith("TELEGRAM_BOT_TOKEN=") and token:
        out.append("TELEGRAM_BOT_TOKEN=" + token)
    elif line.startswith("TELEGRAM_CHAT_ID=") and chat:
        out.append("TELEGRAM_CHAT_ID=" + chat)
    else:
        out.append(line)
p.write_text("\n".join(out) + "\n", encoding="utf-8")
PY

echo "[5/6] Robinhood Chain RPC 自检..."
.venv/bin/python monitor.py --self-test

echo "[6/6] 完成"
echo
echo "程序目录：$APP_DIR"
echo "前台试跑：cd $APP_DIR && .venv/bin/python radar_supervisor.py"
echo "后台启动：cd $APP_DIR && bash start-termux.sh"
echo "查看日志：tail -f $APP_DIR/supervisor.log"
echo "停止后台：cd $APP_DIR && bash stop-termux.sh"
