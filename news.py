from __future__ import annotations

import re
import time

import pandas as pd
import yfinance as yf

from data import to_yahoo

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 3600.0

# Basket proxy untuk berita pasar/IHSG (indeks ^JKSE sering kosong di Yahoo).
MARKET_TICKERS = ["^JKSE", "BBCA", "BBRI", "BMRI", "TLKM", "ASII", "ADRO", "GOTO"]

_POS = {
    "naik", "menguat", "untung", "laba", "profit", "cuan", "beli", "buy", "growth", "tumbuh",
    "surge", "rally", "record", "rekor", "dividen", "upgrade", "positif", "ekspansi", "melonjak",
    "tinggi", "rekomendasi", "target", "outperform", "menang", "kontrak", "akuisisi", "rights",
}
_NEG = {
    "turun", "melemah", "rugi", "loss", "jual", "sell", "koreksi", "anjlok", "jatuh", "phk",
    "gagal", "default", "suspend", "downgrade", "negatif", "merosot", "turun", "tekanan",
    "utang", "debt", "sanksi", "denda", "bangkrut", "delisting", "underperform", "warning",
}


def _sentiment(text: str) -> tuple[int, int, float]:
    words = re.findall(r"[a-zA-Z]+", (text or "").lower())
    pos = sum(1 for w in words if w in _POS)
    neg = sum(1 for w in words if w in _NEG)
    score = 0.0
    if pos + neg > 0:
        score = (pos - neg) / (pos + neg)
    return pos, neg, round(score, 2)


def _parse_item(n: dict) -> dict | None:
    if not isinstance(n, dict):
        return None
    content = n.get("content")
    if isinstance(content, dict):
        title = content.get("title")
        publisher = (content.get("provider") or {}).get("displayName")
        link = ((content.get("canonicalUrl") or {}).get("url"))
        ts = content.get("pubDate")
    else:
        title = n.get("title")
        publisher = n.get("publisher")
        link = n.get("link")
        ts = n.get("providerPublishTime")
    if not title:
        return None
    pos, neg, score = _sentiment(title)
    return {
        "title": title,
        "publisher": publisher,
        "url": link,
        "time": ts,
        "sentiment": score,
        "pos": pos,
        "neg": neg,
    }


def _summarize(items: list[dict]) -> tuple[float, str]:
    scores = [i["sentiment"] for i in items if i["sentiment"] != 0]
    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    label = "Positif" if avg > 0.15 else ("Negatif" if avg < -0.15 else "Netral")
    return avg, label


def _raw_items(yt: str, limit: int) -> list[dict]:
    try:
        raw = yf.Ticker(yt).news or []
    except Exception:
        raw = []
    out = []
    for n in raw[:limit]:
        item = _parse_item(n)
        if item:
            out.append(item)
    return out


def get_news(ticker: str, limit: int = 15) -> dict:
    yt = to_yahoo(ticker)
    now = time.time()
    cached = _cache.get("t:" + yt)
    if cached and now - cached[0] < _TTL:
        return cached[1]

    items = _raw_items(yt, limit)
    avg, label = _summarize(items)
    result = {"ticker": ticker.upper(), "count": len(items), "avg_sentiment": avg, "label": label, "items": items}
    _cache["t:" + yt] = (now, result)
    return result


def _time_key(item: dict) -> float:
    ts = item.get("time")
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return pd.Timestamp(ts).timestamp()
        except Exception:
            return 0.0
    return 0.0


def get_market_news(limit: int = 24, tickers: list[str] | None = None) -> dict:
    """Berita pasar/IHSG agregat dari indeks + emiten besar (di-dedupe)."""
    now = time.time()
    universe = [t.upper() for t in (tickers or MARKET_TICKERS)]
    ckey = "m:" + ",".join(universe)
    cached = _cache.get(ckey)
    if cached and now - cached[0] < _TTL:
        return cached[1]

    seen: set[str] = set()
    items: list[dict] = []
    for t in universe:
        yt = to_yahoo(t) if t != "^JKSE" else "^JKSE"
        for item in _raw_items(yt, limit):
            key = re.sub(r"\W+", "", (item.get("title") or "").lower())[:80]
            if not key or key in seen:
                continue
            seen.add(key)
            item["source_ticker"] = t
            items.append(item)

    items.sort(key=_time_key, reverse=True)
    items = items[:limit]
    avg, label = _summarize(items)
    result = {
        "ticker": "PASAR",
        "count": len(items),
        "avg_sentiment": avg,
        "label": label,
        "items": items,
        "universe": universe,
    }
    _cache[ckey] = (now, result)
    return result
