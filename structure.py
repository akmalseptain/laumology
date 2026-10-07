"""Market structure: HH/HL/LH/LL, BOS, CHoCH.

Additive layer di atas `indicators.swing_points`. Tidak mengubah indikator lama.
"""
from __future__ import annotations

import pandas as pd

from indicators import swing_points


def market_structure(d: pd.DataFrame, order: int = 2, lookback: int = 120) -> dict:
    """Klasifikasi struktur pasar dari swing high/low terakhir."""
    if len(d) < 20:
        price = float(d["Close"].iloc[-1])
        return {"bias": "ranging", "label": "Data kurang", "hh": False, "hl": False,
                "lh": False, "ll": False, "bos": "none", "choch": False,
                "last_swing_high": price, "last_swing_low": price,
                "prev_swing_high": price, "prev_swing_low": price}

    sub = d.tail(min(lookback, len(d)))
    hi_flags, lo_flags = swing_points(sub["High"], sub["Low"], order=order)
    highs = list(sub.loc[hi_flags, "High"].to_numpy())
    lows = list(sub.loc[lo_flags, "Low"].to_numpy())
    price = float(d["Close"].iloc[-1])

    hh = len(highs) >= 2 and highs[-1] > highs[-2]
    lh = len(highs) >= 2 and highs[-1] < highs[-2]
    hl = len(lows) >= 2 and lows[-1] > lows[-2]
    ll = len(lows) >= 2 and lows[-1] < lows[-2]

    if hh and hl:
        bias, label = "bullish", "HH-HL"
    elif lh and ll:
        bias, label = "bearish", "LH-LL"
    elif hh:
        bias, label = "bullish", "HH"
    elif ll:
        bias, label = "bearish", "LL"
    else:
        bias, label = "ranging", "Ranging"

    last_high = float(highs[-1]) if highs else float(sub["High"].max())
    last_low = float(lows[-1]) if lows else float(sub["Low"].min())
    prev_high = float(highs[-2]) if len(highs) >= 2 else last_high
    prev_low = float(lows[-2]) if len(lows) >= 2 else last_low

    bos = "none"
    if price > last_high:
        bos = "bullish"
    elif price < last_low:
        bos = "bearish"

    choch = (bias == "bullish" and price < last_low) or (bias == "bearish" and price > last_high)

    return {
        "bias": bias, "label": label,
        "hh": bool(hh), "hl": bool(hl), "lh": bool(lh), "ll": bool(ll),
        "bos": bos, "choch": bool(choch),
        "last_swing_high": last_high, "last_swing_low": last_low,
        "prev_swing_high": prev_high, "prev_swing_low": prev_low,
    }
