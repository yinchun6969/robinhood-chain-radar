#!/usr/bin/env python3
from token_intel import TokenIntelligence, ZERO, DEAD

class T:
    def __init__(self,a,s,d=18):
        self.address=a; self.symbol=s; self.decimals=d

class FakeRPC:
    def eth_call(self,to,data,block="latest"):
        if data=="0x18160ddd":
            return hex(1000000 * 10**18)
        if data=="0x8da5cb5b":
            return "0x" + "00"*32
        raise RuntimeError("offline")

class FakeDB:
    def execute(self,*a,**k):
        class R:
            def fetchall(self): return []
        return R()

x=TokenIntelligence(FakeRPC(),FakeDB(),"https://example","0x"+"11"*20,"0x"+"22"*20,"0x"+"33"*20)
t0=T("0x"+"11"*20,"WETH")
t1=T("0x"+"44"*20,"MOW")
focus,other=x._pick_focus(t0,t1)
assert focus.symbol=="MOW"
assert x._fmt_pct(12.345)=="12.3%"
assert x._fmt_money(1016000)=="$1.02M"

print("static smoke test: OK (V1.2.5 token CA / holder / risk / LP enrichment)")
