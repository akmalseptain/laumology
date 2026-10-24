"""LAUMOLOGY web server (Flask).

Entry point tipis: pembuatan app, hook lintas-request (rate-limit, metrik,
error JSON), registrasi blueprint di `routes/`, dan worker scheduler opsional.
Semua endpoint ada di paket `routes/`.
"""
from __future__ import annotations

import argparse
import datetime
import logging
import os
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request


def _load_dotenv(path: str = ".env") -> None:
    try:
        p = Path(path)
        if not p.exists():
            return
        for raw in p.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except Exception:
        pass


# Muat .env SEBELUM mengimpor modul yang membaca config/env saat impor
# (mis. `config.py` via `state`/`routes`), agar override `LAUM_*` dari .env berlaku.
_load_dotenv()

import state  # noqa: E402
import store  # noqa: E402
from routes import register as register_routes  # noqa: E402
from routes.meta import _public_base  # noqa: E402

_log = logging.getLogger("laumology.webapp")

app = Flask(__name__)
store.init()
register_routes(app)


_api_key_warned = False


@app.before_request
def _guard():
    global _api_key_warned
    if not _api_key_warned and not state.api_key():
        _log.warning(
            "API_KEY tidak diset: endpoint tulis %s TIDAK dilindungi. "
            "Set API_KEY dan kirim header X-API-Key sebelum mengekspos layanan publik.",
            sorted(state.PROTECTED),
        )
        _api_key_warned = True
    if request.path.startswith("/api"):
        ip = request.remote_addr or "?"
        if state.rate_limited(ip):
            return jsonify(error="Rate limit terlampaui"), 429
    if state.api_key() and request.method == "POST" and request.path in state.PROTECTED:
        if request.headers.get("X-API-Key") != state.api_key():
            return jsonify(error="Unauthorized"), 401
    return None


# Allowlist CSP: script hanya 'self' (tidak ada inline script/handler),
# style perlu 'unsafe-inline' karena template memakai atribut style= dan
# menyuntik style via innerHTML; font hanya dari Google Fonts.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "worker-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


@app.after_request
def _track(resp):
    state.tick_metrics(request.path, resp.status_code)
    # nosniff + Referrer-Policy untuk SEMUA respons (termasuk /static/*) agar
    # aset statis (vendor JS) tidak di-MIME-sniff.
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not request.path.startswith("/static/"):
        if request.path in ("/robots.txt", "/sitemap.xml"):
            # Primitif crawl mesin pencari. Base kanonik divalidasi ketat dan
            # tidak pernah memantulkan header ``Host``. Bila base tak
            # dikonfigurasi/valid, isi respons memakai lokasi relatif →
            # jangan cache di cache bersama (fail-closed anti cache poisoning).
            if _public_base():
                resp.headers["Cache-Control"] = "public, max-age=3600"
            else:
                resp.headers["Cache-Control"] = "no-store"
            # Sabuk pengaman: bila kelak ada varian per-Host, cache bersama
            # tak menyilangkan respons antar Host.
            resp.headers.setdefault("Vary", "Host")
        else:
            resp.headers["Cache-Control"] = "no-store"
    else:
        # OPTIMASI: aset /static/* identik lintas-Host dan tak memantulkan
        # input klien — aman di-cache browser & cache bersama; menghindari
        # revalidasi tiap-request (default Flask: no-cache).
        resp.headers["Cache-Control"] = "public, max-age=3600"
    # Header pembatas framing/CSP HANYA untuk dokumen HTML; deteksi lewat
    # content-type (bukan path) agar JSON/SSE (/api/screen/stream) tak rusak.
    ctype = resp.content_type or ""
    if ctype.startswith("text/html"):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Content-Security-Policy", _CSP)
        resp.headers.setdefault(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
        )
    # HSTS hanya bila TLS di-terminate proxy dan proto benar-benar https
    # (jangan dipaksa di dev HTTP).
    if request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        resp.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return resp


@app.errorhandler(Exception)
def _json_errors(e):
    """Pastikan semua error di /api/* SELALU dibalas JSON (bukan HTML)."""
    from werkzeug.exceptions import HTTPException
    code = e.code if isinstance(e, HTTPException) else 500
    if request.path.startswith("/api/"):
        return jsonify(error=str(e) or "error", code=code), code
    if isinstance(e, HTTPException):
        return e
    return "Internal Server Error", 500


