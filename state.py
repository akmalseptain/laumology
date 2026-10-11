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
from collections import OrderedDict

_log = logging.getLogger("laumology.state")

VERSION = "1.0.0"
START = time.time()

PROTECTED = {"/api/paper/open", "/api/paper/close", "/api/notify"}


def api_key() -> str:
    """Dibaca dinamis agar .env yang dimuat setelah impor tetap terbaca."""
    return os.environ.get("API_KEY", "")

HISTORY_MAX = 300
SCAN_JOBS_MAX = 6
# TTL job scan non-terminal (detik). Job yang nyangkut di `queued`/`running`
# (mis. `screener.screen` menggantung di I/O) TIDAK pernah jadi terminal, jadi
# bila hanya job terminal yang dibuang, kuota `SCAN_JOBS_MAX` akan penuh
# permanen dan SEMUA scan baru ditolak -> self-DoS sampai proses di-restart.
# Job yang lebih tua dari TTL ini dianggap mati dan boleh dieviksi.
SCAN_JOB_TTL = 600

_history: list[dict] = []
_history_lock = threading.Lock()

_metrics = {"requests": 0, "errors": 0, "by_path": {}}
_metrics_lock = threading.Lock()
# Batas keras jumlah path yang dilacak. `after_request` mencatat SEMUA path
# (termasuk non-/api), jadi path acak dari klien bisa menumbuhkan dict ini
# tanpa batas -> kebocoran memori pada proses panjang. Eviksi FIFO (dict
# mempertahankan urutan sisip) cukup: metrik ini hanya penghitung, path lama
# boleh hilang tanpa memengaruhi angka total `requests`/`errors`.
_METRICS_PATH_MAX = 512

_rl: OrderedDict[str, list[float]] = OrderedDict()
_rl_lock = threading.Lock()
# Batas keras jumlah IP yang dilacak. `rate_limited` dipanggil per request di
# `before_request`; tiap IP unik membuat satu entri via `setdefault`, tapi
# prune di bawah hanya menyentuh window IP yang kembali. IP yang sekali lewat
# lalu tak kembali akan menumpuk permanen -> kebocoran memori.
#
# Eviksi memakai LRU O(1)-amortized: `_rl` adalah `OrderedDict`; tiap akses
# memindahkan IP ke ujung via `move_to_end`, lalu kelebihan dibuang dari depan
# (`popitem(last=False)`). Jadi yang terbuang adalah IP paling lama TIDAK
# diakses -- bukan IP yang masih aktif. Penting: IP yang sedang membanjiri
# (bahkan yang sudah kena limit) tetap di-`move_to_end`, agar penyerang tak
# bisa me-reset window-nya sendiri dengan membanjiri IP unik.
#
# Catatan asal IP: `webapp.py` memakai `request.remote_addr` TANPA `ProxyFix`.
# Di belakang load balancer (mis. Render) ini bisa mengerucut ke satu IP
# proxy -- leak jadi moot, tetapi rate-limit menjadi terbagi global. Itu
# lubang lama di luar scope perubahan ini; didokumentasikan agar tidak
# disalahartikan sebagai perbaikan.
_RL_MAX_IPS = 4096

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
        by_path = _metrics["by_path"]
        by_path[path] = by_path.get(path, 0) + 1
        if len(by_path) > _METRICS_PATH_MAX:
            # Urutan sisip dict stabil, jadi elemen awal = path terlama.
            for stale in list(by_path)[: len(by_path) - _METRICS_PATH_MAX]:
                by_path.pop(stale, None)


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
        # Tandai IP ini baru diakses (LRU); tetap dilakukan walau limit
        # terlampaui agar IP yang aktif tak digantikan saat eviksi.
        _rl.move_to_end(ip)
        win[:] = [t for t in win if now - t < 60]
        if len(win) >= limit:
            return True
        win.append(now)
        if len(_rl) > _RL_MAX_IPS:
            # Batas keras LRU: buang IP paling lama tak diakses dari depan.
            # `popitem` O(1), jadi biaya = O(excess); `excess` ~0-1/request.
            # Cabang non-positif mencegah `popitem` atas dict kosong (KeyError)
            # bila `_RL_MAX_IPS` di-set 0/negatif lewat konfigurasi/test.
            if _RL_MAX_IPS >= 1:
                while len(_rl) > _RL_MAX_IPS:
                    _rl.popitem(last=False)
            else:
                _rl.clear()
    return False


# --- Background scan jobs ---
def create_scan_job(params: dict) -> str | None:
    """Daftarkan job scan baru; ``None`` bila kuota penuh (pemanggil tak boleh
    memarkir thread baru).

    Eviksi dua tahap: (1) job terminal (``done``/``error``/``cancelled``)
    selalu dibuang TANPA grace; (2) job non-terminal yang lebih tua dari
    ``SCAN_JOB_TTL`` TIDAK dibuang, melainkan ditandai terminal
    (``state="error"``, ``error="kedaluwarsa"``, ``cancel=True``) agar worker
    berhenti lewat ``scan_cancelled`` dan polling berhenti di status terminal,
    bukan 404. Kuota dihitung hanya dari job non-terminal, sehingga entri
    terminal yang menunggu dibaca tak menghalangi scan baru. Bila setelah
    eviksi kuota ``SCAN_JOBS_MAX`` masih penuh, kembalikan ``None`` dan
    jangan sisipkan entri baru.
    """
    now = time.time()
    jid = uuid.uuid4().hex[:12]
    terminal_states = ("done", "error", "cancelled")
    with _scan_lock:
        for k in list(_scan_jobs):
            v = _scan_jobs[k]
            if v.get("state") in terminal_states:
                _scan_jobs.pop(k, None)
                continue
            expired = (SCAN_JOB_TTL > 0
                       and now - float(v.get("created") or now) > SCAN_JOB_TTL)
            if expired:
                v["state"] = "error"
                v["error"] = "kedaluwarsa"
                v["cancel"] = True
        active = sum(1 for v in _scan_jobs.values()
                     if v.get("state") not in terminal_states)
        if active >= SCAN_JOBS_MAX:
            return None
        _scan_jobs[jid] = {
            "state": "queued", "scanned": 0, "total": 0, "rows": [],
            "created": now, "cancel": False, "error": None,
        }
    return jid


def update_scan_job(jid: str, **fields) -> None:
    terminal_states = ("done", "error", "cancelled")
    with _scan_lock:
        cur = _scan_jobs.get(jid)
        if cur is None:
            return
        if cur.get("state") in terminal_states:
            return
        cur.update(fields)


def get_scan_job(jid: str) -> dict | None:
    terminal_states = ("done", "error", "cancelled")
    with _scan_lock:
        for k in list(_scan_jobs):
            if k == jid:
                continue
            if _scan_jobs[k].get("state") in terminal_states:
                _scan_jobs.pop(k, None)
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
