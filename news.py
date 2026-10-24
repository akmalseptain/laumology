from __future__ import annotations

import html
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import pandas as pd
import yfinance as yf

from data import to_yahoo

_log = logging.getLogger("laumology.news")

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

# Sumber berita. `yf.Ticker(...).news` dicoba lebih dulu, lalu fallback RSS:
# Bing News RSS (`bing.com/news/search?format=RSS`) didahulukan karena
# menyertakan gambar + ringkasan asli, lalu Google News RSS
# (`news.google.com/rss/search`) sebagai cadangan terakhir. Sumber RSS Yahoo
# lama tidak lagi dipakai; `yf.Ticker(...).news` kerap mengembalikan daftar
# kosong sehingga fallback memang dibutuhkan.
_RSS_URL = "https://news.google.com/rss/search"
_BING_URL = "https://www.bing.com/news/search"
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


# Panjang maksimum ringkasan (summary) yang diteruskan ke UI. `<description>`
# RSS atau `summary` Yahoo bisa sangat panjang dan cache dibatasi 512 entri,
# jadi dipotong keras agar payload tidak membengkak (memory-DoS).
_MAX_SUMMARY = 240

# Panjang minimum sisa ringkasan agar dianggap bermakna. Google News RSS
# menaruh `<description>` = "Judul Penerbit" (tanpa tanda hubung), padahal
# keduanya sudah tampil di UI (judul + meta penerbit). Setelah awalan judul /
# akhiran penerbit dibuang, sisa di bawah ambang ini berarti ringkasan memang
# hanya mengulang — kembalikan `None` agar UI memakai fallback jujur.
# Diselaraskan dengan gate `meaningful` di `static/js/views.js`.
_MIN_SUMMARY = 24


