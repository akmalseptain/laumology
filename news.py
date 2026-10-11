from __future__ import annotations

import re
import threading
import time

import pandas as pd
import yfinance as yf

from data import to_yahoo

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_TTL = 3600.0

# Batas keras jumlah entri cache berita. Key dibentuk dari ticker yang bisa
# datang dari klien (`GET /api/news?ticker=...`, endpoint tanpa auth), sehingga
# tanpa batas ini cache tumbuh selamanya dan bisa menghabiskan memori pada
# proses berjalan lama (memory-DoS). Eviksi hanya memicu ambil ulang berita,
# bukan hasil yang salah. (Selaras dengan `data._QUOTE_CACHE_MAX`.)
_CACHE_MAX = 512

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
    with _cache_lock:
        cached = _cache.get("t:" + yt)
        if cached and now - cached[0] < _TTL:
            return cached[1]

    items = _raw_items(yt, limit)
    avg, label = _summarize(items)
    result = {"ticker": ticker.upper(), "count": len(items), "avg_sentiment": avg, "label": label, "items": items}
    with _cache_lock:
        _cache["t:" + yt] = (now, result)
        _prune_cache_locked()
    return result


def _prune_cache_locked() -> None:
    """Buang entri berita kedaluwarsa lalu tertua bila melebihi batas.

    Dipanggil saat ``_cache_lock`` sedang dipegang. Hanya membuang entri dari
    cache; permintaan berikutnya akan mengambil ulang berita, bukan hasil salah.
    """
    assert _cache_lock.locked(), "harus dipanggil dengan _cache_lock dipegang"
    fresh = time.time()
    expired = [k for k, (ts, _v) in _cache.items() if fresh - ts >= _TTL]
    for key in expired:
        _cache.pop(key, None)
    excess = len(_cache) - _CACHE_MAX
    if excess <= 0:
        return
    oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[:excess]
    for key, _entry in oldest:
        _cache.pop(key, None)


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
    with _cache_lock:
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
    with _cache_lock:
        _cache[ckey] = (now, result)
        _prune_cache_locked()
    return result
