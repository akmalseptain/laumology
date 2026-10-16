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
_JUAL = ("jual", "anjlok", "cutloss", "cut loss", "hindari", "melemah", "net sell", "trading halt", "turun")
_BELI = ("beli", "serok", "akumulasi", "menguat", "net buy")
_TAHAN = ("tahan", "hold", "wait", "tunggu", "waspada")
_OUR = {"BUY": "beli", "SELL": "jual", "HOLD": "tahan", "WAIT": "tahan"}
_TTL = 1800.0
_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "items": None, "ok": None}


def stance_of(title: str) -> str:
    """Arah yang terbaca dari judul. Kalimat yang berisi beli dan jual jadi netral."""
    low = (title or "").lower()
    jual = any(word in low for word in _JUAL)
    beli = any(word in low for word in _BELI)
    tahan = any(word in low for word in _TAHAN)
    if jual and beli:
        return "netral"
    if jual:
        return "jual"
    if beli:
        return "beli"
    if tahan:
        return "tahan"
    return "netral"


def compare_signal(our_signal: str | None, posts: list[dict]) -> dict:
    """Bandingkan sinyal aplikasi dengan arah mayoritas pos X. Tidak mengubah skor."""
    counts = {"beli": 0, "jual": 0, "tahan": 0, "netral": 0}
    samples: list[str] = []
    for post in posts or []:
        if not isinstance(post, dict):
            continue
        title = str(post.get("title") or "")
        side = post.get("stance") if post.get("stance") in counts else stance_of(title)
        counts[side] += 1
        if side != "netral" and len(samples) < 3:
            samples.append(title[:160])
    voiced = {k: counts[k] for k in ("beli", "jual", "tahan")}
    if not posts:
        theirs, note = "belum ada", "Belum ada pos X soal pasar."
    elif max(voiced.values()) == 0:
        theirs, note = "netral", "Pos X ada, tetapi arah beli atau jualnya tidak terbaca."
    else:
        theirs = max(voiced, key=voiced.get)
        if list(voiced.values()).count(voiced[theirs]) > 1:
            theirs, note = "campur", "Suara X terbelah, tidak ada arah yang menang."
        else:
            note = f"Mayoritas pos X berarah {theirs} ({voiced[theirs]} dari {len(posts)})."
    ours = _OUR.get((our_signal or "").upper(), "tahan")
    if theirs in ("belum ada", "netral", "campur"):
        alignment = "belum cukup"
    elif ours == theirs:
        alignment = "searah"
    elif {ours, theirs} == {"beli", "jual"}:
        alignment = "berlawanan"
    else:
        alignment = "berbeda"
    return {
        "ours": ours,
        "our_signal": (our_signal or "").upper() or None,
        "theirs": theirs,
        "counts": counts,
        "alignment": alignment,
        "note": note,
        "samples": samples,
    }


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
            "stance": stance_of(title),
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
