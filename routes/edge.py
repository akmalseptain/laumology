"""Endpoint JSON ringkas uji edge indikator (server-side, tanpa proyeksi).

Sumber kebenaran: `indicator_edge.evaluate` (event study kausal, event a priori).
Endpoint ini HANYA meringkas hasil — tidak menambah proyeksi, tidak menyetel
threshold, dan tidak menyentuh skor 0-100. Hasil di-cache singkat karena
evaluasi satu universe berat (fetch OHLCV banyak emiten).
"""
from __future__ import annotations

import time

from flask import Blueprint, jsonify, request

import indicator_edge

bp = Blueprint("edge", __name__)

# Cache sederhana dalam proses: evaluasi universe bisa belasan detik.
_CACHE: dict = {"key": None, "ts": 0.0, "payload": None}
_CACHE_TTL_SECONDS = 900.0  # 15 menit


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    return min(max(int(raw), lo), hi)


@bp.get("/api/edge")
def api_edge():
    """Ringkas top event edge dari `indicator_edge.evaluate` (tanpa proyeksi)."""
    universe = (request.args.get("universe") or "lq45").strip().lower()
    try:
        horizon = _int_arg("horizon", 5, 1, 60)
        top = _int_arg("top", 10, 1, 50)
        min_count = _int_arg("min_count", 30, 10, 500)
    except ValueError:
        return jsonify({"error": "Parameter tidak valid: horizon/top/min_count harus berupa angka."}), 400

    key = (universe, horizon, min_count)
    now = time.time()
    if _CACHE["key"] == key and _CACHE["payload"] is not None and now - _CACHE["ts"] < _CACHE_TTL_SECONDS:
        return jsonify(_CACHE["payload"])

    try:
        rep = indicator_edge.evaluate(universe, horizon, min_count)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Gagal mengevaluasi edge: {exc}"}), 502

    payload = {
        "generated": rep["generated"],
        "universe": rep["universe"],
        "horizon_days": rep["horizon_days"],
        "warmup_bars": rep["warmup_bars"],
        "min_count": rep["min_count"],
        "tickers_evaluated": rep["tickers_evaluated"],
        "tickers_total": rep["tickers_total"],
        "baseline_hit": rep["baseline_hit"],
        "baseline_med_ret": rep["baseline_med_ret"],
        "top_events": rep["ranking"][:top],
        "skipped_low_sample": rep["skipped_low_sample"],
        "catatan": rep["catatan"],
    }
    _CACHE["key"] = key
    _CACHE["ts"] = now
    _CACHE["payload"] = payload
    return jsonify(payload)
