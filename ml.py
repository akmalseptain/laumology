from __future__ import annotations

import numpy as np
import pandas as pd

from factors import CANDIDATE_FACTORS, FACTOR_KEYS, candidate_frame, confluence_frame
from indicators import add_indicators


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _fit(X: np.ndarray, y: np.ndarray, lr: float = 0.15, epochs: int = 500, l2: float = 0.02):
    n, d = X.shape
    w = np.zeros(d)
    b = 0.0
    for _ in range(epochs):
        p = _sigmoid(X @ w + b)
        gw = (X.T @ (p - y)) / n + l2 * w
        gb = float(np.mean(p - y))
        w -= lr * gw
        b -= lr * gb
    return w, b


def _calibration(probs: np.ndarray, y: np.ndarray) -> list[dict]:
    out = []
    for lo, hi in [(0, 0.4), (0.4, 0.55), (0.55, 0.7), (0.7, 1.01)]:
        m = (probs >= lo) & (probs < hi)
        if m.sum() == 0:
            out.append({"bucket": f"{int(lo*100)}-{int(hi*100)}%", "n": 0, "actual": None})
            continue
        out.append({"bucket": f"{int(lo*100)}-{int(hi*100)}%", "n": int(m.sum()), "actual": float(y[m].mean())})
    return out


def predict(
    df: pd.DataFrame, ticker: str = "", horizon: int = 10, test_frac: float = 0.3,
    include_candidates: bool = False,
) -> dict:
    d = add_indicators(df)
    d = d.dropna(subset=["ma50", "ma200", "atr", "supertrend"])
    if len(d) < 80:
        raise ValueError("Data tidak cukup untuk model (min 80 bar)")

    cf = confluence_frame(d)
    if include_candidates:
        cf = cf.join(candidate_frame(d)[CANDIDATE_FACTORS])
    feature_keys = list(FACTOR_KEYS) + (list(CANDIDATE_FACTORS) if include_candidates else [])
    close = d["Close"]
    fwd = (close.shift(-horizon) / close - 1.0)
    y_all = (fwd > 0).astype(float).to_numpy()
    X_all = cf[feature_keys].astype(float).to_numpy()
    valid = ~np.isnan(y_all)
    X = X_all[valid]
    y = y_all[valid]
    if len(X) < 60:
        raise ValueError("Sampel terlalu sedikit untuk model")

    split = max(int(len(X) * (1.0 - test_frac)), 30)
    # standardize using train stats
    mu = X[:split].mean(axis=0)
    sd = X[:split].std(axis=0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd

    w, b = _fit(Xs[:split], y[:split])
    p_test = _sigmoid(Xs[split:] @ w + b)
    acc = float(((p_test > 0.5) == (y[split:] > 0.5)).mean()) if len(p_test) else None

    probs = _sigmoid(Xs @ w + b)
    base = float(y.mean())

    weights = [
        {"factor": k, "weight": round(float(wf) / sd[i], 4), "std_weight": round(float(wf), 4)}
        for i, (k, wf) in enumerate(zip(feature_keys, w))
    ]
    weights.sort(key=lambda x: x["weight"], reverse=True)

    # probability from latest bar
    latest = X_all[-1] if not np.isnan(X_all[-1]).any() else X[-1]
    latest_prob = float(_sigmoid(((latest - mu) / sd) @ w + b))

    return {
        "ticker": ticker.upper(),
        "horizon": horizon,
        "samples": int(len(X)),
        "features": feature_keys,
        "include_candidates": bool(include_candidates),
        "train": split,
        "test": int(len(X) - split),
        "base_rate": base,
        "test_accuracy": acc,
        "edge_vs_base": (acc - base) if acc is not None else None,
        "current_prob_up": latest_prob,
        "calibration": _calibration(probs, y),
        "weights": weights,
    }
