#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "请使用 sudo 运行：sudo bash scripts/ubuntu/install.sh"
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="${ROBINHOOD_RADAR_DIR:-/opt/robinhood-chain-radar}"
APP_USER="${ROBINHOOD_RADAR_USER:-robinhood-radar}"

echo "[1/7] 安装系统依赖..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-venv python3-pip ca-certificates curl git

echo "[2/7] 创建系统用户..."
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

echo "[3/7] 安装程序..."
mkdir -p "$APP_DIR"
for f in \
  monitor.py address_intel.py token_intel.py token_radar.py token_worker.py fast_scanner.py event_worker.py \
  swap_filter.py v4_resolver.py native_scanner.py dashboard.py radar_supervisor.py \
  requirements.txt test_static.py test_integration.py .env.example; do
  cp "$SRC_DIR/$f" "$APP_DIR/$f"
done

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$SRC_DIR/.env.example" "$APP_DIR/.env"
fi

echo "[4/7] 创建 Python 虚拟环境..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "[5/7] 安装 systemd 服务..."
cat >/etc/systemd/system/robinhood-chain-radar.service <<EOF
[Unit]
Description=Robinhood Chain Radar
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/radar_supervisor.py
Restart=always
RestartSec=5
TimeoutStopSec=20
KillSignal=SIGINT

# Basic hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable robinhood-chain-radar.service

echo "[6/7] Offline + RPC self-test / 离线 + RPC 自检..."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/test_static.py"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/test_integration.py"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/monitor.py" --self-test

echo "[7/7] 启动..."
systemctl restart robinhood-chain-radar.service

echo
echo "✅ Ubuntu 安装完成"
echo "配置：$APP_DIR/.env"
echo "状态：systemctl status robinhood-chain-radar --no-pager"
echo "日志：journalctl -u robinhood-chain-radar -f"
echo "本机 Dashboard：http://127.0.0.1:8787"
echo
echo "远程查看建议使用 SSH 隧道："
echo "ssh -L 8787:127.0.0.1:8787 user@your-vps"

echo "Language / 语言: set LANGUAGE=zh_CN or LANGUAGE=en_US in .env"
