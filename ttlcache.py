"""TTL cache in-memory sederhana (thread-safe) untuk endpoint komputasi berat.

Additive: tidak mengubah logic apa pun. Hanya menyimpan hasil yang deterministik
untuk jangka waktu singkat agar request berulang tidak menghitung ulang.
"""
from __future__ import annotations

import threading
import time

_store: dict = {}
_lock = threading.Lock()

# Batas keras jumlah entri. Sebagian key dibentuk dari input pengguna
# (mis. `?list=`/`?horizon=`), jadi tanpa batas ini cache bisa tumbuh tak
# terbatas selama entri masih segar (belum kedaluwarsa).
_MAX_ENTRIES = 400


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
    now = time.time()
    with _lock:
        _store[key] = (now, val, ttl)
        if len(_store) > _MAX_ENTRIES:
            # 1) buang entri yang sudah kedaluwarsa.
            for k in [k for k, (ts, _v, tt) in list(_store.items()) if now - ts >= tt]:
                _store.pop(k, None)
            # 2) batas keras: bila masih melebihi, buang yang paling lama.
            #    Eviksi hanya memicu hitung ulang (bukan hasil salah); nilai
            #    yang tersimpan tetap deterministik dari key-nya.
            excess = len(_store) - _MAX_ENTRIES
            if excess > 0:
                oldest = sorted(_store.items(), key=lambda kv: kv[1][0])[:excess]
                for k, _ in oldest:
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
