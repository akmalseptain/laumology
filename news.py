from __future__ import annotations

import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import pandas as pd
import yfinance as yf

from data import to_yahoo

_cache: dict[str, tuple[float, dict, float]] = {}
_cache_lock = threading.Lock()
_TTL = 3600.0

# Hasil kosong/gagal disimpan singkat agar kegagalan sumber tidak "membeku"
# selama satu jam di cache (permintaan berikutnya mencoba lagi lebih cepat).
# Selaras dengan `fundamentals._NEGATIVE_TTL`.
_NEGATIVE_TTL = 300.0

# Whitelist ticker dari klien sebelum divalidasi ke key cache DAN disisipkan ke
# URL sumber berita (endpoint `/api/news` tanpa auth). Mencegah query/path
# injection lewat ticker (`A&foo=bar`, `#`, spasi, path). Selaras semangat
# `fundamentals._MAX_KEY_LEN`.
_TICKER_RE = re.compile(r"^[A-Z0-9.^\-]{1,16}$")

# Sumber berita. `yf.Ticker(...).news` dicoba lebih dulu, lalu fallback ke
# Google News RSS (`news.google.com/rss/search`) yang sudah diverifikasi hidup
# (HTTP 200). Sumber RSS Yahoo lama tidak lagi dipakai; `yf.Ticker(...).news`
# kerap mengembalikan daftar kosong sehingga fallback memang dibutuhkan.
_RSS_URL = "https://news.google.com/rss/search"
_RSS_TIMEOUT = 8.0
_RSS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Plafon byte respons RSS: menahan respons raksasa/ekspansi entitas (DoS) pada
# endpoint tanpa auth. Input di atas plafon dipotong sebelum di-parse.
_RSS_MAX_BYTES = 1_000_000

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


class _Items(list):
    """Daftar item berita + metadata sumber tanpa mengubah signature ``_raw_items``.

    ``_raw_items`` tetap mengembalikan ``list`` (agar ``patch("news._raw_items")``
    di tes tetap kompatibel), tetapi membawa ``source`` sumber yang berhasil,
    ``source_ok`` (ada sumber yang benar-benar menyajikan item, atau RSS
    berhasil diambil tanpa exception), dan ``errors`` kegagalan server-side.
    Daftar polos dari mock tak punya atribut ini, sehingga ``getattr(...,
    default)`` tetap aman: ``source_ok`` absen berarti ``False`` (safe-default
    → ``degraded=True`` bila item kosong).
    """

    def __init__(self, *args, source: str | None = None, source_ok: bool = False,
                 errors: list[str] | None = None):
        super().__init__(*args)
        self.source = source
        self.source_ok = source_ok
        self.errors = errors or []


