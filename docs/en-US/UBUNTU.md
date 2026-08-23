# Ubuntu 22.04 / 24.04 Deployment

## Recommended resources

Minimum: 1 vCPU / 1 GB RAM / 5 GB disk. Recommended: 2 vCPU / 2 GB RAM and a dedicated or higher-rate-limit Robinhood Chain RPC.

## Install

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

Default install path: `/opt/robinhood-chain-radar`.

Service management:

```bash
sudo systemctl status robinhood-chain-radar
sudo systemctl restart robinhood-chain-radar
sudo journalctl -u robinhood-chain-radar -f
```

The Dashboard binds to `127.0.0.1:8787` by default. Use an SSH tunnel instead of exposing it publicly:

```bash
ssh -L 8787:127.0.0.1:8787 user@VPS_IP
```
