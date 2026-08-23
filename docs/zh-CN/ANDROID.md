# Android / Termux 部署

## 适用场景

适合手机本地测试、移动监控和低成本常驻。Android 会对后台进程施加限制，因此真正 24/7 生产环境优先推荐 Ubuntu VPS。

## 安装

1. 安装 Termux。建议使用 F-Droid/GitHub 发布渠道的新版 Termux。
2. 将仓库克隆到 Termux：

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

3. 编辑：

```bash
nano ~/robinhood-radar/.env
```

至少配置 Telegram：

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

4. 启动：

```bash
cd ~/robinhood-radar
bash start-termux.sh
```

5. 浏览器打开：

```text
http://127.0.0.1:8787
```

## 后台常驻

- Android 电池设置：Termux 设为“不受限制”
- 允许后台活动/自动启动
- 按 Home 键最小化，不要“强制停止”
- 建议安装 Termux:Boot，然后：

```bash
cd ~/robinhood-radar
bash enable-boot.sh
```

可选安装 Termux:API，提供 JobScheduler 兜底检查。

## 状态

```bash
cd ~/robinhood-radar
bash status-termux.sh
```
