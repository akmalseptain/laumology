"""Pos X dari akun resmi, untuk konteks pasar. Bukan harga dan bukan broker summary.

Memakai X Search di API xAI (``XAI_API_KEY``). Tanpa kunci, fungsi mengembalikan
kosong dan analisis lain tetap jalan. Hanya akun yang diizinkan yang lolos.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from datetime import date, timedelta

# Akun lembaga. Bukan akun rumor atau sekuritas.
ALLOWED_HANDLES = ("idx_bei", "bank_indonesia", "kemenkeuri", "ojkindonesia")

_API = "https://api.x.ai/v1/responses"
_MODEL = "grok-4.7"
_TTL = 1800.0
_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "items": None, "ok": None}

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{2,20}$")


def configured() -> bool:
    return bool((os.environ.get("XAI_API_KEY") or "").strip())


def _output_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts)


def parse_posts(text: str) -> list[dict]:
    """Ambil hanya pos yang handle-nya diizinkan dan URL-nya di X."""
    raw = text or ""
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        rows = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    allowed = {name.lower() for name in ALLOWED_HANDLES}
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        handle = str(row.get("handle") or "").strip().lstrip("@").lower()
        body = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        url = str(row.get("url") or "").strip()
        if handle not in allowed or not _HANDLE_RE.fullmatch(handle):
            continue
        if not body or len(body) < 12:
            continue
        if not (url.startswith("https://x.com/") or url.startswith("https://twitter.com/")):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append({
            "title": f"@{handle}: {body[:180]}",
            "summary": None,
            "url": url,
            "source": "x",
        })
        if len(out) >= 8:
            break
    return out


def _request() -> str:
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("XAI_API_KEY kosong")
    start = date.today() - timedelta(days=2)
    end = date.today() + timedelta(days=1)
    handles = ", ".join("@" + name for name in ALLOWED_HANDLES)
    prompt = (
        "Cari pos X terbaru hanya dari akun "
        + handles
        + " tentang IHSG, MSCI, FTSE, rupiah, investor asing, atau suku bunga. "
        "Balas HANYA JSON array. Tiap elemen: "
        '{"handle":"idx_bei","text":"teks pos","url":"https://x.com/..."}. '
        "Jangan mengarang pos. Jika tidak ada, balas []."
    )
    body = json.dumps({
        "model": _MODEL,
        "input": prompt,
        "max_turns": 2,
        "tools": [{
            "type": "x_search",
            "allowed_x_handles": list(ALLOWED_HANDLES),
            "from_date": start.isoformat(),
            "to_date": end.isoformat(),
        }],
    }).encode("utf-8")
    req = urllib.request.Request(
        _API,
        data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.loads(resp.read(1_000_000).decode("utf-8", "replace"))
    if not isinstance(payload, dict):
        return ""
    return _output_text(payload)


def headlines() -> tuple[list[dict], bool]:
    """``(pos, sumber_hidup)``. Tanpa kunci: ``([], False)`` tanpa jaringan."""
    if not configured():
        return [], False
    now = time.time()
    with _lock:
        if _cache["items"] is not None and now - float(_cache["ts"]) < _TTL:
            return list(_cache["items"]), bool(_cache["ok"])
    try:
        items = parse_posts(_request())
        ok = True
    except Exception:
        items, ok = [], False
    with _lock:
        _cache["ts"] = time.time()
        _cache["items"] = items
        _cache["ok"] = ok
    return list(items), ok
