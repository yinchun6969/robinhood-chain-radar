#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "请使用 sudo 运行"
  exit 1
fi
APP_DIR="${ROBINHOOD_RADAR_DIR:-/opt/robinhood-chain-radar}"
systemctl disable --now robinhood-chain-radar.service 2>/dev/null || true
rm -f /etc/systemd/system/robinhood-chain-radar.service
systemctl daemon-reload
echo "systemd 服务已删除。"
echo "数据目录仍保留在 $APP_DIR；如确认无需备份，可手动删除。"