class _TextExtract(HTMLParser):
    """Ambil teks murni dari HTML tanpa `defusedxml`/regex (anti-bypass)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _title_basename(title: str, publisher) -> str:
    """Buang akhiran " - Penerbit" dari judul Google News (mis. "X - Pub").

    `re.escape` wajib: `title`/`publisher` berasal dari RSS pihak ketiga dan
    tak boleh diperlakukan sebagai pola regex.
    """
    t = (title or "").strip()
    pub = (publisher or "").strip()
    if pub:
        t = re.sub(
            r"\s*[-–—|·]\s*" + re.escape(pub) + r"\s*$",
            "", t, flags=re.IGNORECASE,
        )
    return t.strip()


def _strip_redundant(plain: str, title: str, publisher) -> str:
    """Buang awalan judul + akhiran penerbit yang sudah tampil di UI.

    Dikerjakan pada teks polos SEBELUM pemotongan `_MAX_SUMMARY` agar akhiran
    penerbit tak terpangkas lebih dulu (kalau tidak, sisa duplikat lolos).
    Hanya awalan/akhiran persis yang dipotong (setelah normalisasi spasi),
    bukan substring bebas, supaya ringkasan asli tak terpangkas sembarangan.
    """
    s = plain
    # Judul lengkap ("X - Pub") dan judul bersih ("X").
    for prefix in (_title_basename(title, publisher), (title or "").strip()):
        p = prefix
        if p:
            s = re.sub(r"^\s*" + re.escape(p) + r"\s*", "", s, flags=re.IGNORECASE)
    pub = (publisher or "").strip()
    if pub:
        s = re.sub(
            r"\s*[-–—|·]?\s*" + re.escape(pub) + r"\s*$",
            "", s, flags=re.IGNORECASE,
        )
    return s.strip()


def _clean_summary(text, title=None, publisher=None) -> str | None:
    """Bersihkan HTML `<description>`/`summary` jadi teks polos terbatas panjang.

    Sengaja dipisah dari `_sentiment`: ringkasan TIDAK boleh ikut menghitung
    sentimen (label tetap title-only), hanya untuk kejelasan singkat di UI.

    Bila `title`/`publisher` diberikan (jalur RSS Google News), redundansi
    "judul + penerbit" dibuang lebih dulu. Blob cluster `<ol>` (banyak headline
    tergabung) langsung ditolak (`None`) karena tak bisa dipisah dengan aman.
    """
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if title or publisher:
        if re.search(r"<ol\b", raw, flags=re.IGNORECASE):
            return None
    try:
        parser_obj = _TextExtract()
        parser_obj.feed(raw)
        parser_obj.close()
        plain = parser_obj.get_text()
    except Exception:  # noqa: BLE001 - parser gagal, fallback aman
        plain = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return None
    if title or publisher:
        plain = _strip_redundant(plain, title or "", publisher)
        if len(plain) < _MIN_SUMMARY:
            return None
    if len(plain) > _MAX_SUMMARY:
        plain = plain[:_MAX_SUMMARY].rstrip() + "…"
    return plain


def _safe_http_url(url) -> str | None:
    """Validasi server-side: hanya terima http(s) ber-host; tolak skema lain."""
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u:
        return None
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return u
    return None


def _favicon_url(url) -> str | None:
    """Favicon host dari URL penerbit TERVALIDASI (dipakai klien, bukan server).

    Hanya dipakai sebagai cadangan bila ``<enclosure>`` tiada. Host diambil dari
    ``hostname`` (bukan ``netloc``) agar userinfo/``x@host`` tak ikut terbawa.
    Endpoint favicon pihak ketiga (mis. Google) TIDAK dipakai supaya host tidak
    bocor; gambar tetap dimuat klien lewat ``<img referrerpolicy="no-referrer">``.
    """
    safe = _safe_http_url(url)
    if not safe:
        return None
    parsed = urllib.parse.urlparse(safe)
    host = parsed.hostname
    if not host:
        return None
    netloc = host
    try:
        if parsed.port:
            netloc = f"{host}:{parsed.port}"
    except ValueError:
        return None
    return f"{parsed.scheme}://{netloc}/favicon.ico"


def _local_name(tag) -> str:
    """Nama lokal tag XML tanpa namespace (mis. ``{ns}Image`` → ``Image``).

    Bing News RSS memakai prefix ``News:`` dengan URI namespace DINAMIS (memuat
    parameter query ``?q=...``), jadi pencocokan tag lewat namespace mustahil.
    """
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _bing_image_url(url) -> str | None:
    """Validasi gambar Bing: host `.bing.com` (subdomain boleh) + paksa https.

    Gambar pihak ketiga TIDAK diterima: hanya host Bing yang dikenali yang
    dirender klien. Host diperiksa lewat ``hostname`` (bukan ``netloc``) agar
    userinfo ``bing.com@evil`` tak lolos; scheme dipaksa ``https`` (hindari
    mixed-content). Port eksplisit selain 443 ditolak agar permukaan hotlink
    tetap sempit (``bing.com:8443`` gugur), lalu port default dihilangkan dari
    netloc.
    """
    safe = _safe_http_url(url)
    if not safe:
        return None
    parsed = urllib.parse.urlparse(safe)
    host = (parsed.hostname or "").lower()
    if host != "bing.com" and not host.endswith(".bing.com"):
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port not in (None, 443):
        return None
    return urllib.parse.urlunparse(
        ("https", host, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def _decode_bing_link(link) -> str | None:
    """Ambil URL penerbit asli dari tautan ``apiclick`` Bing News RSS.

    ``apiclick.aspx?...&url=<encoded>`` di-decode lewat ``parse_qs`` (sekali,
    bukan potong substring) lalu divalidasi ulang ``_safe_http_url`` sehingga
    ``javascript:``/skema jahat/double-encode ditolak. Bila parameter absen atau
    tidak valid, kembalikan ``None`` — item tetap dipakai dengan ``url=None``.
    """
    safe = _safe_http_url(link)
    if not safe:
        return None
    parsed = urllib.parse.urlparse(safe)
    host = (parsed.hostname or "").lower()
    if host != "bing.com" and not host.endswith(".bing.com"):
        return None
    target = urllib.parse.parse_qs(parsed.query).get("url")
    if not target:
        return None
    return _safe_http_url(target[0])


def _thumb_url(thumb) -> str | None:
    """Ambil URL gambar dari `thumbnail` Yahoo (dict dengan `resolutions`)."""
    if isinstance(thumb, dict):
        res = thumb.get("resolutions")
        if isinstance(res, list):
            for entry in res:
                if isinstance(entry, dict):
                    u = _safe_http_url(entry.get("url"))
                    if u:
                        return u
        return _safe_http_url(thumb.get("url"))
    return _safe_http_url(thumb)


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
        summary = content.get("summary") or content.get("description")
        image = _thumb_url(content.get("thumbnail"))
    else:
        title = n.get("title")
        publisher = n.get("publisher")
        link = n.get("link")
        ts = n.get("providerPublishTime")
        summary = n.get("summary") or n.get("description")
        image = _thumb_url(n.get("thumbnail"))
    if not title:
        return None
    pos, neg, score = _sentiment(title)
    return {
        "title": title,
        "publisher": publisher,
        "publisher_url": None,
        "url": _safe_http_url(link),
        "time": ts,
        "sentiment": score,
        "pos": pos,
        "neg": neg,
        "summary": _clean_summary(summary),
        "image": image,
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
        link = _safe_http_url((node.findtext("link") or "").strip() or None)
        source_node = node.find("source")
        publisher = (node.findtext("source") or "").strip() or None
        # `<source url="...">` Google News RSS dibuang bila hanya `findtext`;
        # ambil `url`-nya lewat `_safe_http_url` (menolak skema/host tak valid)
        # sebagai dasar favicon cadangan. JANGAN dipakai sebagai tautan (open
        # redirect) — tautan tetap `link` yang sudah divalidasi.
        publisher_url = _safe_http_url(source_node.get("url")) if source_node is not None else None
        ts = (node.findtext("pubDate") or "").strip() or None
        enclosure = node.find("enclosure")
        image = _safe_http_url(enclosure.get("url") if enclosure is not None else None)
        if not image:
            image = _favicon_url(publisher_url)
        pos, neg, score = _sentiment(title)
        out.append({
            "title": title,
            "publisher": publisher,
            "publisher_url": publisher_url,
            "url": link,
            "time": ts,
            "sentiment": score,
            "pos": pos,
            "neg": neg,
            "summary": _clean_summary(node.findtext("description"), title, publisher),
            "image": image,
        })
    return out


def _parse_bing_rss(xml_bytes: bytes) -> list[dict]:
    """Urai Bing News RSS ke skema item yang sama dengan ``_parse_item``.

    ``<item>`` dicocokkan by local-name (namespace Bing dinamis). Gambar diambil
    dari ``News:Image`` (divalidasi host ``.bing.com`` + paksa https), penerbit
    dari ``News:Source``, dan ringkasan asli dari ``<description>`` (bukan
    "judul + penerbit" seperti Google News). Batas keamanan sama: DTD/entitas
    ditolak, ukuran sudah dipotong pemanggil.
    """
    if not xml_bytes:
        return []
    _reject_dtd(xml_bytes)
    root = ET.fromstring(xml_bytes)
    out: list[dict] = []
    for node in root.iter():
        if _local_name(node.tag) != "item":
            continue
        title = ""
        publisher = None
        link = None
        ts = None
        description = None
        image = None
        for child in node:
            name = _local_name(child.tag)
            text = (child.text or "").strip()
            if name == "title":
                title = text
            elif name == "link":
                link = _decode_bing_link(text or None)
            elif name == "description":
                description = child.text
            elif name == "pubDate":
                ts = text or None
            elif name == "Image":
                image = _bing_image_url(text)
            elif name == "Source":
                publisher = text or None
        if not title:
            continue
        pos, neg, score = _sentiment(title)
        out.append({
            "title": title,
            "publisher": publisher,
            "publisher_url": None,
            "url": link,
            "time": ts,
            "sentiment": score,
            "pos": pos,
            "neg": neg,
            "summary": _clean_summary(description, title, publisher),
            "image": image,
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


def _bing_items(yt: str) -> list[dict]:
    """Ambil berita dari Bing News RSS untuk simbol Yahoo ``yt``."""
    query = urllib.parse.quote(_rss_query(yt) + " saham")
    url = f"{_BING_URL}?q={query}&format=RSS&setlang=id"
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
    return _parse_bing_rss(raw)


def _raw_items(yt: str, limit: int) -> list[dict]:
    """Item berita terbaik: coba Yahoo dulu, lalu fallback Bing/Google News RSS.

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
        # Bing News RSS didahulukan: menyertakan gambar + ringkasan asli,
        # sedangkan Google News hanya favicon + deskripsi "judul penerbit".
        for fetcher, name in (
            (_bing_items, "bing_news_rss"),
            (_rss_items, "google_news_rss"),
        ):
            try:
                fetched = fetcher(yt)[:limit]
            except Exception as exc:  # noqa: BLE001 - kegagalan sumber dilaporkan
                errors.append(f"{name}:{type(exc).__name__}")
                continue
            # Sumber merespons tanpa exception → jaringan hidup (walau kosong).
            source_ok = True
            if fetched:
                out.extend(fetched)
                source = name
                break

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


