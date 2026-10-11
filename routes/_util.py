"""Utilitas kecil untuk blueprint route."""
from __future__ import annotations

from flask import request


def json_object() -> dict | None:
    """Body JSON sebagai dict.

    - Body absen/kosong -> ``{}`` (perilaku lama dipertahankan).
    - Body yang bukan objek (array/string/angka) -> ``None`` agar pemanggil
      dapat membalas 400 (bukan 500 akibat ``.get`` pada non-dict).
    """
    body = request.get_json(silent=True)
    if body is None:
        return {}
    return body if isinstance(body, dict) else None
