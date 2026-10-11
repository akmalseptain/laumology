"""Shared runtime state & registries untuk webapp.

Dipisah dari `webapp.py` agar bisa dipakai oleh blueprint tanpa impor melingkar:
riwayat sinyal, metrik request, rate-limit, dan job scan latar.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid

_log = logging.getLogger("laumology.state")

VERSION = "1.0.0"
START = time.time()

PROTECTED = {"/api/paper/open", "/api/paper/close", "/api/notify"}


def api_key() -> str:
    """Dibaca dinamis agar .env yang dimuat setelah impor tetap terbaca."""
    return os.environ.get("API_KEY", "")

HISTORY_MAX = 300
SCAN_JOBS_MAX = 6

_history: list[dict] = []
_history_lock = threading.Lock()

_metrics = {"requests": 0, "errors": 0, "by_path": {}}
_metrics_lock = threading.Lock()

_rl: dict[str, list[float]] = {}
_rl_lock = threading.Lock()

_scan_jobs: dict[str, dict] = {}
_scan_lock = threading.Lock()


# --- Signal history ---
def record_history(payload: dict) -> None:
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ticker": payload.get("ticker"),
        "signal": payload.get("signal"),
        "action": payload.get("action"),
        "score": payload.get("score"),
        "confidence": payload.get("confidence"),
        "grade": payload.get("grade"),
        "price": payload.get("price"),
        "entry": payload.get("entry"),
        "stop_loss": payload.get("stop_loss"),
        "tp1": payload.get("tp1"),
    }
    with _history_lock:
        _history.append(entry)
        if len(_history) > HISTORY_MAX:
            del _history[: len(_history) - HISTORY_MAX]


def recent_history(limit: int | None = None) -> list[dict]:
    with _history_lock:
        items = list(reversed(_history))
    if limit:
        items = items[: max(1, limit)]
    return items


# --- Metrics ---
def tick_metrics(path: str, status: int) -> None:
    with _metrics_lock:
        _metrics["requests"] += 1
        if status >= 400:
            _metrics["errors"] += 1
        _metrics["by_path"][path] = _metrics["by_path"].get(path, 0) + 1


def metrics_snapshot() -> dict:
    with _metrics_lock:
        return {
            "uptime_s": int(time.time() - START),
            "requests": _metrics["requests"],
            "errors": _metrics["errors"],
            "by_path": dict(_metrics["by_path"]),
        }


# --- Rate limiting ---
_RATE_LIMIT_DEFAULT = 600  # dipakai bila env absen/blank/tidak valid/non-positif
_rate_limit_warned = False


def _rate_limit_per_min() -> int:
    """Baca ``RATE_LIMIT_PER_MIN`` dengan aman.

    Kesalahan konfigurasi (nilai blank, bukan angka, atau <= 0) TIDAK boleh
    melumpuhkan endpoint /api: nilai buruk diabaikan dan kembali ke default,
    dengan satu warning. Ini mencegah satu env var salah memicu HTTP 500 pada
    *setiap* request (``rate_limited`` dipanggil di ``before_request``).
    """
    global _rate_limit_warned
    raw = os.environ.get("RATE_LIMIT_PER_MIN")
    if raw is None or not raw.strip():
        return _RATE_LIMIT_DEFAULT
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        if not _rate_limit_warned:
            _log.warning(
                "Nilai env RATE_LIMIT_PER_MIN=%r tidak valid; memakai default %d.",
                raw, _RATE_LIMIT_DEFAULT,
            )
            _rate_limit_warned = True
        return _RATE_LIMIT_DEFAULT
    return limit


def rate_limited(ip: str) -> bool:
    limit = _rate_limit_per_min()
    now = time.time()
    with _rl_lock:
        win = _rl.setdefault(ip, [])
        win[:] = [t for t in win if now - t < 60]
        if len(win) >= limit:
            return True
        win.append(now)
    return False


# --- Background scan jobs ---
def create_scan_job(params: dict) -> str:
    jid = uuid.uuid4().hex[:12]
    with _scan_lock:
        done = [k for k, v in _scan_jobs.items()
                if v.get("state") in ("done", "error", "cancelled")]
        while len(_scan_jobs) >= SCAN_JOBS_MAX and done:
            _scan_jobs.pop(done.pop(0), None)
        _scan_jobs[jid] = {
            "state": "queued", "scanned": 0, "total": 0, "rows": [],
            "created": time.time(), "cancel": False, "error": None,
        }
    return jid


def update_scan_job(jid: str, **fields) -> None:
    with _scan_lock:
        if jid in _scan_jobs:
            _scan_jobs[jid].update(fields)


def get_scan_job(jid: str) -> dict | None:
    with _scan_lock:
        j = _scan_jobs.get(jid)
        if not j:
            return None
        return dict(state=j.get("state"), scanned=j.get("scanned", 0),
                    total=j.get("total", 0), error=j.get("error"),
                    rows=list(j.get("rows") or []))


def scan_cancelled(jid: str) -> bool:
    with _scan_lock:
        return bool(_scan_jobs.get(jid, {}).get("cancel"))


def cancel_scan_job(jid: str) -> bool:
    with _scan_lock:
        if jid in _scan_jobs:
            _scan_jobs[jid]["cancel"] = True
            return True
    return False
