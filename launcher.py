#!/usr/bin/env python3
"""V1.3.1 runtime launcher: load .env, start RPC failover proxy, then supervisor."""
import os
from pathlib import Path


def load_dotenv():
    p = Path(__file__).with_name('.env')
    if not p.exists():
        return
    for raw in p.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_dotenv()
DEFAULT_RPC = 'https://rpc.mainnet.chain.robinhood.com'


def upstreams():
    # RADAR_PRIMARY_RPC survives os.execv() after the supervisor has replaced
    # RH_RPC_URL with the local proxy address.
    primary = os.getenv('RADAR_PRIMARY_RPC', '').strip() or os.getenv('RH_RPC_URL', DEFAULT_RPC).strip()
    extras = [x.strip() for x in os.getenv('RH_RPC_URLS', '').split(',') if x.strip()]
    out = []
    for x in [primary] + extras:
        if x and x not in out:
            out.append(x)
    return out


def main():
    from rpc_proxy import RPCProxy

    urls = upstreams()
    if not os.getenv('RADAR_PRIMARY_RPC'):
        os.environ['RADAR_PRIMARY_RPC'] = urls[0]
    os.environ['RADAR_ENTRYPOINT'] = str(Path(__file__).resolve())

    port = int(os.getenv('RPC_PROXY_PORT', '18766'))
    failback = int(os.getenv('RPC_FAILBACK_SEC', '300'))
    proxy = RPCProxy(urls, port=port, failback_sec=failback)
    local = proxy.start()
    os.environ['RH_RPC_URL'] = local

    import radar_supervisor
    # V1.3.1 keeps the stable V1.3 monitor core intact while the launcher owns
    # the reliability layer. Update the shared runtime label before alerts fire.
    radar_supervisor.monitor.RADAR_VERSION = '1.3.1'
    radar_supervisor.log.info(
        'V1.3.1 RPC failover proxy active=%s upstreams=%s',
        proxy.pool.active_label,
        len(urls),
    )
    radar_supervisor.main()


if __name__ == '__main__':
    main()
