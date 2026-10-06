from __future__ import annotations

import re
import time

import yfinance as yf

from data import to_yahoo

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 900.0

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


def get_news(ticker: str, limit: int = 15) -> dict:
    yt = to_yahoo(ticker)
    now = time.time()
    cached = _cache.get(yt)
    if cached and now - cached[0] < _TTL:
        return cached[1]

    items: list[dict] = []
    try:
        raw = yf.Ticker(yt).news or []
    except Exception:
        raw = []

    for n in raw[:limit]:
        content = n.get("content") if isinstance(n, dict) else None
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
        pos, neg, score = _sentiment(title or "")
        items.append({
            "title": title,
            "publisher": publisher,
            "url": link,
            "time": ts,
            "sentiment": score,
            "pos": pos,
            "neg": neg,
        })

    scores = [i["sentiment"] for i in items if i["sentiment"] != 0]
    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    label = "Positif" if avg > 0.15 else ("Negatif" if avg < -0.15 else "Netral")

    result = {"ticker": ticker.upper(), "count": len(items), "avg_sentiment": avg, "label": label, "items": items}
    _cache[yt] = (now, result)
    return result
