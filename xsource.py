"""Pos publik di X yang sudah terindeks, tanpa kunci dan tanpa token berbayar.

Sumbernya RSS pencarian yang memuat `site:x.com`. Bukan API xAI.
Yang lolos hanya judul yang membahas pasar (IHSG, MSCI, rupiah, asing).
Akun resmi tidak diistimewakan: penggiat saham ikut, selama judulnya soal pasar.
Pos ini konteks, bukan harga dan bukan broker summary.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

_FEED = (
    "https://news.google.com/rss/search?q="
    "IHSG+(MSCI+OR+asing+OR+rupiah+OR+%22suku+bunga%22)+site:x.com"
    "&hl=id&gl=ID&ceid=ID:id"
)
_NEEDLES = (
    "ihsg", "msci", "ftse", "rupiah", "asing", "bei", "bursa",
    "suku bunga", "trading halt",
)
_TTL = 1800.0
_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "items": None, "ok": None}


def keep_market_posts(rows: list[dict]) -> list[dict]:
    """Saring judul. Olahraga dan unggahan tanpa kata pasar dibuang."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
        low = title.lower()
        if len(title) < 20 or not any(needle in low for needle in _NEEDLES):
            continue
        key = re.sub(r"\W+", "", low)[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            "title": "Pos X: " + title[:180],
            "summary": None,
            "url": str(row.get("link") or row.get("url") or ""),
            "source": "x",
        })
        if len(out) >= 8:
            break
    return out


def _titles_from_rss(raw: bytes) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    rows = []
    for item in root.findall("./channel/item"):
        rows.append({
            "title": item.findtext("title") or "",
            "link": item.findtext("link") or "",
        })
    return rows


def headlines() -> tuple[list[dict], bool]:
    """``(pos, sumber_hidup)``. Tidak memakai kunci API."""
    now = time.time()
    with _lock:
        if _cache["items"] is not None and now - float(_cache["ts"]) < _TTL:
            return list(_cache["items"]), bool(_cache["ok"])
    try:
        req = urllib.request.Request(
            _FEED,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read(500_000)
        items = keep_market_posts(_titles_from_rss(raw))
        ok = True
    except Exception:
        items, ok = [], False
    with _lock:
        _cache["ts"] = time.time()
        _cache["items"] = items
        _cache["ok"] = ok
    return list(items), ok
