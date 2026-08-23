#!/usr/bin/env python3
"""V1.3.1 runtime launcher: RPC failover proxy + existing supervisor."""
import os
from rpc_proxy import RPCProxy

def upstreams():
    primary=os.getenv('RH_RPC_URL','https://rpc.mainnet.chain.robinhood.com').strip()
    extras=[x.strip() for x in os.getenv('RH_RPC_URLS','').split(',') if x.strip()]
    out=[]
    for x in [primary]+extras:
        if x and x not in out: out.append(x)
    return out

def main():
    urls=upstreams(); port=int(os.getenv('RPC_PROXY_PORT','18766')); failback=int(os.getenv('RPC_FAILBACK_SEC','300'))
    proxy=RPCProxy(urls,port=port,failback_sec=failback)
    local=proxy.start(); os.environ['RH_RPC_URL']=local
    import radar_supervisor
    radar_supervisor.log.info('V1.3.1 RPC proxy active=%s upstreams=%s',proxy.pool.active_label,len(urls))
    radar_supervisor.main()

if __name__=='__main__': main()
