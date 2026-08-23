# Ubuntu 22.04 / 24.04 部署 — V1.3.0

## 推荐配置

最低：

- 1 vCPU
- 1 GB RAM
- 5 GB 磁盘

建议长期运行：

- 2 vCPU
- 2 GB RAM
- 10 GB+ 磁盘
- 专用或高额度 Robinhood Chain RPC

## 一键安装

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

默认安装目录：

```text
/opt/robinhood-chain-radar
```

配置：

```bash
sudo nano /opt/robinhood-chain-radar/.env
sudo systemctl restart robinhood-chain-radar
```

建议至少检查：

```env
LANGUAGE=zh_CN
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TOKEN_RADAR_MIN_EVENT_USD=100000
TOKEN_SIGNAL_MIN_SCORE=55
TOKEN_CORRELATION_WINDOW_MIN=180
TOKEN_SIGNAL_COOLDOWN_MIN=30
```

## 从 V1.2.x 升级

在新的 Git 仓库目录执行：

```bash
git pull
sudo bash scripts/ubuntu/update.sh
```

更新脚本会停止服务、备份现有 `.env` / `radar.db`、更新运行文件、重新安装依赖、执行静态测试和 RPC 自检，然后重新启动 systemd 服务。

## 服务管理

```bash
sudo systemctl status robinhood-chain-radar --no-pager
sudo systemctl restart robinhood-chain-radar
sudo journalctl -u robinhood-chain-radar -f
```

## Dashboard

默认只监听：

```text
127.0.0.1:8787
```

远程访问不要直接改成 `0.0.0.0`。推荐 SSH 隧道：

```bash
ssh -L 8787:127.0.0.1:8787 user@VPS_IP
```

然后本机浏览器打开：

```text
http://127.0.0.1:8787/zh
http://127.0.0.1:8787/en
```

## V1.3.0 数据库

旧 `radar.db` 可原地迁移。启动时自动创建 `token_events`、`token_profiles`、`token_scan_queue`、`token_signals`，不会删除旧数据。维护线程会限制历史 Token 事件持续增长。

## 本地健康检查

```text
http://127.0.0.1:8787/api/health
```

返回扫链、Token Radar、Supervisor、区块延迟和 Token 优先队列状态。
