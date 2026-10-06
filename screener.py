from __future__ import annotations

import pandas as pd

import data
from config import WATCHLIST_PRESETS, sector_of
from signals import analyze


def resolve_watchlist(name: str) -> list[str]:
    key = name.lower().strip()
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
) -> pd.DataFrame:
    rows = []
    for t in tickers:
        try:
            df = data.get_ohlcv(t, period=period, use_cache=not refresh)
            if len(df) < 80:
                continue
            res = analyze(df, t)
            row = res.as_row()
            row["_rank"] = _rank(res.signal)
            row["Sector"] = sector_of(t)
            try:
                turnover = (df["Close"] * df["Volume"]).tail(20).mean()
                row["Value"] = float(turnover) if pd.notna(turnover) else 0.0
            except Exception:
                row["Value"] = 0.0
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
    out = out.sort_values(
        ["_rank", "Score", "Conf"], ascending=[False, False, False]
    ).drop(columns=["_rank"]).reset_index(drop=True)
    if top:
        out = out.head(top)
    return out
