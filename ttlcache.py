"""TTL cache in-memory sederhana (thread-safe) untuk endpoint komputasi berat.

Additive: tidak mengubah logic apa pun. Hanya menyimpan hasil yang deterministik
untuk jangka waktu singkat agar request berulang tidak menghitung ulang.
"""
from __future__ import annotations

import threading
import time

_store: dict = {}
_lock = threading.Lock()


def get(key: str):
    now = time.time()
    with _lock:
        e = _store.get(key)
        if not e:
            return None
        ts, val, ttl = e
        if now - ts < ttl:
            return val
        _store.pop(key, None)
    return None


def set(key: str, val, ttl: float) -> None:
    with _lock:
        _store[key] = (time.time(), val, ttl)
        if len(_store) > 400:
            now = time.time()
            for k in [k for k, (ts, _v, tt) in list(_store.items()) if now - ts >= tt]:
                _store.pop(k, None)


def memo(key: str, ttl: float, fn):
    """Kembalikan (value, hit). Hit=True bila dari cache."""
    v = get(key)
    if v is not None:
        return v, True
    v = fn()
    set(key, v, ttl)
    return v, False


def clear() -> None:
    with _lock:
        _store.clear()


def stats() -> dict:
    with _lock:
        return {"size": len(_store), "keys": list(_store.keys())}