_QUERY_OK = re.compile(r"^[0-9A-Za-z][0-9A-Za-z \-]{2,79}$")


def _http_xml(url: str) -> bytes:
    """Ambil XML RSS dengan plafon byte yang sama seperti jalur berita lain."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _RSS_UA,
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=_RSS_TIMEOUT) as resp:
        raw = resp.read(_RSS_MAX_BYTES + 1)
    if len(raw) > _RSS_MAX_BYTES:
        raw = raw[:_RSS_MAX_BYTES]
    return raw


def headlines_for_query(query: str, limit: int = 12) -> tuple[list[dict], bool]:
    """Judul berita untuk satu kueri makro tetap (bukan ticker klien).

    Mengembalikan ``(item, sumber_hidup)``. Kueri di luar pola aman ditolak
    tanpa jaringan. Dipakai lapisan tekanan luar; tidak membuka pencarian bebas.
    """
    q = re.sub(r"\s+", " ", (query or "")).strip()
    if not _QUERY_OK.match(q):
        return [], True
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 12
    now = time.time()
    ckey = "q:" + q.lower()
    with _cache_lock:
        cached = _cache.get(ckey)
        if cached and now - cached[0] < cached[2]:
            items, ok = cached[1]
            return list(items), bool(ok)

    items: list[dict] = []
    ok = False
    quoted = urllib.parse.quote(q)
    attempts = (
        (f"{_BING_URL}?q={quoted}&format=RSS&setlang=id", _parse_bing_rss),
        (f"{_RSS_URL}?q={quoted}&hl=id&gl=ID&ceid=ID:id", _parse_rss),
    )
    for url, parser in attempts:
        try:
            parsed = parser(_http_xml(url))
        except Exception as exc:
            _log.warning(
                "sumber berita makro %s utk kueri %r gagal (%s) - dicoba sumber berikutnya",
                urllib.parse.urlparse(url).netloc, q, type(exc).__name__,
            )
            continue
        ok = True
        if parsed:
            items = parsed[:limit]
            break
    ttl = _TTL if items else _NEGATIVE_TTL
    with _cache_lock:
        _cache[ckey] = (now, (items, ok), ttl)
        _prune_cache_locked()
    return list(items), ok


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
