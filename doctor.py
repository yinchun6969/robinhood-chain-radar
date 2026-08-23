#!/usr/bin/env python3
import os,sys,json,sqlite3,platform,requests
from pathlib import Path
from rpc_pool import FailoverRPC
APP=Path(__file__).resolve().parent

def urls():
 p=os.getenv('RH_RPC_URL','https://rpc.mainnet.chain.robinhood.com').strip(); xs=[x.strip() for x in os.getenv('RH_RPC_URLS','').split(',') if x.strip()]; out=[]
 for x in [p]+xs:
  if x and x not in out: out.append(x)
 return out
def main():
 rows=[]; add=lambda s,n,d='':rows.append({'status':s,'name':n,'detail':str(d)})
 add('OK' if sys.version_info>=(3,10) else 'FAIL','Python',platform.python_version())
 pool=FailoverRPC(urls(),failback_sec=int(os.getenv('RPC_FAILBACK_SEC','300'))); probes=pool.probe_all(5)
 good=[x for x in probes if x.get('ok') and x.get('chain_id')==4663]
 for x in probes:add('OK' if x.get('ok') and x.get('chain_id')==4663 else 'WARN','RPC',f"{x.get('label')} · {x.get('latency_ms','?')}ms · chain {x.get('chain_id','?')}")
 if not good:add('FAIL','RPC failover','no healthy Chain 4663 endpoint')
 db=Path(os.getenv('DB_PATH',str(APP/'radar.db'))).expanduser()
 try:
  d=sqlite3.connect(db,timeout=5); integ=d.execute('PRAGMA integrity_check').fetchone()[0]; add('OK' if integ=='ok' else 'FAIL','SQLite',f'{db} · {integ}')
  tables={r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}; add('OK' if 'token_events' in tables else 'WARN','Token schema','token_events' if 'token_events' in tables else 'not initialized'); d.close()
 except Exception as e:add('FAIL','SQLite',e)
 try:r=requests.get(f"http://127.0.0.1:{os.getenv('DASHBOARD_PORT','8787')}/api/health",timeout=2); add('OK' if r.ok else 'WARN','Dashboard',r.status_code)
 except Exception:add('WARN','Dashboard','not running')
 try:r=requests.get(f"http://127.0.0.1:{os.getenv('RPC_PROXY_PORT','18766')}/health",timeout=2); add('OK' if r.ok else 'WARN','RPC proxy',r.status_code)
 except Exception:add('WARN','RPC proxy','not running (start via launcher.py)')
 fails=sum(x['status']=='FAIL' for x in rows); warns=sum(x['status']=='WARN' for x in rows); result={'version':'1.3.1','status':'FAIL' if fails else 'WARN' if warns else 'HEALTHY','checks':rows}
 if '--json' in sys.argv: print(json.dumps(result,ensure_ascii=False,indent=2))
 else:
  print('Robinhood Chain Radar Doctor V1.3.1'); print('='*52)
  for x in rows:print(f"[{x['status']}] {x['name']}: {x['detail']}")
  print('='*52); print('STATUS:',result['status'])
 raise SystemExit(1 if fails else 0)
if __name__=='__main__':main()
