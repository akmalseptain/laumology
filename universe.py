from __future__ import annotations

import json
import time
import urllib.request

from config import IDX_LIQUID

_SCAN_URL = "https://scanner.tradingview.com/indonesia/scan"
_cache: dict = {"t": 0.0, "data": []}
_TTL = 1800.0  # 30 menit


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
    except Exception:
        pass
    return IDX_LIQUID[:limit]
