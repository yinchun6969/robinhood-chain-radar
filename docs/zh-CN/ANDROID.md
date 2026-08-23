# Android / Termux 部署 — V1.3.0

## 适用场景

适合手机本地测试、移动监控和低成本常驻。Android 可能主动限制后台进程，因此严格 24/7 生产环境仍优先推荐 Ubuntu VPS。

## 首次安装

建议使用 F-Droid 或 Termux 官方 GitHub 发布渠道的新版本 Termux。

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

安装器会复制运行文件到：

```text
~/robinhood-radar
```

然后编辑：

```bash
nano ~/robinhood-radar/.env
```

至少建议配置：

```env
LANGUAGE=zh_CN
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TOKEN_RADAR_MIN_EVENT_USD=100000
TOKEN_SIGNAL_MIN_SCORE=55
TOKEN_CORRELATION_WINDOW_MIN=180
TOKEN_SIGNAL_COOLDOWN_MIN=30
```

启动：

```bash
cd ~/robinhood-radar
bash start-termux.sh
```

Dashboard：

```text
中文：http://127.0.0.1:8787/zh
英文：http://127.0.0.1:8787/en
```

## 从旧版升级到 V1.3.0

在仓库目录拉取新版后运行升级脚本：

```bash
cd ~/robinhood-chain-radar
git pull
bash upgrade-termux.sh
```

升级脚本会先备份现有 `.env` 与 `radar.db`，再更新代码和数据库结构。V1.3.0 只新增 Token Radar 表，不删除 V1.2.x 的旧地址/告警数据。

## 后台常驻

- Android 电池设置中将 Termux 设为“不受限制”；
- 允许后台活动/自动启动；
- 正常按 Home 键最小化，不要对 Termux 执行“强制停止”；
- 推荐安装 Termux:Boot，然后：

```bash
cd ~/robinhood-radar
bash enable-boot.sh
```

如已安装 Termux:API，可使用 JobScheduler 做额外保活检查。

## 状态与日志

```bash
cd ~/robinhood-radar
bash status-termux.sh
```

V1.3.0 Supervisor 会同时管理 Fast Scanner、Priority Workers、Swap Filters、V4 Resolver、Native Scanner、Token Radar Worker 和 Dashboard。

## 手机端注意事项

- `127.0.0.1` 只允许本机访问，安全性高于直接开放公网；
- 关闭浏览器不会停止 Radar；
- Android “强制停止 Termux”会终止进程，直到用户再次启动；
- 公共 RPC 有速率限制，持续高频监控建议使用更高额度 RPC。

## 本地健康检查

```text
http://127.0.0.1:8787/api/health
```

返回扫链、Token Radar、Supervisor、区块延迟和 Token 优先队列状态。
