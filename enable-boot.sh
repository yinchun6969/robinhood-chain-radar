#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
APP_DIR="$HOME/robinhood-radar"
BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"
cat > "$BOOT_DIR/robinhood-radar.sh" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
sleep 20
termux-wake-lock 2>/dev/null || true
cd "$APP_DIR"
bash start-termux.sh >> boot.log 2>&1
EOF
chmod +x "$BOOT_DIR/robinhood-radar.sh"
echo "✅ 已创建开机恢复脚本：$BOOT_DIR/robinhood-radar.sh"
echo "安装 Termux:Boot 后至少打开一次，并把 Termux 与 Termux:Boot 的电池策略设为“不受限制”。"
echo "可选：安装 Termux:API App，并执行 pkg install termux-api，可启用 15 分钟一次的 JobScheduler 兜底检查。"
echo "注意：Android“强制停止”无法被 Boot/JobScheduler 绕过。"
