# Ubuntu 24.04 / 22.04 部署

## 推荐配置

最低：
- 1 vCPU
- 1 GB RAM
- 5 GB 磁盘

建议：
- 2 vCPU
- 2 GB RAM
- 专用/高额度 Robinhood Chain RPC

## 一键安装

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

安装目录默认：

```text
/opt/robinhood-chain-radar
```

编辑配置：

```bash
sudo nano /opt/robinhood-chain-radar/.env
sudo systemctl restart robinhood-chain-radar
```

## 服务管理

```bash
sudo systemctl status robinhood-chain-radar
sudo systemctl restart robinhood-chain-radar
sudo journalctl -u robinhood-chain-radar -f
```

## Dashboard

默认只监听 VPS 本机：

```text
127.0.0.1:8787
```

不要为了方便直接开放 `0.0.0.0`。远程查看使用 SSH 隧道：

```bash
ssh -L 8787:127.0.0.1:8787 user@VPS_IP
```

本地浏览器访问：

```text
http://127.0.0.1:8787
```
