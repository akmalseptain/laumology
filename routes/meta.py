"""Endpoint meta: UI root, health, versi, metrik, skema, disclaimer, SEO."""
from __future__ import annotations

import os
import re
import sys
import time
from urllib.parse import urlsplit

from flask import Blueprint, Response, jsonify, render_template, request

import state
import store
from config import WATCHLIST_PRESETS

bp = Blueprint("meta", __name__)

# Karakter yang dilarang di base URL: spasi, kontrol, dan char yang bisa
# merusak XML/robots (``<``, ``>``, ``&``, kutip). Validasi sebelum dipakai.
_BAD_BASE_CHARS = frozenset(" \t\r\n<>&\"'")


def _validated_base(value: str | None) -> str:
    """Validasi base URL kanonik: hanya ``http``/``https`` + host non-kosong.

    Tolak path/query/fragment, karakter kontrol/XML, dan skema lain. Bila
    tidak valid → kembalikan ``""`` (fail-safe; JANGAN memakai input mentah).
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    if any(ch in _BAD_BASE_CHARS for ch in raw) or any(
        ord(ch) < 0x20 or ord(ch) == 0x7F for ch in raw
    ):
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    # Izinkan path kosong atau "/" (base + trailing slash); tolak path/query/
    # fragment lain agar tak menyisipkan teks ke XML/robots.
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _public_base() -> str:
    """Base URL kanonik publik untuk canonical/sitemap/robots.

    Divalidasi ketat (``_validated_base``). TIDAK PERNAH jatuh ke
    ``request.host_url``: jalur ini tak boleh memantulkan ``Host`` request
    (anti Host-spoof / cache poisoning). Bila ``LAUM_PUBLIC_BASE_URL``
    absen/invalid → ``""`` dan konsumen memakai lokasi relatif (fail-safe).
    """
    return _validated_base(os.environ.get("LAUM_PUBLIC_BASE_URL"))


# Tanggal modifikasi konten publik (W3C date). Nilai tetap agar sitemap
# deterministik (bukan ``datetime.now()`` yang berubah tiap request/run).
_CONTENT_LASTMOD = "2026-10-16"

# Token verifikasi Google Search Console harus murni alfanumerik + ``-``/``_``.
# Divalidasi ketat agar nilai env yang "jorok" (``"``, ``<``, dll) tak pernah
# masuk ke atribut ``content`` di <head> (anti HTML injection). Bila absen/
# invalid → ``""`` (fail-safe; tag tidak dirender).
_GSC_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# Token verifikasi Search Console untuk https://laumology.onrender.com.
# Publik: Google memintanya tampil di <head>. Env menimpa bila diisi valid.
_GSC_DEFAULT = "RnwQXP6N7GmFJnEJwvC_cPmgesMpyroVameSBPihrKE"


def _gsc_token() -> str:
    """Token verifikasi Google Search Console.

    Env ``LAUM_GOOGLE_SITE_VERIFICATION`` menimpa default bila valid.
    Kosong dianggap belum diset, jadi default dipakai. Nilai kotor
    (kutip, ``<``, spasi) ditolak dan tag tidak dirender.
    """
    raw = os.environ.get("LAUM_GOOGLE_SITE_VERIFICATION")
    if raw is None or not raw.strip():
        raw = _GSC_DEFAULT
    else:
        raw = raw.strip()
    if not _GSC_TOKEN_RE.fullmatch(raw):
        return ""
    return raw


# Berkas yang diunduh dari Search Console (metode unggah HTML).
# Isi harus sama persis dengan file di Downloads.
_GSC_HTML_FILE = "google42f09fe8816f0fe6.html"
_GSC_HTML_BODY = "google-site-verification: google42f09fe8816f0fe6.html\n"


@bp.route("/" + _GSC_HTML_FILE)
def gsc_html_file():
    """Berkas verifikasi di akar situs, tempat Google mencarinya."""
    return Response(_GSC_HTML_BODY, mimetype="text/html")


@bp.route("/")
def index():
    return render_template(
        "index.html",
        presets=list(WATCHLIST_PRESETS.keys()),
        canonical_base=_public_base(),
        site_verification=_gsc_token(),
    )


@bp.route("/tentang")
def tentang():
    """Halaman konten statis yang dapat di-crawl mesin pencari."""
    return render_template("tentang.html", canonical_base=_public_base())


@bp.route("/panduan")
def panduan():
    """Panduan how-to analisis saham IDX (konten statis, server-rendered)."""
    return render_template(
        "panduan.html",
        canonical_base=_public_base(),
        content_lastmod=_CONTENT_LASTMOD,
    )


@bp.route("/indikator-saham")
def indikator_saham():
    """Glosarium indikator saham IDX (konten statis, server-rendered)."""
    return render_template(
        "indikator-saham.html",
        canonical_base=_public_base(),
        content_lastmod=_CONTENT_LASTMOD,
    )


@bp.route("/robots.txt")
def robots():
    base = _public_base()
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "\n"
    )
    # Hanya tulis ``Sitemap:`` absolut bila base kanonik valid; bila tidak,
    # lewati agar ``Host`` request tak pernah dipantulkan.
    if base:
        body += f"Sitemap: {base}/sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@bp.route("/sitemap.xml")
def sitemap():
    base = _public_base()
    loc = f"{base}/" if base else "/"
    about_loc = f"{base}/tentang" if base else "/tentang"
    panduan_loc = f"{base}/panduan" if base else "/panduan"
    indikator_loc = f"{base}/indikator-saham" if base else "/indikator-saham"
    track_loc = f"{base}/track-record" if base else "/track-record"
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{loc}</loc><lastmod>{_CONTENT_LASTMOD}</lastmod>"
        "<changefreq>daily</changefreq>"
        "<priority>1.0</priority></url>\n"
        f"  <url><loc>{about_loc}</loc><lastmod>{_CONTENT_LASTMOD}</lastmod>"
        "<changefreq>weekly</changefreq>"
        "<priority>0.8</priority></url>\n"
        f"  <url><loc>{panduan_loc}</loc><lastmod>{_CONTENT_LASTMOD}</lastmod>"
        "<changefreq>weekly</changefreq>"
        "<priority>0.7</priority></url>\n"
        f"  <url><loc>{indikator_loc}</loc><lastmod>{_CONTENT_LASTMOD}</lastmod>"
        "<changefreq>weekly</changefreq>"
        "<priority>0.7</priority></url>\n"
        f"  <url><loc>{track_loc}</loc><lastmod>{_CONTENT_LASTMOD}</lastmod>"
        "<changefreq>daily</changefreq>"
        "<priority>0.9</priority></url>\n"
        "</urlset>\n"
    )
    return Response(body, mimetype="application/xml")


def _litestream_status() -> str:
    """Status persistensi dari marker render-start.sh (aktif / nonaktif:binary /
    nonaktif:env / nonaktif:binary+env / aktif:restore-error). Tanpa marker =
    jalankan di luar Render (lokal/CI) atau bootstrap lama."""
    try:
        p = store.DB_PATH.parent / "litestream.status"
        return p.read_text().strip() if p.exists() else "nonaktif:tanpa-marker"
    except Exception:
        return "unknown"


@bp.route("/health")
def health():
    return jsonify(status="ok", version=state.VERSION,
                   uptime_s=int(time.time() - state.START),
                   db=str(store.DB_PATH),
                   litestream=_litestream_status(),
                   time=time.strftime("%Y-%m-%d %H:%M:%S"))


@bp.route("/api/version")
def api_version():
    return jsonify(version=state.VERSION, engine="laumology", python=sys.version.split()[0])


@bp.route("/api/metrics")
def api_metrics():
    return jsonify(**state.metrics_snapshot())


@bp.route("/api/disclaimer")
def api_disclaimer():
    return jsonify(
        text=("LAUMOLOGY adalah alat bantu analisis dan edukasi, BUKAN nasihat keuangan/investasi. "
              "Data dapat tertunda dan akurasi tidak dijamin. Keputusan investasi sepenuhnya tanggung "
              "jawab pengguna. Selalu kelola risiko dan konsultasikan dengan penasihat berlisensi.")
    )


@bp.route("/api/schema")
def api_schema():
    return jsonify(version=state.VERSION, endpoints=[
        {"method": "GET", "path": "/api/analyze", "params": ["ticker", "interval", "refresh", "bars", "log"]},
        {"method": "GET", "path": "/api/ohlc", "params": ["ticker", "interval", "bars", "refresh"]},
        {"method": "GET", "path": "/api/quote", "params": ["ticker"]},
        {"method": "GET", "path": "/api/screen", "params": ["list", "top", "min_score", "min_conf", "sector", "min_value", "only_bullish"]},
        {"method": "GET", "path": "/api/backtest", "params": ["ticker", "interval", "min_score", "tp_rr", "sl_mult", "max_hold"]},
        {"method": "GET", "path": "/api/compare-backtest", "params": ["ticker", "interval", "tp_rr", "sl_mult", "max_hold"]},
        {"method": "GET", "path": "/api/compare-universe", "params": ["list", "tp_rr", "sl_mult", "max_hold", "refresh"]},
        {"method": "GET", "path": "/api/walkforward", "params": ["ticker", "folds"]},
        {"method": "GET", "path": "/api/optimize", "params": ["ticker"]},
        {"method": "GET", "path": "/api/optimize-weights", "params": ["list"]},
        {"method": "GET", "path": "/api/accuracy", "params": ["ticker", "horizon"]},
        {"method": "GET", "path": "/api/calibrate", "params": ["list", "horizon", "min_edge", "refresh"]},
        {"method": "GET", "path": "/api/regime-edge", "params": ["list", "horizon", "refresh"]},
        {"method": "GET", "path": "/api/edge", "params": ["universe", "horizon", "top", "min_count"]},
        {"method": "GET", "path": "/api/trackrecord", "params": []},
        {"method": "GET", "path": "/api/attribution", "params": ["horizon", "min_n"]},
        {"method": "GET", "path": "/api/verdicts", "params": ["horizon", "limit"]},
        {"method": "GET", "path": "/api/train", "params": ["list", "horizon", "folds"]},
        {"method": "GET", "path": "/api/model", "params": []},
        {"method": "GET", "path": "/api/ml", "params": ["ticker", "horizon", "candidates"]},
        {"method": "GET", "path": "/api/news", "params": ["ticker"]},
        {"method": "GET", "path": "/api/news/market", "params": []},
        {"method": "GET", "path": "/api/external", "params": ["ticker"]},
        {"method": "GET", "path": "/api/fundamental", "params": ["ticker"]},
        {"method": "GET", "path": "/api/market", "params": ["list", "refresh"]},
        {"method": "GET", "path": "/api/sector-strength", "params": ["list"]},
        {"method": "GET", "path": "/api/correlation", "params": ["tickers"]},
        {"method": "POST", "path": "/api/portfolio-risk", "params": ["positions", "capital"]},
        {"method": "GET", "path": "/api/musyawarah", "params": ["ticker", "llm"]},
        {"method": "GET", "path": "/api/paper", "params": []},
        {"method": "POST", "path": "/api/paper/open", "params": ["ticker", "entry", "lots", "stop", "tp"]},
        {"method": "POST", "path": "/api/paper/close", "params": ["id", "exit"]},
        {"method": "POST", "path": "/api/paper/purge", "params": ["id", "reason"]},
        {"method": "GET", "path": "/api/data/quality", "params": ["list"]},
        {"method": "GET", "path": "/api/seasonality", "params": ["ticker"]},
        {"method": "GET", "path": "/health", "params": []},
        {"method": "GET", "path": "/api/metrics", "params": []},
    ])

