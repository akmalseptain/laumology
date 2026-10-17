"""Sumber internet gratis untuk satu kode saham.

Kanal tanpa kunci (web lewat Jina Reader, YouTube, RSS, GitHub, Bilibili, V2EX,
Reddit) diambil lewat HTTP. Kanal yang butuh cookie browser hanya ditandai,
tidak pernah dijalankan di server. Hasilnya konteks bacaan, bukan harga bursa
dan tidak masuk skor.
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

import news

_TICKER_RE = re.compile(r"^[A-Z0-9.^\-]{1,12}$")
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_TTL_OK = 600.0
_TTL_THIN = 120.0
_CACHE_MAX = 128
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
    "www.v2ex.com",
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


def _clean_title(text: str) -> str:
    title = re.sub(r"<[^>]+>", "", text or "")
    title = re.sub(r"\s+", " ", title).strip()
    return title[:180]


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
        if not _has_code(f"{title} {url}", ticker):
            continue
        seen.add(url)
        out.append({"title": title, "url": url})
        if len(out) >= 5:
            break
    return out


def parse_youtube(payload: dict, ticker: str) -> list[dict]:
    """Video teratas dari pencarian. Judul yang memuat kode didahulukan."""
    matched: list[dict] = []
    rest: list[dict] = []

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
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) and title:
                    row = {"title": title, "url": f"https://www.youtube.com/watch?v={vid}"}
                    if _has_code(title, ticker):
                        matched.append(row)
                    else:
                        rest.append(row)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return (matched or rest)[:5]


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
        out.append({"title": title, "url": url})
        if len(out) >= 5:
            break
    return out


def parse_github(payload: dict, ticker: str) -> list[dict]:
    out: list[dict] = []
    for item in (payload.get("items") or [])[:20]:
        if not isinstance(item, dict):
            continue
        blob = " ".join(
            str(item.get(key) or "") for key in ("full_name", "name", "description")
        )
        if not _has_code(blob, ticker):
            continue
        url = _http_url(str(item.get("html_url") or ""))
        if not url.startswith("https://github.com/"):
            continue
        title = _clean_title(str(item.get("full_name") or item.get("name") or ""))
        desc = _clean_title(str(item.get("description") or ""))
        if desc:
            title = _clean_title(f"{title} — {desc}")
        if title:
            out.append({"title": title, "url": url})
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
        if not title:
            continue
        items.append({"title": title, "url": link})
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


def _v2ex(ticker: str, fetcher) -> dict:
    raw = fetcher(
        "https://www.v2ex.com/api/topics/hot.json",
        headers={"User-Agent": "laumology", "Accept": "application/json"},
        data=None,
        timeout=6.0,
    )
    rows = json.loads(raw.decode("utf-8", "replace") or "[]")
    items = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = _clean_title(str(row.get("title") or ""))
            if not _has_code(title, ticker):
                continue
            url = _http_url(str(row.get("url") or ""))
            if title and url:
                items.append({"title": title, "url": url})
    return _from_items("v2ex", "V2EX", items)


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
            items.append({"title": title, "url": link})
    return _from_items("reddit", "Reddit", items)


_LIVE = (
    ("web", "Web", _web),
    ("youtube", "YouTube", _youtube),
    ("rss", "RSS", _rss),
    ("github", "GitHub", _github),
    ("bilibili", "Bilibili", _bilibili),
    ("v2ex", "V2EX", _v2ex),
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


def _cache_get(ticker: str) -> dict | None:
    now = time.time()
    with _CACHE_LOCK:
        row = _CACHE.get(ticker)
        if not row:
            return None
        ts, payload = row
        ttl = _TTL_OK if any(c.get("status") == "ok" for c in payload.get("channels") or []) else _TTL_THIN
        if now - ts < ttl:
            return payload
        _CACHE.pop(ticker, None)
    return None


def _cache_set(ticker: str, payload: dict) -> None:
    now = time.time()
    with _CACHE_LOCK:
        _CACHE[ticker] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[: len(_CACHE) - _CACHE_MAX]
            for key, _row in oldest:
                _CACHE.pop(key, None)


def for_ticker(ticker: str, fetcher=None) -> dict:
    """Kumpulkan kanal untuk satu kode. ``fetcher`` hanya untuk uji."""
    code = (ticker or "").strip().upper()
    if not _TICKER_RE.fullmatch(code):
        return {"ticker": code, "error": "Kode saham tidak valid", "channels": []}
    if fetcher is None:
        hit = _cache_get(code)
        if hit is not None:
            return hit
        payload = _gather(code, _fetch)
        _cache_set(code, payload)
        return payload
    return _gather(code, fetcher)