# Penanda deklarasi DTD/entitas yang harus ditolak.
_DTD_MARKERS = (b"<!DOCTYPE", b"<!ENTITY")
# BOM yang ditangani (UTF-32 dulu agar BOM LE-nya tak salah dibaca sebagai UTF-16).
_BOMS = (b"\xef\xbb\xbf", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff", b"\xff\xfe", b"\xfe\xff")


def _reject_dtd(xml_bytes: bytes) -> None:
    """Tolak DTD/entitas secara encoding-agnostic pada SELURUH body.

    Penanda diperiksa pada byte mentah dan pada varian bebas-byte-nol (UTF-16/
    UTF-32 menyisipkan ``\\x00`` antar karakter ASCII), sehingga deklarasi tak
    bisa disembunyikan lewat encoding maupun digeser melewati jendela 4 KB.
    """
    body = xml_bytes
    for bom in _BOMS:
        if body.startswith(bom):
            body = body[len(bom):]
            break
    for sample in (xml_bytes, body.replace(b"\x00", b"")):
        up = sample.upper()
        if any(marker in up for marker in _DTD_MARKERS):
            raise ValueError("XML dengan DTD/entitas tidak didukung")


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    """Urai RSS 2.0 (Google News) ke skema item yang sama dengan ``_parse_item``.

    Batas keamanan: DTD/entitas eksternal ditolak (tanpa ``defusedxml``) untuk
    mencegah XXE/billion-laughs; ukuran sudah dipotong pemanggil.
    """
    if not xml_bytes:
        return []
    _reject_dtd(xml_bytes)
    root = ET.fromstring(xml_bytes)
    out: list[dict] = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        link = (node.findtext("link") or "").strip() or None
        publisher = (node.findtext("source") or "").strip() or None
        ts = (node.findtext("pubDate") or "").strip() or None
        pos, neg, score = _sentiment(title)
        out.append({
            "title": title,
            "publisher": publisher,
            "url": link,
            "time": ts,
            "sentiment": score,
            "pos": pos,
            "neg": neg,
        })
    return out


def _rss_query(yt: str) -> str:
    """Ubah simbol Yahoo (``BBCA.JK``/``^JKSE``) jadi kata kunci ramah manusia."""
    base = yt[:-3] if yt.endswith(".JK") else yt
    if base == "^JKSE":
        return "IHSG"
    return base.lstrip("^")


def _rss_items(yt: str) -> list[dict]:
    """Ambil berita dari Google News RSS untuk simbol Yahoo ``yt``."""
    query = urllib.parse.quote(_rss_query(yt) + " saham")
    url = f"{_RSS_URL}?q={query}&hl=id&gl=ID&ceid=ID:id"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _RSS_UA,
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    # Verifikasi TLS biarkan default urllib (True) — jangan pernah dimatikan.
    with urllib.request.urlopen(req, timeout=_RSS_TIMEOUT) as resp:
        raw = resp.read(_RSS_MAX_BYTES + 1)
    if len(raw) > _RSS_MAX_BYTES:
        raw = raw[:_RSS_MAX_BYTES]
    return _parse_rss(raw)


def _raw_items(yt: str, limit: int) -> list[dict]:
    """Item berita terbaik: coba Yahoo dulu, lalu fallback Google News RSS.

    Kegagalan tidak lagi ditelan diam-diam; dikumpulkan di ``_Items.errors``
    (server-side) agar ``degraded`` bisa dilaporkan jujur ke UI.
    """
    errors: list[str] = []
    out: list[dict] = []
    source: str | None = None
    # Yahoo yang membalas daftar kosong (`[]`) BUKAN bukti sumber hidup: feed
    # berita Yahoo kerap mati-diam tanpa melempar. Jadi `source_ok` dinyalakan
    # hanya bila sumber benar-benar MENYAJIKAN item (Yahoo) atau berhasil
    # diambil tanpa exception (RSS). Konsekuensinya, kegagalan RSS setelah Yahoo
    # kosong tetap dilaporkan `degraded=True` → UI jujur "sumber tidak
    # tersedia", bukan bohong "Tidak ada berita".
    source_ok = False

    try:
        raw = yf.Ticker(yt).news or []
    except Exception as exc:  # noqa: BLE001 - kegagalan sumber dilaporkan, bukan disembunyikan
        raw = []
        errors.append(f"yahoo:{type(exc).__name__}")
    for n in raw[:limit]:
        item = _parse_item(n)
        if item:
            out.append(item)
    if out:
        source = "yahoo"
        source_ok = True
    else:
        try:
            for item in _rss_items(yt)[:limit]:
                out.append(item)
            source_ok = True
            if out:
                source = "google_news_rss"
        except Exception as exc:  # noqa: BLE001 - kegagalan sumber dilaporkan, bukan disembunyikan
            errors.append(f"rss:{type(exc).__name__}")

    return _Items(out, source=source, source_ok=source_ok, errors=errors)


def get_news(ticker: str, limit: int = 15) -> dict:
    t = (ticker or "").strip().upper()
    # Validasi sebelum cache/URL: ticker dari klien tak boleh menyusup ke query.
    if not _TICKER_RE.match(t):
        return {
            "ticker": t or (ticker or "").upper(),
            "count": 0,
            "avg_sentiment": 0.0,
            "label": "Netral",
            "items": [],
            "degraded": True,
            "source": None,
            "error": "Kode saham tidak valid",
        }
    yt = to_yahoo(t)
    now = time.time()
    with _cache_lock:
        cached = _cache.get("t:" + yt)
        if cached and now - cached[0] < cached[2]:
            return cached[1]

    raw = _raw_items(yt, limit)
    items = list(raw)
    source = getattr(raw, "source", None)
    source_ok = bool(getattr(raw, "source_ok", False))
    avg, label = _summarize(items)
    result = {
        "ticker": t,
        "count": len(items),
        "avg_sentiment": avg,
        "label": label,
        "items": items,
        "degraded": (not items) and not source_ok,
        "source": source,
    }
    ttl = _TTL if items else _NEGATIVE_TTL
    with _cache_lock:
        _cache["t:" + yt] = (now, result, ttl)
        _prune_cache_locked()
    return result


def _prune_cache_locked() -> None:
    """Buang entri berita kedaluwarsa lalu tertua bila melebihi batas.

    Dipanggil saat ``_cache_lock`` sedang dipegang. Hanya membuang entri dari
    cache; permintaan berikutnya akan mengambil ulang berita, bukan hasil salah.
    """
    assert _cache_lock.locked(), "harus dipanggil dengan _cache_lock dipegang"
    fresh = time.time()
    expired = [k for k, (ts, _v, ttl) in _cache.items() if fresh - ts >= ttl]
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
        if cached and now - cached[0] < cached[2]:
            return cached[1]

    seen: set[str] = set()
    items: list[dict] = []
    sources: set[str] = set()
    any_source_ok = False
    for t in universe:
        yt = to_yahoo(t) if t != "^JKSE" else "^JKSE"
        raw = _raw_items(yt, limit)
        if getattr(raw, "source", None):
            sources.add(raw.source)
        if getattr(raw, "source_ok", False):
            any_source_ok = True
        for item in raw:
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
        "degraded": (not items) and not any_source_ok,
        "source": ",".join(sorted(sources)) if sources else None,
    }
    ttl = _TTL if items else _NEGATIVE_TTL
    with _cache_lock:
        _cache[ckey] = (now, result, ttl)
        _prune_cache_locked()
    return result
