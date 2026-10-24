from __future__ import annotations

import json
import logging
import time
import urllib.request

from config import IDX_LIQUID

_log = logging.getLogger("laumology.universe")

_SCAN_URL = "https://scanner.tradingview.com/indonesia/scan"
_cache: dict = {"t": 0.0, "data": []}
_full: dict = {"t": 0.0, "data": []}
_TTL = 1800.0  # 30 menit
_TTL_FULL = 21600.0  # 6 jam


def _tv_query(limit: int) -> list[str]:
    payload = {
        "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
        "options": {"lang": "en"},
        "columns": ["name", "close", "Value.Traded"],
        "sort": {"sortBy": "Value.Traded", "sortOrder": "desc"},
        "range": [0, limit],
    }
    req = urllib.request.Request(
        _SCAN_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8", "ignore"))
    out: list[str] = []
    for row in data.get("data", []):
        sym = str(row.get("s", ""))
        if ":" in sym:
            t = sym.split(":", 1)[1].strip().upper()
            if t and t not in out:
                out.append(t)
    return out


def auto_universe(limit: int = 150) -> list[str]:
    """Daftar saham IDX paling likuid (dynamic). Fallback ke daftar statis."""
    now = time.time()
    if _cache["data"] and now - _cache["t"] < _TTL and len(_cache["data"]) >= limit:
        return _cache["data"][:limit]
    try:
        data = _tv_query(max(limit, 250))
        if data:
            _cache["t"] = now
            _cache["data"] = data
            return data[:limit]
        _log.warning("respons TradingView kosong - universe auto fallback statis (limit %d)", limit)
    except Exception:
        # Universe berganti dari dinamis ke statis - cakupan scan berubah.
        # Fallback tetap jalan (best-effort), tapi TIDAK boleh senyap.
        _log.warning("query TradingView gagal - universe auto fallback statis (limit %d)", limit, exc_info=True)
    return IDX_LIQUID[:limit]


def full_universe(limit: int = 1000) -> list[str]:
    """Seluruh emiten saham IDX (dynamic). Fallback ke daftar statis."""
    now = time.time()
    if _full["data"] and now - _full["t"] < _TTL_FULL and len(_full["data"]) >= limit:
        return _full["data"][:limit]
    try:
        data = _tv_query(limit)
        if len(data) > 300:
            _full["t"] = now
            _full["data"] = data
            return data[:limit]
        _log.warning("respons TradingView terlalu sedikit (%d baris) - universe penuh fallback statis", len(data))
    except Exception:
        # Cakupan "seluruh emiten" menyusut ke daftar statis tanpa jejak =
        # hasil scan tidak bisa dibandingkan antar hari bila senyap.
        _log.warning("query TradingView gagal - universe penuh fallback statis (limit %d)", limit, exc_info=True)
    return IDX_LIQUID[:limit]
