# Ubuntu 22.04 / 24.04 Deployment — V1.3.0

## Recommended resources

Minimum:

- 1 vCPU
- 1 GB RAM
- 5 GB disk

Recommended for sustained operation:

- 2 vCPU
- 2 GB RAM
- 10 GB+ disk
- dedicated or higher-rate-limit Robinhood Chain RPC

## Install

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

Default application directory:

```text
/opt/robinhood-chain-radar
```

Configure and restart:

```bash
sudo nano /opt/robinhood-chain-radar/.env
sudo systemctl restart robinhood-chain-radar
```

Recommended settings to review:

```env
LANGUAGE=en_US
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TOKEN_RADAR_MIN_EVENT_USD=100000
TOKEN_SIGNAL_MIN_SCORE=55
TOKEN_CORRELATION_WINDOW_MIN=180
TOKEN_SIGNAL_COOLDOWN_MIN=30
```

## Upgrade from V1.2.x

From the Git checkout:

```bash
git pull
sudo bash scripts/ubuntu/update.sh
```

The updater stops the service, backs up the existing `.env` / `radar.db`, refreshes runtime files, installs dependencies, runs offline static tests and an RPC self-test, then restarts the systemd service.

## Service management

```bash
sudo systemctl status robinhood-chain-radar --no-pager
sudo systemctl restart robinhood-chain-radar
sudo journalctl -u robinhood-chain-radar -f
```

## Dashboard

The Dashboard binds to localhost by default:

```text
127.0.0.1:8787
```

Do not expose it by casually switching to `0.0.0.0`. Use an SSH tunnel:

```bash
ssh -L 8787:127.0.0.1:8787 user@VPS_IP
```

Then open:

```text
http://127.0.0.1:8787/zh
http://127.0.0.1:8787/en
```

## V1.3.0 database migration

Existing `radar.db` files are migrated in place. Startup creates `token_events`, `token_profiles`, `token_scan_queue` and `token_signals` without deleting older data. Maintenance bounds retained token-event history for long-running installs.

## Local health check

```text
http://127.0.0.1:8787/api/health
```

Returns scanner, Token Radar, supervisor, block-lag and priority-queue health.
