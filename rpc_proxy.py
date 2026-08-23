#!/usr/bin/env python3
"""Local JSON-RPC reverse proxy with automatic upstream failover."""
from __future__ import annotations
import json, logging, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from rpc_pool import FailoverRPC

log=logging.getLogger('rpc-proxy')

class RPCProxy:
    def __init__(self, urls, host='127.0.0.1', port=18766, failback_sec=300):
        self.pool=FailoverRPC(urls,failback_sec=failback_sec,logger=log)
        self.host=host; self.port=int(port); self.httpd=None; self.thread=None
    def _forward(self,payload,timeout=35):
        errors=[]
        for idx in self.pool._ordered_indexes():
            try:
                data,lat=self.pool._post(idx,payload,timeout)
                self.pool._mark_success(idx,lat)
                return data
            except Exception as exc:
                self.pool._mark_failure(idx,exc); errors.append(f"{self.pool.safe_label(self.pool.urls[idx])}: {exc}")
        raise RuntimeError('all upstream RPCs failed: '+' | '.join(errors))
    def start(self):
        outer=self
        class H(BaseHTTPRequestHandler):
            def log_message(self,*a): return
            def do_GET(self):
                if self.path!='/health': self.send_error(404); return
                body=json.dumps({'ok':True,'active':outer.pool.active_label,'endpoints':outer.pool.endpoint_health()}).encode()
                self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                try:
                    n=int(self.headers.get('content-length') or 0); payload=json.loads(self.rfile.read(n) or b'{}')
                    out=outer._forward(payload); body=json.dumps(out,separators=(',',':')).encode()
                    self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
                except Exception as exc:
                    body=json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32098,'message':str(exc)[:500]}}).encode()
                    self.send_response(503); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        self.httpd=ThreadingHTTPServer((self.host,self.port),H)
        self.thread=threading.Thread(target=self.httpd.serve_forever,name='rpc-failover-proxy',daemon=True); self.thread.start()
        return f'http://{self.host}:{self.port}'
    def stop(self):
        if self.httpd: self.httpd.shutdown(); self.httpd.server_close()
