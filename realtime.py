from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_PATH = Path("realtime.json")
EXAMPLE_PATH = Path("realtime.example.json")

_DEFAULT = {
    "provider": "auto",
    "api_key": "",
    "url": "",
    "headers": {},
    "mapping": {
        "last": "close",
        "prev_close": "previous_close",
        "open": "open",
        "high": "high",
        "low": "low",
        "volume": "volume",
    },
}


def load_config() -> dict:
    cfg = dict(_DEFAULT)
    cfg["headers"] = {}
    cfg["mapping"] = dict(_DEFAULT["mapping"])
    env_provider = os.environ.get("IDX_RT_PROVIDER")
    env_key = os.environ.get("IDX_RT_KEY")
    env_url = os.environ.get("IDX_RT_URL")
    if env_provider:
        cfg["provider"] = env_provider
    if env_key:
        cfg["api_key"] = env_key
    if env_url:
        cfg["url"] = env_url
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    cfg[k] = v
        except Exception:
            pass
    return cfg


def active_provider() -> str:
    return str(load_config().get("provider", "auto")).lower()


def _http_json(url: str, headers: dict | None = None, timeout: float = 8.0):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "idx-terminal/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _http_post_json(url: str, payload: dict, headers: dict | None = None, timeout: float = 8.0):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers=headers or {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _dig(obj, path: str):
    cur = obj
    for part in str(path).split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _norm(last, prev, o, hi, lo, vol, symbol, source, now=None) -> dict | None:
    last = _num(last)
    if last is None:
        return None
    return {
        "symbol": symbol,
        "last": last,
        "prev_close": _num(prev),
        "open": _num(o),
        "day_high": _num(hi),
        "day_low": _num(lo),
        "volume": _num(vol),
        "time": now or time.time(),
        "source": source,
    }


def _generic(cfg: dict, symbol: str) -> dict | None:
    url = str(cfg.get("url") or "")
    if not url:
        raise RuntimeError("realtime.url belum diisi")
    ticker = symbol.split(".")[0]
    url = url.format(symbol=ticker, symbol_full=symbol, key=cfg.get("api_key", ""))
    data = _http_json(url, cfg.get("headers"))
    m = cfg.get("mapping", {})
    return _norm(
        _dig(data, m.get("last", "close")),
        _dig(data, m.get("prev_close", "previous_close")),
        _dig(data, m.get("open", "open")),
        _dig(data, m.get("high", "high")),
        _dig(data, m.get("low", "low")),
        _dig(data, m.get("volume", "volume")),
        symbol, "custom",
    )


def _twelvedata(cfg: dict, symbol: str) -> dict | None:
    key = cfg.get("api_key", "")
    if not key:
        raise RuntimeError("api_key Twelve Data kosong")
    ticker = symbol.split(".")[0]
    host = cfg.get("url") or "https://api.twelvedata.com/quote"
    url = f"{host}?symbol={urllib.parse.quote(ticker)}&exchange=IDX&apikey={urllib.parse.quote(key)}"
    d = _http_json(url, cfg.get("headers"))
    if isinstance(d, dict) and d.get("status") == "error":
        raise RuntimeError(d.get("message", "Twelve Data error"))
    return _norm(
        d.get("close") or d.get("price"), d.get("previous_close"),
        d.get("open"), d.get("high"), d.get("low"), d.get("volume"),
        symbol, "twelvedata",
    )


def _eodhd(cfg: dict, symbol: str) -> dict | None:
    key = cfg.get("api_key", "")
    if not key:
        raise RuntimeError("api_token EODHD kosong")
    host = cfg.get("url") or "https://eodhd.com/api/real-time"
    url = f"{host}/{urllib.parse.quote(symbol)}?api_token={urllib.parse.quote(key)}&fmt=json"
    d = _http_json(url, cfg.get("headers"))
    return _norm(
        d.get("close"), d.get("previousClose"),
        d.get("open"), d.get("high"), d.get("low"), d.get("volume"),
        symbol, "eodhd",
    )


def _tradingview(cfg: dict, symbol: str) -> dict | None:
    ticker = symbol.split(".")[0]
    url = cfg.get("url") or "https://scanner.tradingview.com/indonesia/scan"
    columns = ["name", "close", "change", "change_abs", "open", "high", "low", "volume", "prev_close_price"]
    payload = {
        "symbols": {"tickers": [f"IDX:{ticker}"], "query": {"types": []}},
        "columns": columns,
    }
    headers = cfg.get("headers") or {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    data = _http_post_json(url, payload, headers)
    rows = data.get("data") or []
    if not rows or not rows[0].get("d"):
        return None
    d = rows[0]["d"]
    close, change, _chg_abs, o, hi, lo, vol, prev = d[1], d[2], d[3], d[4], d[5], d[6], d[7], d[8]
    prev = _num(prev)
    if prev is None and close is not None and change is not None:
        try:
            prev = float(close) / (1.0 + float(change) / 100.0)
        except (TypeError, ValueError, ZeroDivisionError):
            prev = None
    return _norm(close, prev, o, hi, lo, vol, symbol, "tradingview")


PROVIDERS = {
    "tradingview": _tradingview,
    "tv": _tradingview,
    "generic": _generic,
    "custom": _generic,
    "http": _generic,
    "twelvedata": _twelvedata,
    "eodhd": _eodhd,
}


def fetch_quote(symbol: str) -> dict | None:
    cfg = load_config()
    provider = str(cfg.get("provider", "auto")).lower()
    if provider in ("yfinance", "yahoo"):
        return None
    if provider in ("auto", ""):
        try:
            q = _tradingview(cfg, symbol)
            if q and q.get("last") is not None:
                return q
        except Exception:
            pass
        return None
    fn = PROVIDERS.get(provider)
    if fn is None:
        raise RuntimeError(f"provider '{provider}' tidak dikenal")
    return fn(cfg, symbol)
