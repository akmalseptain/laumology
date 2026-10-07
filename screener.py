from __future__ import annotations

import time

import pandas as pd

import data
from config import WATCHLIST_PRESETS, sector_of
from signals import analyze
from universe import auto_universe, full_universe

_AUTO_KEYS = {"auto", "top", "most-active", "paling aktif", "palingaktif", "likuid", "liquid-auto"}
_ALL_KEYS = {"all", "allidx", "all-idx", "semua-emiten", "seluruh", "idx-all", "allidx2"}

# Cache baris hasil analisis (key ticker+bar) agar scan ulang instan.
_ROW_CACHE: dict[str, tuple[float, dict]] = {}
_ROW_TTL = 900.0
_ROW_CACHE_MAX = 8000


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
            pass
    rows = []
    now = time.time()
    for t in tickers:
        try:
            df = data.get_ohlcv(t, period=period, use_cache=not refresh)
            if len(df) < 80:
                continue
            key = f"{t}:{str(df.index[-1])[:10]}"
            cached = _ROW_CACHE.get(key)
            if cached and not refresh and now - cached[0] < _ROW_TTL:
                row = dict(cached[1])
            else:
                res = analyze(df, t, light=True)
                row = res.as_row()
                try:
                    turnover = (df["Close"] * df["Volume"]).tail(20).mean()
                    row["Value"] = float(turnover) if pd.notna(turnover) else 0.0
                except Exception:
                    row["Value"] = 0.0
                if len(_ROW_CACHE) > _ROW_CACHE_MAX:
                    _ROW_CACHE.clear()
                _ROW_CACHE[key] = (now, dict(row))
            row["_rank"] = _rank(row.get("Signal", ""))
            row["Sector"] = sector_of(t)
            rows.append(row)
        except Exception as exc:
            print(f"  ! {t}: {exc}")

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    out = out[out["Score"] >= min_score]
    out = out[out["Conf"] >= min_confidence]
    if sector:
        out = out[out["Sector"].str.lower() == sector.lower()]
    if min_value and min_value > 0:
        out = out[out["Value"] >= min_value]
    if only_bullish:
        out = out[out["_rank"] >= 4]
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
