# Android / Termux Deployment — V1.3.0

## Use case

Best for mobile testing, portable monitoring and low-cost local operation. Android may kill background processes, so Ubuntu VPS is still recommended for strict 24/7 production use.

## Fresh install

Use a recent Termux build from F-Droid or the official Termux GitHub releases.

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

Runtime files are installed under:

```text
~/robinhood-radar
```

Edit configuration:

```bash
nano ~/robinhood-radar/.env
```

Recommended minimum:

```env
LANGUAGE=en_US
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TOKEN_RADAR_MIN_EVENT_USD=100000
TOKEN_SIGNAL_MIN_SCORE=55
TOKEN_CORRELATION_WINDOW_MIN=180
TOKEN_SIGNAL_COOLDOWN_MIN=30
```

Start:

```bash
cd ~/robinhood-radar
bash start-termux.sh
```

Dashboard:

```text
Chinese: http://127.0.0.1:8787/zh
English: http://127.0.0.1:8787/en
```

## Upgrade from an older version

Pull the repository and run the upgrade helper:

```bash
cd ~/robinhood-chain-radar
git pull
bash upgrade-termux.sh
```

The upgrader backs up `.env` and `radar.db` before replacing runtime files and applying the V1.3 schema. Existing V1.2.x address/alert data is preserved.

## Background operation

- Set Termux battery usage to unrestricted.
- Allow background activity / autostart where your Android vendor exposes those settings.
- Use Home to minimize Termux; do not force-stop it.
- Termux:Boot is recommended; then run `bash enable-boot.sh` in `~/robinhood-radar`.
- Termux:API can optionally provide a JobScheduler keepalive check.

## Status

```bash
cd ~/robinhood-radar
bash status-termux.sh
```

V1.3.0 Supervisor manages the Fast Scanner, priority workers, swap filters, V4 resolver, native scanner, Token Radar worker and Dashboard.

## Notes

The Dashboard binds to localhost only. Closing the browser does not stop Radar, but Android's Force Stop action will terminate Termux processes until the app is started again. A higher-rate-limit RPC is recommended for sustained scanning.

## Local health check

```text
http://127.0.0.1:8787/api/health
```

Returns scanner, Token Radar, supervisor, block-lag and priority-queue health.
