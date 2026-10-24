"""Pos publik di X yang sudah terindeks, tanpa kunci dan tanpa token berbayar.

Sumbernya RSS pencarian yang memuat `site:x.com`. Bukan API xAI.
Yang lolos hanya judul yang membahas pasar (IHSG, MSCI, rupiah, asing).
Akun resmi tidak diistimewakan: penggiat saham ikut, selama judulnya soal pasar.
Pos ini konteks, bukan harga dan bukan broker summary.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

_log = logging.getLogger("laumology.xsource")

# Beberapa kueri supaya pembanding tidak hanya judul MSCI yang sama.
_QUERIES = (
    "IHSG (MSCI OR asing OR rupiah OR saham) site:x.com",
    "(BBCA OR BMRI OR BBRI OR TLKM OR ASII) (beli OR jual OR IHSG) site:x.com",
    "(LQ45 OR IDX30 OR saham) (IHSG OR bursa OR analisis) site:x.com",
)
# Cukup lebar untuk mayoritas, tetap berbatas supaya kartu tidak memuat ratusan judul.
_POST_CAP = 60
_NEEDLES = (
    "ihsg", "msci", "ftse", "rupiah", "asing", "bei", "bursa",
    "suku bunga", "trading halt",
)
_JUAL = (
    "jual", "anjlok", "cutloss", "cut loss", "hindari", "melemah", "net sell",
    "trading halt", "turun", "jeblok", "ambles", "longsor", "tertekan",
    "bearish", "koreksi",
)
_BELI = (
    "beli", "serok", "akumulasi", "menguat", "net buy", "naik", "bullish",
    "cuan", "koleksi", "rebound", "breakout",
)
_TAHAN = ("tahan", "hold", "wait", "tunggu", "waspada")
_PERISTIWA = (
    "rups", "tender offer", "dividen", "right issue", "rights issue",
    "akuisisi", "stock split", "private placement", "waran", "buyback",
)
_OUR = {"BUY": "beli", "SELL": "jual", "HOLD": "tahan", "WAIT": "tahan"}
_TTL = 1800.0
_TICKER_RE = re.compile(r"^[A-Z]{2,5}$")
_OTHER_CODE = re.compile(r"\b[A-Z]{4}\b")
_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "items": None, "ok": None}
_ticker_cache: dict[str, tuple[float, list, bool]] = {}


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
    if any(word in low for word in _PERISTIWA):
        return "peristiwa"
    return "netral"


def compare_signal(our_signal: str | None, posts: list[dict], subject: str = "") -> dict:
    """Bandingkan sinyal aplikasi dengan arah mayoritas pos X. Tidak mengubah skor."""
    counts = {"beli": 0, "jual": 0, "tahan": 0, "netral": 0, "peristiwa": 0}
    samples: list[str] = []
    for post in posts or []:
        if not isinstance(post, dict):
            continue
        title = str(post.get("title") or "")
        side = post.get("stance") if post.get("stance") in counts else stance_of(title)
        counts[side] += 1
        if len(samples) < 8:
            samples.append(f"[{side}] {title[:150]}")
    voiced = {k: counts[k] for k in ("beli", "jual", "tahan")}
    nama = subject or "emiten ini"
    if not posts:
        theirs, note = "belum ada", f"Belum ada pos X yang menyebut {nama}."
    elif max(voiced.values()) == 0 and counts["peristiwa"] > 0:
        theirs = "peristiwa"
        note = (f"Pos X tentang {nama} membahas aksi korporasi "
                f"({counts['peristiwa']} dari {len(posts)}), bukan ajakan beli atau jual.")
    elif max(voiced.values()) == 0:
        theirs, note = "netral", (
            f"{len(posts)} pos menyebut {nama}. Tidak ada kata beli atau jual. "
            "Judulnya tercantum di bawah, bukan dibuang."
        )
    else:
        theirs = max(voiced, key=voiced.get)
        if list(voiced.values()).count(voiced[theirs]) > 1:
            theirs, note = "campur", f"Suara X tentang {nama} terbelah, tidak ada arah yang menang."
        else:
            note = (f"Mayoritas pos X tentang {nama} berarah {theirs} "
                    f"({voiced[theirs]} dari {len(posts)}).")
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
        "ticker": subject or None,
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
        if len(out) >= _POST_CAP:
            break
    return out


def keep_ticker_posts(rows: list[dict], ticker: str) -> list[dict]:
    """Hanya judul yang menyebut kode ini. BBCA tidak tercampur dengan TLKM."""
    code = (ticker or "").upper().strip()
    if not _TICKER_RE.fullmatch(code):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
        upper = title.upper()
        if code not in upper or len(title) < 12:
            continue
        others = {token for token in _OTHER_CODE.findall(title) if token != code}
        # Judul daftar banyak kode adalah berita pasar, bukan suara emiten ini.
        if len(others) >= 2:
            continue
        key = re.sub(r"\W+", "", title.lower())[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            "title": f"Pos X {code}: " + title[:180],
            "summary": None,
            "url": str(row.get("link") or row.get("url") or ""),
            "source": "x",
            "stance": stance_of(title),
        })
        if len(out) >= _POST_CAP:
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


def _feed_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=id&gl=ID&ceid=ID:id"
    )


def _fetch_query(query: str) -> tuple[list[dict], bool]:
    try:
        req = urllib.request.Request(
            _feed_url(query),
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            return _titles_from_rss(resp.read(500_000)), True
    except Exception as exc:
        _log.warning(
            "feed X %r gagal diambil (%s) - sumber dilewati",
            query, type(exc).__name__,
        )
        return [], False


def headlines() -> tuple[list[dict], bool]:
    """``(pos, sumber_hidup)``. Tidak memakai kunci API."""
    now = time.time()
    with _lock:
        if _cache["items"] is not None and now - float(_cache["ts"]) < _TTL:
            return list(_cache["items"]), bool(_cache["ok"])
    rows: list[dict] = []
    ok = False
    try:
        with ThreadPoolExecutor(max_workers=len(_QUERIES)) as pool:
            for found, source_ok in pool.map(_fetch_query, _QUERIES):
                if source_ok:
                    ok = True
                rows.extend(found)
        items = keep_market_posts(rows)
    except Exception as exc:
        _log.warning(
            "pos X pasar gagal total (%s: %s) - ok=False",
            type(exc).__name__, exc,
        )
        items, ok = [], False
    with _lock:
        _cache["ts"] = time.time()
        _cache["items"] = items
        _cache["ok"] = ok
    return list(items), ok


def headlines_for(ticker: str) -> tuple[list[dict], bool]:
    """Pos X yang menyebut satu kode. Cache terpisah per emiten."""
    code = (ticker or "").upper().strip()
    if not _TICKER_RE.fullmatch(code):
        return [], False
    now = time.time()
    with _lock:
        cached = _ticker_cache.get(code)
        if cached and now - cached[0] < _TTL:
            return list(cached[1]), bool(cached[2])
    queries = (
        f"{code} saham site:x.com",
        f"{code} (beli OR jual OR tahan OR IHSG OR saham) site:x.com",
        f"{code} (analisis OR target OR support OR resistance) site:x.com",
    )
    rows: list[dict] = []
    ok = False
    try:
        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            for found, source_ok in pool.map(_fetch_query, queries):
                if source_ok:
                    ok = True
                rows.extend(found)
        items = keep_ticker_posts(rows, code)
    except Exception as exc:
        _log.warning(
            "pos X emiten %s gagal total (%s: %s) - ok=False",
            code, type(exc).__name__, exc,
        )
        items, ok = [], False
    with _lock:
        _ticker_cache[code] = (time.time(), items, ok)
        if len(_ticker_cache) > 80:
            oldest = sorted(_ticker_cache.items(), key=lambda kv: kv[1][0])[:20]
            for key, _entry in oldest:
                _ticker_cache.pop(key, None)
    return list(items), ok
