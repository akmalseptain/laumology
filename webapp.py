"""LAUMOLOGY web server (Flask).

Entry point tipis: pembuatan app, hook lintas-request (rate-limit, metrik,
error JSON), registrasi blueprint di `routes/`, dan worker scheduler opsional.
Semua endpoint ada di paket `routes/`.
"""
from __future__ import annotations

import argparse
import logging
import os
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request

import state
import store
from routes import register as register_routes

_log = logging.getLogger("laumology.webapp")

app = Flask(__name__)
store.init()
register_routes(app)


def _load_dotenv(path: str = ".env") -> None:
    try:
        p = Path(path)
        if not p.exists():
            return
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except Exception:
        pass


_load_dotenv()

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


@app.after_request
def _track(resp):
    state.tick_metrics(request.path, resp.status_code)
    if not request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
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

    interval = max(120, int(os.environ.get("SCAN_INTERVAL", "900")))
    universe = os.environ.get("SCAN_UNIVERSE", "lq45")
    window = os.environ.get("SCAN_WINDOW", "market").lower()
    start_delay = int(os.environ.get("SCAN_START_DELAY", "90"))
    warm_universe = os.environ.get("WARM_UNIVERSE", "auto")
    warm_interval = max(600, int(os.environ.get("WARM_INTERVAL", "1800")))

    def _in_window() -> bool:
        if window in ("24h", "all", "always"):
            return True
        try:
            now = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=7)  # WIB
            if now.weekday() >= 5:  # Sabtu/Minggu
                return False
            minutes = now.hour * 60 + now.minute
            return (8 * 60 + 45) <= minutes <= (16 * 60 + 20)
        except Exception:
            return True

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