def _env_int(name: str, default: int) -> int:
    """Baca ``int`` dari environment dengan aman.

    Nilai absen, kosong, atau bukan angka diabaikan dan ``default``
    dipertahankan (dengan satu warning). ``_maybe_start_scheduler`` dipanggil
    saat impor modul, jadi kesalahan konfigurasi TIDAK boleh menggagalkan boot
    WSGI (``webapp:app``); selaras dengan penanganan env di ``config.py``/
    ``state.py``.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        _log.warning(
            "Nilai env %s=%r tidak valid (int); memakai default %d.",
            name, raw, default,
        )
        return default


# Batas ukuran body request (byte). Melindungi instance ber-RAM kecil dari
# POST besar (OOM/DoS) tanpa perlu modul tambahan; Flask membalas 413 otomatis.
_BODY_BYTES_DEFAULT = 1 * 1024 * 1024  # 1 MB
_BODY_BYTES_MIN = 64 * 1024            # 64 KB
_BODY_BYTES_MAX = 8 * 1024 * 1024      # 8 MB


def _max_body_bytes() -> int:
    """Batas ``MAX_CONTENT_LENGTH`` dari env ``LAUM_MAX_BODY_BYTES``.

    Nilai di-parse int ketat (``_env_int``) lalu di-clamp ke rentang
    ``[_BODY_BYTES_MIN, _BODY_BYTES_MAX]``. Nilai ``<= 0`` (termasuk ``0``)
    atau tak valid dikembalikan ke default 1 MB agar konfigurasi salah tak
    melumpuhkan SEMUA POST (self-DoS).
    """
    n = _env_int("LAUM_MAX_BODY_BYTES", _BODY_BYTES_DEFAULT)
    if n <= 0:
        return _BODY_BYTES_DEFAULT
    if n < _BODY_BYTES_MIN:
        return _BODY_BYTES_MIN
    if n > _BODY_BYTES_MAX:
        return _BODY_BYTES_MAX
    return n


# Dipasang setelah `_env_int` didefinisikan (bukan di baris `app = Flask(...)`)
# agar impor WSGI `webapp:app` tidak melempar NameError.
app.config["MAX_CONTENT_LENGTH"] = _max_body_bytes()


_TRUSTED_PROXY_HOPS_MAX = 5


def _trusted_proxy_hops() -> int:
    """Jumlah hop proxy tepercaya dari env ``TRUSTED_PROXY_HOPS``.

    Nilai di-parse int ketat (pakai ``_env_int``) lalu di-clamp ke rentang
    ``[0, _TRUSTED_PROXY_HOPS_MAX]``. Negatif = 0 (nonaktif); terlalu besar
    dibatasi agar konfigurasi salah tak membuka celah spoof X-Forwarded-For.
    """
    n = _env_int("TRUSTED_PROXY_HOPS", 0)
    if n <= 0:
        return 0
    if n > _TRUSTED_PROXY_HOPS_MAX:
        _log.warning(
            "TRUSTED_PROXY_HOPS=%d melebihi batas aman %d; memakai %d.",
            n, _TRUSTED_PROXY_HOPS_MAX, _TRUSTED_PROXY_HOPS_MAX,
        )
        return _TRUSTED_PROXY_HOPS_MAX
    return n


def _apply_proxy_fix(wsgi_app, hops: int):
    """Bungkus ``wsgi_app`` dengan ``ProxyFix`` bila ``hops > 0``.

    Hanya ``x_for`` yang dipercaya (bukan ``x_proto``/``x_host``) supaya
    deteksi HSTS manual di ``_track`` tetap utuh. ``hops == 0`` mengembalikan
    app apa adanya (perilaku lama, tanpa regresi).
    """
    if hops <= 0:
        return wsgi_app
    from werkzeug.middleware.proxy_fix import ProxyFix

    return ProxyFix(wsgi_app, x_for=hops)


# Dipasang di level modul (setelah `app = Flask(...)`) agar gunicorn
# `webapp:app` (Render) benar-benar kena -- bukan di `main()`.
app.wsgi_app = _apply_proxy_fix(app.wsgi_app, _trusted_proxy_hops())


_WIB_OFFSET = datetime.timedelta(hours=7)  # UTC+7 (WIB)


def in_market_window(now_utc: datetime.datetime, window: str = "market") -> bool:
    """Jendela aktif scheduler — murni/deterministik dari argumen (bisa dites).

    Mode 'market' (default): Senin–Jumat 08:45–16:20 WIB inklusif; Sabtu/Minggu
    idle. Mode '24h'/'all'/'always': selalu aktif. Kesalahan internal
    dianggap AKTIF (fail-open, jangan mematikan scan diam-diam) — perilaku
    sama dengan implementasi lama di dalam loop.
    """
    if str(window or "").lower() in ("24h", "all", "always"):
        return True
    try:
        now = now_utc + _WIB_OFFSET
        if now.weekday() >= 5:  # Sabtu/Minggu
            return False
        minutes = now.hour * 60 + now.minute
        return (8 * 60 + 45) <= minutes <= (16 * 60 + 20)
    except Exception:
        return True


def _maybe_start_scheduler() -> None:
    """Jalankan auto-scanner in-process (untuk Render/VPS). Aktifkan via ENABLE_SCHEDULER=1.

    Aman untuk boot: ada jeda awal, single-flight, dan (default) hanya saat jam bursa.
    """
    if os.environ.get("ENABLE_SCHEDULER") not in ("1", "true", "yes"):
        return
    try:
        import scheduler as sched_mod
    except Exception:
        return
    import datetime as _dt

    interval = max(120, _env_int("SCAN_INTERVAL", 900))
    universe = os.environ.get("SCAN_UNIVERSE", "lq45")
    window = os.environ.get("SCAN_WINDOW", "market").lower()
    start_delay = max(0, _env_int("SCAN_START_DELAY", 90))
    warm_universe = os.environ.get("WARM_UNIVERSE", "auto")
    warm_interval = max(600, _env_int("WARM_INTERVAL", 1800))

    def _in_window() -> bool:
        return in_market_window(_dt.datetime.now(_dt.timezone.utc), window)

    def loop() -> None:
        time.sleep(start_delay)  # beri waktu server siap sebelum kerja berat
        try:
            store.init()
        except Exception:
            pass
        running = False
        last_warm = 0.0
        while True:
            now = time.time()
            if _in_window() and (now - last_warm) >= warm_interval:
                last_warm = now
                try:
                    if warm_universe:
                        sched_mod.warm(warm_universe)
                except Exception:
                    pass
            if _in_window() and not running:
                running = True
                try:
                    sched_mod.run_once(universe)
                except Exception:
                    pass
                running = False
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="laumology-scanner").start()

    # Paper trading otomatis (batch-35): loop 24 jam TANPA jendela bursa.
    # Aman kapan pun karena sync hanya MEMBACA sinyal/OHLC dan menulis tabel
    # paper - tidak menulis sinyal (beda dengan scan). Tujuan: track record
    # paper selalu mutakhir; posisi ditutup begitu bar terbaru menunjukkan
    # TP/SL tersentuh, termasuk setelah jam bursa dan di akhir pekan.
    paper_interval = max(300, _env_int("PAPER_SYNC_INTERVAL", 1800))

    def paper_loop() -> None:
        time.sleep(start_delay)
        try:
            store.init()
        except Exception:
            pass
        while True:
            try:
                import paper_auto
                paper_auto.sync_paper()
            except Exception:
                pass
            time.sleep(paper_interval)

    threading.Thread(target=paper_loop, daemon=True, name="laumology-paper").start()


_maybe_start_scheduler()


def _lan_ips() -> list[str]:
    import socket
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" not in ip and not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def main() -> None:
    parser = argparse.ArgumentParser(description="LAUMOLOGY IDX Trading Terminal (web)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser and args.host not in ("0.0.0.0", "::"):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"LAUMOLOGY jalan di {url}")
    if args.host in ("0.0.0.0", "::"):
        for ip in _lan_ips():
            print(f"  -> dari HP (WiFi sama): http://{ip}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
