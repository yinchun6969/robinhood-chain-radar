#!/usr/bin/env python3
"""Small read-only JSON-RPC failover pool for Robinhood Chain Radar."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

import requests


class FailoverRPC:
    def __init__(self, urls, failback_sec=300, session_factory=None, logger=None):
        if isinstance(urls, str):
            urls = [urls]
        clean = []
        for raw in urls or []:
            u = str(raw or "").strip()
            if u and u not in clean:
                clean.append(u)
        if not clean:
            raise ValueError("at least one RPC URL is required")
        self.urls = clean
        self.failback_sec = max(0, int(failback_sec or 0))
        self.session_factory = session_factory or requests.Session
        self.log = logger
        self._local = threading.local()
        self._lock = threading.RLock()
        self._id = 0
        self._active = 0
        self._last_primary_probe = 0.0
        self._stats = [
            {
                "successes": 0,
                "failures": 0,
                "consecutive_failures": 0,
                "latency_ms": None,
                "last_ok_ts": 0,
                "last_error": "",
            }
            for _ in clean
        ]

    @staticmethod
    def safe_label(url: str) -> str:
        """Return a URL label that does not leak API keys in path/query/userinfo."""
        try:
            p = urlsplit(url)
            host = p.hostname or "rpc"
            if p.port:
                host += f":{p.port}"
            return f"{p.scheme or 'https'}://{host}"
        except Exception:
            return "rpc://redacted"

    @property
    def active_url(self):
        with self._lock:
            return self.urls[self._active]

    @property
    def active_label(self):
        return self.safe_label(self.active_url)

    @property
    def active_index(self):
        with self._lock:
            return self._active

    def _sessions(self):
        sessions = getattr(self._local, "sessions", None)
        if sessions is None:
            sessions = {}
            self._local.sessions = sessions
        return sessions

    def _session(self, idx):
        sessions = self._sessions()
        if idx not in sessions:
            sessions[idx] = self.session_factory()
        return sessions[idx]

    def _next_id(self):
        with self._lock:
            self._id += 1
            return self._id

    def _ordered_indexes(self):
        now = time.monotonic()
        with self._lock:
            active = self._active
            order = [active] + [i for i in range(len(self.urls)) if i != active]
            if active != 0 and self.failback_sec and now - self._last_primary_probe >= self.failback_sec:
                order = [0, active] + [i for i in range(len(self.urls)) if i not in (0, active)]
                self._last_primary_probe = now
            return order

    def _mark_success(self, idx, latency_ms):
        with self._lock:
            previous = self._active
            self._active = idx
            s = self._stats[idx]
            s["successes"] += 1
            s["consecutive_failures"] = 0
            s["last_ok_ts"] = int(time.time())
            s["last_error"] = ""
            old = s.get("latency_ms")
            s["latency_ms"] = round(float(latency_ms) if old is None else old * 0.7 + float(latency_ms) * 0.3, 1)
        if previous != idx and self.log:
            self.log.warning("RPC failover: %s -> %s", self.safe_label(self.urls[previous]), self.safe_label(self.urls[idx]))

    def _mark_failure(self, idx, exc):
        with self._lock:
            s = self._stats[idx]
            s["failures"] += 1
            s["consecutive_failures"] += 1
            s["last_error"] = str(exc)[:180]

    def _post(self, idx, payload, timeout):
        started = time.monotonic()
        r = self._session(idx).post(self.urls[idx], json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        latency = (time.monotonic() - started) * 1000.0
        return data, latency

    def call(self, method, params, timeout=20):
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params}
        errors = []
        for idx in self._ordered_indexes():
            try:
                data, latency = self._post(idx, payload, timeout)
                if not isinstance(data, dict):
                    raise RuntimeError("invalid JSON-RPC response")
                if "error" in data:
                    raise RuntimeError(f"RPC {method}: {data['error']}")
                self._mark_success(idx, latency)
                return data.get("result")
            except Exception as exc:
                self._mark_failure(idx, exc)
                errors.append(f"{self.safe_label(self.urls[idx])}: {exc}")
        raise RuntimeError(f"all RPC endpoints failed for {method}: " + " | ".join(errors))

    def batch(self, calls, timeout=30):
        payload = []
        ids = []
        for method, params in calls:
            rid = self._next_id()
            ids.append(rid)
            payload.append({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        errors = []
        for idx in self._ordered_indexes():
            try:
                arr, latency = self._post(idx, payload, timeout)
                if not isinstance(arr, list):
                    raise RuntimeError("provider does not support JSON-RPC batch")
                byid = {x.get("id"): x for x in arr if isinstance(x, dict)}
                out = []
                for rid in ids:
                    item = byid.get(rid)
                    if not item or "error" in item:
                        raise RuntimeError(f"batch item failed: {item}")
                    out.append(item.get("result"))
                self._mark_success(idx, latency)
                return out
            except Exception as exc:
                self._mark_failure(idx, exc)
                errors.append(f"{self.safe_label(self.urls[idx])}: {exc}")
        if self.log:
            self.log.warning("RPC batch unavailable on all endpoints; sequential fallback: %s", " | ".join(errors))
        return [self.call(method, params, timeout=timeout) for method, params in calls]

    def endpoint_health(self):
        with self._lock:
            result = []
            for i, (url, stats) in enumerate(zip(self.urls, self._stats)):
                x = dict(stats)
                x.update({"index": i, "label": self.safe_label(url), "active": i == self._active})
                result.append(x)
            return result

    def probe_all(self, timeout=6):
        """Probe each endpoint independently without exposing endpoint secrets."""
        out = []
        for idx, url in enumerate(self.urls):
            started = time.monotonic()
            try:
                rid1, rid2 = self._next_id(), self._next_id()
                payload = [
                    {"jsonrpc": "2.0", "id": rid1, "method": "eth_chainId", "params": []},
                    {"jsonrpc": "2.0", "id": rid2, "method": "eth_blockNumber", "params": []},
                ]
                data, _ = self._post(idx, payload, timeout)
                if not isinstance(data, list):
                    raise RuntimeError("batch probe unsupported")
                byid = {x.get("id"): x for x in data if isinstance(x, dict)}
                c, b = byid.get(rid1), byid.get(rid2)
                if not c or not b or "error" in c or "error" in b:
                    raise RuntimeError("probe RPC error")
                out.append({
                    "label": self.safe_label(url), "ok": True,
                    "chain_id": int(c.get("result"), 16),
                    "block": int(b.get("result"), 16),
                    "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
                    "active": idx == self.active_index,
                })
            except Exception as exc:
                # Some endpoints reject batch probes. Retry sequentially on the same endpoint.
                try:
                    r1, _ = self._post(idx, {"jsonrpc":"2.0","id":self._next_id(),"method":"eth_chainId","params":[]}, timeout)
                    r2, _ = self._post(idx, {"jsonrpc":"2.0","id":self._next_id(),"method":"eth_blockNumber","params":[]}, timeout)
                    if "error" in r1 or "error" in r2:
                        raise RuntimeError("probe RPC error")
                    out.append({
                        "label": self.safe_label(url), "ok": True,
                        "chain_id": int(r1.get("result"), 16), "block": int(r2.get("result"), 16),
                        "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
                        "active": idx == self.active_index,
                    })
                except Exception as exc2:
                    out.append({"label": self.safe_label(url), "ok": False, "error": str(exc2)[:180], "active": idx == self.active_index})
        return out
