from __future__ import annotations

import os
import pickle
import time
from pathlib import Path

import pandas as pd

import data
import logging
from config import WATCHLIST_PRESETS, sector_of, settings
from signals import analyze
from universe import auto_universe, full_universe

_AUTO_KEYS = {"auto", "top", "most-active", "paling aktif", "palingaktif", "likuid", "liquid-auto"}
_ALL_KEYS = {"all", "allidx", "all-idx", "semua-emiten", "seluruh", "idx-all", "allidx2"}

# Cache baris hasil analisis (key ticker+bar) agar scan ulang instan (memori + disk).
_log = logging.getLogger("laumology.screener")

_ROW_CACHE: dict[str, tuple[float, dict]] = {}
_ROW_TTL = 900.0
_ROW_CACHE_MAX = 20000


def _cache_file() -> Path:
    return Path(settings.cache_dir) / "screen_rows.pkl"


def _load_cache() -> None:
    try:
        p = _cache_file()
        if not p.exists():
            return
        with open(p, "rb") as f:
            obj = pickle.load(f)
        if isinstance(obj, dict):
            _ROW_CACHE.update(obj)
    except Exception:
        pass


def _save_cache() -> None:
    try:
        p = _cache_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            pickle.dump(dict(_ROW_CACHE), f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass


_load_cache()


def resolve_watchlist(name: str) -> list[str]:
    key = name.lower().strip()
    if key in _AUTO_KEYS:
        return auto_universe(150)
    if key in _ALL_KEYS:
        return full_universe(1000)
    if key in WATCHLIST_PRESETS:
        return WATCHLIST_PRESETS[key]
    return [t.strip().upper() for t in name.split(",") if t.strip()]


def _rank(signal: str) -> int:
    return {
        "STRONG BUY": 5,
        "BUY": 4,
        "ACCUMULATE": 3,
        "HOLD": 2,
        "SELL": 1,
        "AVOID": 0,
    }.get(signal, 0)


def _row_from_df(t: str, df: pd.DataFrame) -> dict | None:
    res = analyze(df, t, light=True)
    row = res.as_row()
    try:
        turnover = (df["Close"] * df["Volume"]).tail(20).mean()
        row["Value"] = float(turnover) if pd.notna(turnover) else 0.0
    except Exception:
        # Nilai turnover 0.0 bisa menyingkirkan saham dari filter min_value -
        # degradasi hasil harus terlihat, bukan senyap.
        _log.warning("hitung Value (turnover) %s gagal - fallback 0.0", t, exc_info=True)
        row["Value"] = 0.0
    row["Sector"] = sector_of(t)
    return row


def _screen_one(payload: tuple) -> dict | None:
    """Worker (top-level, picklable) untuk ProcessPoolExecutor."""
    t, period, refresh = payload
    try:
        df = data.get_ohlcv(t, period=period, use_cache=not refresh)
        if len(df) < 80:
            return None
        return _row_from_df(t, df)
    except Exception:
        _log.warning("screen worker %s gagal - dilewati", t, exc_info=True)
        return None


def _plan_workers(n: int) -> int:
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        return 1
    if os.environ.get("RENDER") or os.environ.get("DYNO"):
        return 1
    configured = int(getattr(settings, "screen_workers", 0) or 0)
    if configured > 0:
        return max(1, min(configured, n))
    if n < 24:
        return 1
    return max(1, min(4, (os.cpu_count() or 1)))


def screen(
    tickers: list[str],
    period: str | None = None,
    min_score: int = 0,
    top: int | None = None,
    refresh: bool = False,
    min_confidence: int = 0,
    only_bullish: bool = False,
    sector: str | None = None,
    min_value: float = 0.0,
    decision: str | None = None,
) -> pd.DataFrame:
    if len(tickers) > 40 and not refresh:
        try:
            data.prefetch(tickers, period=period)
        except Exception:
            # best-effort (scan lanjut satu-per-satu), tapi TIDAK senyap.
            _log.warning("prefetch batch gagal saat screen - lanjut satu-per-satu", exc_info=True)

    now = time.time()
    rows: list[dict] = []
    todo: list[tuple] = []
    for t in tickers:
        key_suffix = None
        try:
            df = data.get_ohlcv(t, period=period, use_cache=not refresh)
            if len(df) < 80:
                continue
            key_suffix = f"{t}:{str(df.index[-1])[:10]}"
        except Exception:
            # Best-effort (ticker lain tetap dipindai), tapi TIDAK senyap:
            # ticker yang hilang dari hasil scan harus terlihat di log.
            _log.warning("ticker %s gagal difetch saat screen - dilewati", t, exc_info=True)
            continue
        cached = _ROW_CACHE.get(key_suffix) if key_suffix else None
        if cached and not refresh and now - cached[0] < _ROW_TTL:
            rows.append(dict(cached[1]))
        else:
            # Simpan df dari loop ini agar cabang serial tak membaca ulang OHLCV.
            todo.append((t, key_suffix, df))

    # Analisis yang belum ada cache (paralel bila memungkinkan).
    if todo:
        workers = _plan_workers(len(todo))
        computed: list[tuple] = []
        if workers > 1:
            try:
                # pastikan benchmark ter-cache di disk agar anak tak unduh ulang
                data.get_ohlcv(settings.benchmark, suffix=settings.benchmark_suffix,
                               period=period, use_cache=not refresh)
            except Exception:
                _log.warning("prefetch benchmark gagal - paralel tetap dicoba", exc_info=True)
            try:
                from concurrent.futures import ProcessPoolExecutor
                with ProcessPoolExecutor(max_workers=workers) as ex:
                    # Cabang paralel tetap memakai (t, period, refresh); df tidak
                    # dikirim ke proses anak (diambil sendiri oleh anak).
                    results = list(ex.map(_screen_one, [(t, period, refresh) for t, _, _ in todo],
                                          chunksize=2))
                for (_t, key_suffix, _df), row in zip(todo, results):
                    if row:
                        computed.append((key_suffix, row))
            except Exception:
                _log.warning("screen paralel gagal - fallback serial", exc_info=True)
                computed = []
        if not computed:
            for t, key_suffix, df in todo:
                try:
                    if len(df) < 80:
                        continue
                    computed.append((key_suffix, _row_from_df(t, df)))
                except Exception:
                    # Best-effort (ticker lain tetap dianalisis), tapi TIDAK
                    # senyap: baris yang hilang dari hasil scan harus terlihat.
                    _log.warning("analisis baris %s gagal saat screen - dilewati", t, exc_info=True)
        if len(_ROW_CACHE) + len(computed) > _ROW_CACHE_MAX:
            _ROW_CACHE.clear()
        for key_suffix, row in computed:
            if key_suffix:
                _ROW_CACHE[key_suffix] = (now, dict(row))
            rows.append(row)
        if computed:
            _save_cache()

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    out["_rank"] = out["Signal"].map(_rank)
    out = out[out["Score"] >= min_score]
    out = out[out["Conf"] >= min_confidence]
    if sector:
        out = out[out["Sector"].str.lower() == sector.lower()]
    if min_value and min_value > 0:
        out = out[out["Value"] >= min_value]
    if only_bullish:
        out = out[out["_rank"] >= 4] if "_rank" in out.columns else out
    if decision == "buyable" and "Buyable" in out.columns:
        out = out[out["Buyable"] == True]  # noqa: E712
    elif decision == "buy" and "Decision" in out.columns:
        out = out[out["Decision"] == "BUY"]
    elif decision == "notrade" and "NoTrade" in out.columns:
        out = out[out["NoTrade"] == True]  # noqa: E712
    out = out.sort_values(
        ["_rank", "Score", "Conf"], ascending=[False, False, False]
    ).drop(columns=["_rank"]).reset_index(drop=True)
    if top:
        out = out.head(top)
    return out
