#!/usr/bin/env python3
import json
import time
import math
import requests

ZERO = "0x0000000000000000000000000000000000000000"
DEAD = "0x000000000000000000000000000000000000dead"
TOTAL_SUPPLY_SEL = "0x18160ddd"
BALANCE_OF_SEL = "0x70a08231"
OWNER_SEL = "0x8da5cb5b"

class TokenIntelligence:
    def __init__(self, rpc, db, explorer, weth, usdg, v4_pool_manager, language="zh_CN"):
        self.rpc = rpc
        self.db = db
        self.explorer = explorer.rstrip("/")
        self.api = self.explorer + "/api/v2"
        self.weth = (weth or "").lower()
        self.usdg = (usdg or "").lower()
        self.v4_pm = (v4_pool_manager or "").lower()
        self.language = language or "zh_CN"
        self._cache = {}
        self._session = requests.Session()

    def _get(self, path, ttl=300, timeout=6):
        now = time.time()
        key = path
        cached = self._cache.get(key)
        if cached and now - cached[0] < ttl:
            return cached[1]
        try:
            r = self._session.get(self.api + path, timeout=timeout)
            if not r.ok:
                return None
            data = r.json()
            self._cache[key] = (now, data)
            return data
        except Exception:
            return None

    @staticmethod
    def _word_addr(raw):
        if not raw or raw == "0x":
            return None
        h = raw[2:] if raw.startswith("0x") else raw
        if len(h) < 40:
            return None
        return ("0x" + h[-40:]).lower()

    def _total_supply(self, ca):
        try:
            raw = self.rpc.eth_call(ca, TOTAL_SUPPLY_SEL)
            return int(raw, 16)
        except Exception:
            return None

    def _owner(self, ca):
        try:
            raw = self.rpc.eth_call(ca, OWNER_SEL)
            return self._word_addr(raw)
        except Exception:
            return None

    def _balance_of(self, token, addr):
        try:
            data = BALANCE_OF_SEL + addr.lower().replace("0x", "").rjust(64, "0")
            raw = self.rpc.eth_call(token.address, data)
            return int(raw, 16) / (10 ** token.decimals)
        except Exception:
            return None

    def _pick_focus(self, t0, t1):
        bases = {self.weth, self.usdg, ZERO}
        a0, a1 = t0.address.lower(), t1.address.lower()
        if a0 in bases and a1 not in bases:
            return t1, t0
        if a1 in bases and a0 not in bases:
            return t0, t1
        # Prefer a non-native ERC20 if possible.
        if a0 == ZERO and a1 != ZERO:
            return t1, t0
        if a1 == ZERO and a0 != ZERO:
            return t0, t1
        return t1, t0

    def _holder_stats(self, token, exclude_addrs):
        ca = token.address.lower()
        info = self._get(f"/tokens/{ca}", ttl=180)
        counters = self._get(f"/tokens/{ca}/counters", ttl=180)
        holders = self._get(f"/tokens/{ca}/holders", ttl=180)

        holder_count = None
        if isinstance(info, dict):
            holder_count = info.get("holders_count")
        if not holder_count and isinstance(counters, dict):
            holder_count = counters.get("token_holders_count")
        try:
            holder_count = int(holder_count) if holder_count is not None else None
        except Exception:
            holder_count = None

        total_raw = self._total_supply(ca)
        excluded = {x.lower() for x in exclude_addrs if x}
        excluded.update({ZERO, DEAD, self.v4_pm})

        vals = []
        burn_raw = 0
        if isinstance(holders, dict):
            for item in holders.get("items", [])[:50]:
                addr_obj = item.get("address") or item.get("address_hash") or {}
                if isinstance(addr_obj, str):
                    ah = addr_obj.lower()
                elif isinstance(addr_obj, dict):
                    ah = (addr_obj.get("hash") or addr_obj.get("address_hash") or "").lower()
                else:
                    ah = ""
                try:
                    value = int(item.get("value") or 0)
                except Exception:
                    value = 0
                if ah in {ZERO, DEAD}:
                    burn_raw += value
                if ah and ah not in excluded and value > 0:
                    vals.append(value)

        vals.sort(reverse=True)
        def pct(v):
            if not total_raw:
                return None
            return 100.0 * v / total_raw

        top1 = pct(vals[0]) if vals else None
        top10 = pct(sum(vals[:10])) if vals else None
        burn = pct(burn_raw) if burn_raw else 0.0 if total_raw else None

        return {
            "holders": holder_count,
            "top1": top1,
            "top10": top10,
            "burn": burn,
            "total_raw": total_raw,
        }

    def _contract_risk(self, token):
        ca = token.address.lower()
        c = self._get(f"/smart-contracts/{ca}", ttl=600)
        addr = self._get(f"/addresses/{ca}", ttl=600)

        if not isinstance(c, dict):
            return {
                "level": "未知",
                "verified": None,
                "proxy": None,
                "owner": None,
                "flags": ["Explorer 未返回完整合约资料"],
                "note": "无法充分审计",
            }

        verified = bool(c.get("is_verified") or c.get("is_fully_verified"))
        changed = bool(c.get("is_changed_bytecode"))
        proxy = bool(
            c.get("minimal_proxy_address_hash")
            or (isinstance(addr, dict) and addr.get("implementation_address"))
        )

        abi = c.get("abi") or []
        if isinstance(abi, str):
            try:
                abi = json.loads(abi)
            except Exception:
                abi = []

        fn_names = set()
        if isinstance(abi, list):
            for x in abi:
                if isinstance(x, dict) and x.get("type") == "function" and x.get("name"):
                    fn_names.add(str(x["name"]).lower())

        source = str(c.get("source_code") or "").lower()
        for x in c.get("additional_sources") or []:
            if isinstance(x, dict):
                source += "\n" + str(x.get("source_code") or "").lower()

        owner = self._owner(ca)
        owner_renounced = owner in {ZERO, DEAD}
        owner_active = bool(owner and not owner_renounced)

        groups = {
            "可增发": ("mint", "mintto", "_mint"),
            "黑名单": ("blacklist", "setblacklist", "bot", "setbot"),
            "暂停交易": ("pause", "unpause", "paused"),
            "税费可调": ("setfee", "settax", "taxfee", "buytax", "selltax", "marketingfee"),
            "交易开关": ("enabletrading", "settrading", "tradingenabled", "opentrading"),
            "限额限制": ("setmaxtx", "maxwallet", "maxtransaction", "setmaxwallet"),
            "可升级": ("upgradeto", "upgradeandcall", "implementation"),
        }

        flags = []
        hit = set()
        blob = source + " " + " ".join(fn_names)
        for label, keys in groups.items():
            if any(k in blob for k in keys):
                hit.add(label)
                flags.append(label)

        if changed:
            flags.insert(0, "已验证 bytecode 与当前 bytecode 不一致")
        if proxy:
            flags.append("Proxy/可升级结构")
        if owner_active:
            flags.append("Owner 仍存在")
        elif owner_renounced:
            flags.append("Owner 已放弃/销毁地址")

        # Heuristic risk level, not a guarantee.
        if not verified:
            level = "未知/偏高"
            note = "源码未完整验证，无法充分审计"
        elif changed:
            level = "高"
            note = "bytecode 变化需要重点复核"
        elif {"黑名单", "交易开关"} & hit:
            level = "高"
            note = "发现可影响买卖/地址权限的接口"
        elif {"可增发", "税费可调", "限额限制", "暂停交易", "可升级"} & hit or proxy or owner_active:
            level = "中"
            note = "存在管理权限或敏感接口"
        else:
            level = "较低"
            note = "已验证源码中未发现常见高风险管理接口"

        return {
            "level": level,
            "verified": verified,
            "proxy": proxy,
            "owner": owner,
            "owner_renounced": owner_renounced,
            "flags": flags[:6],
            "note": note,
        }

    def _lp_activity(self, subject):
        now = int(time.time())
        try:
            rows = self.db.execute(
                """SELECT action,usd FROM address_events
                   WHERE event_type='liquidity' AND subject=? AND ts>=?""",
                (subject.lower(), now - 86400),
            ).fetchall()
        except Exception:
            rows = []
        adds = removes = 0.0
        add_n = remove_n = 0
        for action, usd in rows:
            u = float(usd or 0)
            if "ADD" in (action or "").upper():
                adds += u
                add_n += 1
            elif "REMOVE" in (action or "").upper():
                removes += u
                remove_n += 1
        return adds, removes, add_n, remove_n

    def _fmt_money(self, v):
        if v is None:
            return "未知" if self.language.lower().startswith("zh") else "Unknown"
        sign = "-" if v < 0 else ""
        x = abs(float(v))
        if x >= 1_000_000:
            return f"{sign}${x/1_000_000:.2f}M"
        if x >= 1_000:
            return f"{sign}${x/1_000:.1f}K"
        return f"{sign}${x:,.0f}"

    def _fmt_pct(self, v):
        return ("未知" if self.language.lower().startswith("zh") else "Unknown") if v is None else f"{v:.1f}%"

    def _risk_text_en(self, risk):
        level_map = {"未知":"Unknown", "未知/偏高":"Unknown / Elevated", "高":"High", "中":"Medium", "较低":"Lower"}
        flag_map = {
            "Explorer 未返回完整合约资料":"Explorer did not return complete contract data",
            "可增发":"Mint capability",
            "黑名单":"Blacklist controls",
            "暂停交易":"Pause controls",
            "税费可调":"Adjustable tax/fees",
            "交易开关":"Trading switch",
            "限额限制":"Max-tx / max-wallet limits",
            "可升级":"Upgradeable functions",
            "已验证 bytecode 与当前 bytecode 不一致":"Verified bytecode differs from current bytecode",
            "Proxy/可升级结构":"Proxy / upgradeable structure",
            "Owner 仍存在":"Owner still active",
            "Owner 已放弃/销毁地址":"Owner renounced / dead address",
        }
        note_map = {
            "无法充分审计":"Insufficient data for meaningful review",
            "源码未完整验证，无法充分审计":"Source is not fully verified; review is incomplete",
            "bytecode 变化需要重点复核":"Bytecode change requires manual review",
            "发现可影响买卖/地址权限的接口":"Found interfaces that may affect trading or address permissions",
            "存在管理权限或敏感接口":"Administrative privileges or sensitive interfaces are present",
            "已验证源码中未发现常见高风险管理接口":"No common high-risk admin interfaces found in verified source",
        }
        return (
            level_map.get(risk.get("level"), risk.get("level") or "Unknown"),
            [flag_map.get(x, x) for x in (risk.get("flags") or [])],
            note_map.get(risk.get("note"), risk.get("note") or "Unknown"),
        )

    def build_liquidity_report(self, kind, pool_subject, event_usd, t0, t1,
                               block_number, v4_meta=None, current_amounts=None):
        focus, other = self._pick_focus(t0, t1)
        if focus.address.lower() == ZERO:
            return ""

        exclude = {pool_subject}
        holders = self._holder_stats(focus, exclude)
        risk = self._contract_risk(focus)
        adds, removes, add_n, remove_n = self._lp_activity(pool_subject)
        net = adds - removes
        zh = self.language.lower().startswith("zh")

        if zh:
            lines = [
                "🪙 代币情报",
                f"重点代币：{focus.symbol}",
                f"CA：{focus.address}",
                f"合约：{self.explorer}/address/{focus.address}",
            ]
            if other.address.lower() not in {ZERO, self.weth, self.usdg}:
                lines.append(f"另一侧 CA：{other.address}")
            lines += [
                "", "👥 持有人",
                f"持有人数：{holders['holders'] if holders['holders'] is not None else '未知'}",
                f"Top1：{self._fmt_pct(holders['top1'])} · Top10：{self._fmt_pct(holders['top10'])}",
            ]
            if holders["burn"] is not None and holders["burn"] > 0:
                lines.append(f"零/销毁地址占比：{self._fmt_pct(holders['burn'])}")
            lines.append("注：Top1/Top10 已排除当前池、V4 PoolManager、零/销毁地址。")
            lines += [
                "", "💧 LP 池情况",
                f"本次事件：{self._fmt_money(event_usd)}",
                f"近24h大额LP(≥$100K)：加池 {self._fmt_money(adds)} ({add_n}笔) · 撤池 {self._fmt_money(removes)} ({remove_n}笔)",
                f"近24h大额LP净变化：{self._fmt_money(net)}",
            ]
        else:
            lines = [
                "🪙 Token Intelligence",
                f"Focus token: {focus.symbol}",
                f"CA: {focus.address}",
                f"Contract: {self.explorer}/address/{focus.address}",
            ]
            if other.address.lower() not in {ZERO, self.weth, self.usdg}:
                lines.append(f"Other-side CA: {other.address}")
            lines += [
                "", "👥 Holders",
                f"Holder count: {holders['holders'] if holders['holders'] is not None else 'Unknown'}",
                f"Top1: {self._fmt_pct(holders['top1'])} · Top10: {self._fmt_pct(holders['top10'])}",
            ]
            if holders["burn"] is not None and holders["burn"] > 0:
                lines.append(f"Zero/dead share: {self._fmt_pct(holders['burn'])}")
            lines.append("Note: Top1/Top10 excludes the current pool, V4 PoolManager and zero/dead addresses.")
            lines += [
                "", "💧 LP Pool Status",
                f"Current event: {self._fmt_money(event_usd)}",
                f"24h large LP (≥$100K): add {self._fmt_money(adds)} ({add_n}) · remove {self._fmt_money(removes)} ({remove_n})",
                f"24h large-LP net change: {self._fmt_money(net)}",
            ]

        if kind.lower() == "v4" and isinstance(v4_meta, dict):
            fee = v4_meta.get("fee")
            tick_spacing = v4_meta.get("tick_spacing")
            hooks = (v4_meta.get("hooks") or ZERO).lower()
            fee_text = "未知" if zh else "Unknown"
            try:
                fee_text = f"{int(fee)/10000:.3f}%".rstrip("0").rstrip(".") + "%"
            except Exception:
                pass
            hook_text = ("无" if zh else "None") if hooks in {ZERO, "0x0", ""} else hooks
            if zh:
                lines.append(f"V4费率：{fee_text} · Tick spacing：{tick_spacing if tick_spacing is not None else '未知'}")
                lines.append(f"Hook：{hook_text}")
                lines.append("V4 为 singleton 架构，未把 PoolManager 总余额误当成该单池 TVL。")
            else:
                lines.append(f"V4 fee: {fee_text} · Tick spacing: {tick_spacing if tick_spacing is not None else 'Unknown'}")
                lines.append(f"Hook: {hook_text}")
                lines.append("V4 uses a singleton PoolManager; its total balance is not treated as this pool's TVL.")
        elif kind.lower() == "v2":
            try:
                raw = self.rpc.eth_call(pool_subject, "0x0902f1ac")
                h = raw[2:] if raw.startswith("0x") else raw
                r0, r1 = int(h[0:64], 16), int(h[64:128], 16)
                a0, a1 = r0/(10**t0.decimals), r1/(10**t1.decimals)
                lines.append((f"当前池储备：{t0.symbol} {a0:,.4g} · {t1.symbol} {a1:,.4g}" if zh else
                              f"Current reserves: {t0.symbol} {a0:,.4g} · {t1.symbol} {a1:,.4g}"))
            except Exception:
                pass
        elif kind.lower() == "v3":
            b0, b1 = self._balance_of(t0, pool_subject), self._balance_of(t1, pool_subject)
            if b0 is not None or b1 is not None:
                if b0 is not None and b1 is not None:
                    lines.append((f"当前池合约余额：{t0.symbol} {b0:,.4g} · {t1.symbol} {b1:,.4g}" if zh else
                                  f"Current pool contract balances: {t0.symbol} {b0:,.4g} · {t1.symbol} {b1:,.4g}"))
                else:
                    lines.append("当前池合约余额：部分数据查询失败" if zh else "Current pool balances: partial query failure")

        if zh:
            lines += [
                "", "🛡 合约风险扫描（启发式）",
                f"风险级别：{risk['level']}",
                f"源码验证：{'是' if risk['verified'] else '否/未知'} · Proxy：{'是' if risk['proxy'] else '否/未知'}",
            ]
            if risk.get("owner"):
                lines.append("Owner：已放弃/销毁地址" if risk.get("owner_renounced") else f"Owner：{risk['owner']}")
            if risk.get("flags"):
                lines.append("关注项：" + "、".join(risk["flags"]))
            lines += ["判断：" + risk["note"], "说明：这是链上静态/权限启发式检查，不等同于真实买卖模拟或安全审计。"]
        else:
            risk_level, risk_flags, risk_note = self._risk_text_en(risk)
            lines += [
                "", "🛡 Contract Risk Scan (heuristic)",
                f"Risk level: {risk_level}",
                f"Source verified: {'Yes' if risk['verified'] else 'No/Unknown'} · Proxy: {'Yes' if risk['proxy'] else 'No/Unknown'}",
            ]
            if risk.get("owner"):
                lines.append("Owner: renounced/dead address" if risk.get("owner_renounced") else f"Owner: {risk['owner']}")
            if risk_flags:
                lines.append("Flags: " + ", ".join(risk_flags))
            lines += ["Assessment: " + risk_note, "Note: this is a static/on-chain permission heuristic, not a buy/sell simulation or full security audit."]

        return "\n".join(lines)[:2500]

