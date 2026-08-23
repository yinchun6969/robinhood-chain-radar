# Android / Termux Deployment

## Use case

Best for mobile testing and low-cost local monitoring. For strict 24/7 production use, Ubuntu VPS is recommended because Android may kill background processes.

## Install

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

Edit `~/robinhood-radar/.env` and configure Telegram credentials. Use `LANGUAGE=en_US` for English alerts or `zh_CN` for Chinese.

Start:

```bash
cd ~/robinhood-radar
bash start-termux.sh
```

Dashboard: `/zh` for Chinese, `/en` for English.

For background operation, set Termux battery usage to unrestricted, allow background activity, use Home instead of force-stop, and optionally install Termux:Boot.
