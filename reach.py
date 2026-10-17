"""Sumber internet gratis untuk satu kode saham.

Kanal tanpa kunci (web lewat Jina Reader, YouTube, RSS, GitHub, Bilibili,
Reddit) diambil lewat HTTP. V2EX tidak dipanggil: API publiknya hanya topik
panas global, bukan pencarian kode. Kanal yang butuh cookie browser hanya
ditandai, tidak pernah dijalankan di server. Hasilnya konteks bacaan, bukan
harga bursa dan tidak masuk skor.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import news

_TICKER_RE = re.compile(r"^[A-Z0-9.^\-]{1,12}$")
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_TTL_OK = 600.0
_TTL_THIN = 120.0
_CACHE_MAX = 384
_JKT = ZoneInfo("Asia/Jakarta")
_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
_MAX_BYTES = 400_000
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_HOSTS = frozenset({
    "r.jina.ai",
    "news.google.com",
    "www.youtube.com",
    "api.github.com",
    "api.bilibili.com",
    "www.reddit.com",
})
_NOTE = (
    "Judul dari sumber publik. Bukan harga transaksi bursa dan bukan sinyal. "
    "Tidak masuk skor."
)
_LOCKED = (
    ("twitter", "Twitter/X", "Butuh cookie browser. Tidak dijalankan di server."),
    ("xueqiu", "Xueqiu", "Butuh cookie browser. Tidak dijalankan di server."),
    ("facebook", "Facebook", "Butuh sesi browser. Tidak dijalankan di server."),
    ("instagram", "Instagram", "Butuh sesi browser. Tidak dijalankan di server."),
    ("xiaohongshu", "Xiaohongshu", "Butuh cookie browser. Tidak dijalankan di server."),
    ("linkedin", "LinkedIn", "Butuh sesi browser. Tidak dijalankan di server."),
    ("boss", "Boss直聘", "Butuh login browser. Tidak dijalankan di server."),
    ("xiaoyuzhou", "Xiaoyuzhou", "Butuh kunci transkrip. Tidak dijalankan di server."),
)


def _channel(cid: str, label: str, status: str, detail: str, items: list[dict] | None = None) -> dict:
    return {
        "id": cid,
        "label": label,
        "status": status,
        "detail": detail,
        "items": items or [],
    }


def _locked(cid: str, label: str, detail: str) -> dict:
    return _channel(cid, label, "perlu_login", detail, [])


def _has_code(text: str, ticker: str) -> bool:
    return re.search(
        rf"(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])",
        (text or "").upper(),
    ) is not None


def _about_ticker(text: str, ticker: str) -> bool:
    """Kode utuh, atau 'BCA' bila kodenya BBCA (judul berita sering menyingkat)."""
    if _has_code(text, ticker):
        return True
    if ticker == "BBCA":
        return re.search(r"(?<![A-Z0-9])BCA(?![A-Z0-9])", (text or "").upper()) is not None
    return False


def _clean_title(text: str) -> str:
    title = re.sub(r"<[^>]+>", "", text or "")
    title = re.sub(r"\s+", " ", title).strip()
    return title[:180]


def _format_date(dt: datetime) -> str:
    local = dt.astimezone(_JKT) if dt.tzinfo else dt.replace(tzinfo=_JKT)
    return f"{local.day} {_MONTHS[local.month]} {local.year}"


def _when_phrase(text: str) -> str:
    """Teks relatif pendek dari sumber, misalnya '2 hari yang lalu'."""
    phrase = _clean_title(text)
    if not phrase or len(phrase) > 40 or "://" in phrase:
        return ""
    return phrase


def _when_stamp(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        return _format_date(parsedate_to_datetime(raw))
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    try:
        return _format_date(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return ""


def _when_unix(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if not (1_000_000_000 <= float(value) <= 4_000_000_000):
        return ""
    try:
        return _format_date(datetime.fromtimestamp(int(value), _JKT))
    except (OverflowError, OSError, ValueError):
        return ""


def _row(title: str, url: str, when: str = "") -> dict:
    return {"title": title, "url": url, "when": when}


def _http_url(url: str) -> str:
    raw = (url or "").strip()
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        return ""
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        return ""
    return raw


def _unwrap_ddg(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        dest = (urllib.parse.parse_qs(parsed.query).get("uddg") or [""])[0]
        return _http_url(urllib.parse.unquote(dest))
    if host.endswith("duckduckgo.com"):
        return ""
    return _http_url(url)


def parse_web_markdown(text: str, ticker: str) -> list[dict]:
    """Ambil tautan dari markdown Jina. Lewati aset DuckDuckGo sendiri."""
    out: list[dict] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?<!!)\[([^\]]{4,180})\]\((https?://[^)\s]+)\)", text or ""):
        title = _clean_title(match.group(1))
        url = _unwrap_ddg(match.group(2))
        if not title or not url or url in seen:
            continue
        if not (_about_ticker(title, ticker) or _has_code(url, ticker)):
            continue
        seen.add(url)
        out.append(_row(title, url))
        if len(out) >= 5:
            break
    return out


def parse_youtube(payload: dict, ticker: str) -> list[dict]:
    """Video yang judulnya menyebut kode. Hasil lain tidak ditampilkan."""
    matched: list[dict] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            video = node.get("videoRenderer")
            if isinstance(video, dict):
                title = ""
                raw = video.get("title") or {}
                if isinstance(raw, dict):
                    runs = raw.get("runs") or []
                    if runs and isinstance(runs[0], dict):
                        title = str(runs[0].get("text") or "")
                    title = title or str(raw.get("simpleText") or "")
                vid = str(video.get("videoId") or "")
                title = _clean_title(title)
                published = video.get("publishedTimeText") or {}
                when = _when_phrase(str(published.get("simpleText") or "") if isinstance(published, dict) else "")
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) and title and _about_ticker(title, ticker):
                    matched.append(_row(title, f"https://www.youtube.com/watch?v={vid}", when))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return matched[:5]


def parse_bilibili(payload: dict, ticker: str) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return []
    result = (payload.get("data") or {}).get("result") or []
    if not isinstance(result, list):
        return []
    out: list[dict] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        title = _clean_title(str(item.get("title") or ""))
        url = _http_url(str(item.get("arcurl") or ""))
        host = (urllib.parse.urlparse(url).hostname or "").lower() if url else ""
        if not title or not url or not host.endswith("bilibili.com"):
            continue
        if not _has_code(title, ticker):
            continue
        out.append(_row(title, url, _when_unix(item.get("pubdate"))))
        if len(out) >= 5:
            break
    return out


def parse_github(payload: dict, ticker: str) -> list[dict]:
    out: list[dict] = []
    for item in (payload.get("items") or [])[:20]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        full_name = str(item.get("full_name") or "")
        desc = _clean_title(str(item.get("description") or ""))
        named = _has_code(name, ticker) or _has_code(full_name, ticker)
        # Deskripsi pendek seperti "saham BBCA" pada repo bernama "file" dibuang.
        described = _has_code(desc, ticker) and len(desc) >= 24
        if not named and not described:
            continue
        url = _http_url(str(item.get("html_url") or ""))
        if not url.startswith("https://github.com/"):
            continue
        title = desc if described and not named else _clean_title(full_name or name)
        when = _when_stamp(str(item.get("pushed_at") or item.get("updated_at") or ""))
        if title:
            out.append(_row(title, url, when))
        if len(out) >= 5:
            break
    return out


def _fetch(
    url: str, *, headers: dict | None = None, data: bytes | None = None,
    timeout: float = 6.0, max_bytes: int = _MAX_BYTES,
) -> bytes:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host not in _HOSTS:
        raise ValueError("host tidak diizinkan")
    req = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(max_bytes + 1)
    return raw[:max_bytes]


def _query(ticker: str) -> str:
    return f"{ticker} saham"


def _fail(cid: str, label: str, detail: str) -> dict:
    return _channel(cid, label, "gagal", detail, [])


def _from_items(cid: str, label: str, items: list[dict]) -> dict:
    if items:
        return _channel(cid, label, "ok", f"{len(items)} judul.", items)
    return _channel(cid, label, "kosong", "Belum ada bahasan untuk kode ini.", [])


def _call(cid: str, label: str, fn, ticker: str, fetcher) -> dict:
    try:
        return fn(ticker, fetcher)
    except Exception:
        return _fail(cid, label, "Sumber tidak membalas.")


def _web(ticker: str, fetcher) -> dict:
    q = urllib.parse.quote(_query(ticker))
    url = f"https://r.jina.ai/https://html.duckduckgo.com/html/?q={q}"
    raw = fetcher(url, headers={"User-Agent": _UA, "Accept": "text/plain"}, data=None, timeout=8.0)
    text = raw.decode("utf-8", "replace")
    return _from_items("web", "Web", parse_web_markdown(text, ticker))


def _youtube(ticker: str, fetcher) -> dict:
    body = json.dumps({
        "context": {"client": {"clientName": "WEB", "clientVersion": "2.20240101.01.00", "hl": "id", "gl": "ID"}},
        "query": _query(ticker),
    }).encode()
    raw = fetcher(
        "https://www.youtube.com/youtubei/v1/search?prettyPrint=false",
        headers={"User-Agent": _UA, "Content-Type": "application/json"},
        data=body,
        timeout=12.0,
        max_bytes=1_500_000,
    )
    payload = json.loads(raw.decode("utf-8", "replace") or "{}")
    return _from_items("youtube", "YouTube", parse_youtube(payload, ticker))


def _rss(ticker: str, fetcher) -> dict:
    q = urllib.parse.quote(_query(ticker))
    url = f"https://news.google.com/rss/search?q={q}&hl=id&gl=ID&ceid=ID:id"
    raw = fetcher(
        url,
        headers={"User-Agent": _UA, "Accept": "application/rss+xml, application/xml"},
        data=None,
        timeout=6.0,
    )
    items = []
    for row in news._parse_rss(raw)[:8]:
        title = _clean_title(str(row.get("title") or ""))
        link = _http_url(str(row.get("url") or ""))
        if not title or not _about_ticker(title, ticker):
            continue
        items.append(_row(title, link, _when_stamp(str(row.get("time") or ""))))
        if len(items) >= 5:
            break
    return _from_items("rss", "RSS", items)


def _github(ticker: str, fetcher) -> dict:
    q = urllib.parse.quote(f"{ticker} saham")
    url = f"https://api.github.com/search/repositories?q={q}&per_page=10"
    raw = fetcher(
        url,
        headers={"User-Agent": "laumology", "Accept": "application/vnd.github+json"},
        data=None,
        timeout=6.0,
    )
    return _from_items("github", "GitHub", parse_github(json.loads(raw.decode("utf-8", "replace") or "{}"), ticker))


def _bilibili(ticker: str, fetcher) -> dict:
    q = urllib.parse.quote(_query(ticker))
    url = f"https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={q}"
    try:
        raw = fetcher(
            url,
            headers={"User-Agent": _UA, "Accept": "application/json", "Referer": "https://www.bilibili.com/"},
            data=None,
            timeout=6.0,
        )
    except urllib.error.HTTPError as exc:
        exc.close()
        return _fail("bilibili", "Bilibili", "Bilibili menolak permintaan server.")
    text = raw.decode("utf-8", "replace").lstrip()
    if not text.startswith("{"):
        return _fail("bilibili", "Bilibili", "Bilibili menolak permintaan server.")
    return _from_items("bilibili", "Bilibili", parse_bilibili(json.loads(text), ticker))


def _reddit(ticker: str, fetcher) -> dict:
    q = urllib.parse.quote(_query(ticker))
    url = f"https://www.reddit.com/search.json?q={q}&limit=5&sort=new"
    try:
        raw = fetcher(url, headers={"User-Agent": "laumology/1.0"}, data=None, timeout=6.0)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (401, 403, 429):
            return _locked("reddit", "Reddit", "Reddit menolak server ini. Butuh sesi browser.")
        return _fail("reddit", "Reddit", "Reddit tidak membalas.")
    payload = json.loads(raw.decode("utf-8", "replace") or "{}")
    items = []
    for child in ((payload.get("data") or {}).get("children") or [])[:8]:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        title = _clean_title(str(data.get("title") or ""))
        if not _has_code(title, ticker):
            continue
        link = _http_url("https://www.reddit.com" + str(data.get("permalink") or ""))
        if title and link:
            created = data.get("created_utc")
            items.append(_row(title, link, _when_unix(created)))
    return _from_items("reddit", "Reddit", items)


_LIVE = (
    ("web", "Web", _web),
    ("youtube", "YouTube", _youtube),
    ("rss", "RSS", _rss),
    ("github", "GitHub", _github),
    ("bilibili", "Bilibili", _bilibili),
    ("reddit", "Reddit", _reddit),
)


def _gather(ticker: str, fetcher) -> dict:
    by_id: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(_LIVE)) as pool:
        futures = {
            pool.submit(_call, cid, label, fn, ticker, fetcher): cid
            for cid, label, fn in _LIVE
        }
        for fut, cid in futures.items():
            by_id[cid] = fut.result()
    channels = [by_id[cid] for cid, _label, _fn in _LIVE]
    channels.extend(_locked(cid, label, detail) for cid, label, detail in _LOCKED)
    return {"ticker": ticker, "note": _NOTE, "channels": channels}


def _ttl_for(channel: dict) -> float:
    """Kanal gagal diulang lebih cepat. Kanal yang berhasil tetap 10 menit."""
    return _TTL_THIN if channel.get("status") == "gagal" else _TTL_OK


def _channel_get(ticker: str, cid: str) -> dict | None:
    now = time.time()
    key = f"{ticker}:{cid}"
    with _CACHE_LOCK:
        row = _CACHE.get(key)
        if not row:
            return None
        ts, channel = row
        if now - ts < _ttl_for(channel):
            return channel
        _CACHE.pop(key, None)
    return None


def _channel_set(ticker: str, cid: str, channel: dict) -> None:
    now = time.time()
    key = f"{ticker}:{cid}"
    with _CACHE_LOCK:
        _CACHE[key] = (now, channel)
        if len(_CACHE) > _CACHE_MAX:
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[: len(_CACHE) - _CACHE_MAX]
            for old, _row in oldest:
                _CACHE.pop(old, None)


def for_ticker(ticker: str, fetcher=None) -> dict:
    """Kumpulkan kanal untuk satu kode. ``fetcher`` hanya untuk uji, tanpa cache."""
    code = (ticker or "").strip().upper()
    if not _TICKER_RE.fullmatch(code):
        return {"ticker": code, "error": "Kode saham tidak valid", "channels": []}
    if fetcher is not None:
        return _gather(code, fetcher)
    by_id: dict[str, dict] = {}
    pending = []
    for cid, label, fn in _LIVE:
        hit = _channel_get(code, cid)
        if hit is not None:
            by_id[cid] = hit
        else:
            pending.append((cid, label, fn))
    if pending:
        with ThreadPoolExecutor(max_workers=len(pending)) as pool:
            futures = {
                pool.submit(_call, cid, label, fn, code, _fetch): cid
                for cid, label, fn in pending
            }
            for fut, cid in futures.items():
                channel = fut.result()
                by_id[cid] = channel
                _channel_set(code, cid, channel)
    channels = [by_id[cid] for cid, _label, _fn in _LIVE]
    channels.extend(_locked(cid, label, detail) for cid, label, detail in _LOCKED)
    return {"ticker": code, "note": _NOTE, "channels": channels}
