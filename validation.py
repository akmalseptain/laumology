from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import add_indicators
from signals import FACTOR_KEYS, confluence_frame, score_frame

BUCKETS = [
    (0, 40, "Lemah < 40"),
    (40, 65, "Sedang 40-64"),
    (65, 80, "Kuat 65-79"),
    (80, 101, "Sangat 80-100"),
]


def analyze_accuracy(df: pd.DataFrame, horizon: int = 10, min_n: int = 20) -> dict:
    """Measure predictive edge of each factor and calibrate the composite score.

    Forward return = close[t+horizon] / close[t] - 1. This is a historical
    study: the last `horizon` bars are dropped (look-ahead free).
    """
    d = add_indicators(df)
    d = d.dropna(subset=["ma50", "ma200", "atr", "supertrend"])
    if len(d) < 80:
        raise ValueError("Data tidak cukup untuk uji akurasi (min 80 bar)")

    close = d["Close"]
    fwd = (close.shift(-horizon) / close - 1.0) * 100.0
    sc = score_frame(d)["score"]
    base = fwd.dropna()
    base_wr = float((base > 0).mean()) if len(base) else 0.0
    base_avg = float(base.mean()) if len(base) else 0.0
    base_med = float(base.median()) if len(base) else 0.0

    calibration = []
    for lo, hi, label in BUCKETS:
        mask = (sc >= lo) & (sc < hi)
        r = fwd[mask].dropna()
        calibration.append({
            "bucket": label,
            "n": int(len(r)),
            "win_rate": float((r > 0).mean()) if len(r) else None,
            "avg_ret": float(r.mean()) if len(r) else None,
            "median_ret": float(r.median()) if len(r) else None,
            "edge": (float((r > 0).mean()) - base_wr) if len(r) else None,
        })

    cf = confluence_frame(d)
    factors = []
    for k in FACTOR_KEYS:
        mask = cf[k].astype(bool)
        r = fwd[mask].dropna()
        if len(r) < min_n:
            continue
        wr = float((r > 0).mean())
        factors.append({
            "factor": k,
            "n": int(len(r)),
            "win_rate": wr,
            "avg_ret": float(r.mean()),
            "median_ret": float(r.median()),
            "edge": wr - base_wr,
        })
    factors.sort(key=lambda x: x["edge"], reverse=True)

    # Synergy: how many factors agree, vs outcome
    n_true = cf[FACTOR_KEYS].sum(axis=1)
    agreement = []
    for lo, hi, label in [(0, 6, "0-5 setuju"), (6, 11, "6-10"), (11, 16, "11-15"), (16, 21, "16-20")]:
        mask = (n_true >= lo) & (n_true < hi)
        r = fwd[mask].dropna()
        agreement.append({
            "bucket": label,
            "n": int(len(r)),
            "win_rate": float((r > 0).mean()) if len(r) else None,
            "avg_ret": float(r.mean()) if len(r) else None,
        })

    return {
        "horizon": int(horizon),
        "bars": int(len(d)),
        "samples": int(len(base)),
        "base_win_rate": base_wr,
        "base_avg_ret": base_avg,
        "base_median_ret": base_med,
        "calibration": calibration,
        "factors": factors,
        "agreement": agreement,
    }
