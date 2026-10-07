"""Kalibrasi & optimasi skor (walk-forward) + probabilitas ML.

Model = regresi logistik atas 7 sub-skor komponen (`factors.SCORE_COMPONENTS`),
dilatih **out-of-sample** dengan walk-forward lintas emiten, lalu disimpan ke JSON.
Dipakai oleh `signals.analyze` untuk:
  1. Mengoptimalkan bobot komponen (dari koefisien terlatih).
  2. Menghasilkan probabilitas naik terkalibrasi (prob ML).
  3. Mem-blend keduanya ke skor/confidence akhir.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings
from factors import COMPONENT_MAX, SCORE_COMPONENTS, score_frame
from indicators import add_indicators

MIN_BARS = 140


def _model_path() -> Path:
    if settings.score_model_path:
        return Path(settings.score_model_path)
    return Path(settings.cache_dir) / "score_model.json"


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _fit(X: np.ndarray, y: np.ndarray, lr: float = 0.2, epochs: int = 800, l2: float = 0.02):
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


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    pos = y == 1
    npos, nneg = int(pos.sum()), int((~pos).sum())
    if npos == 0 or nneg == 0:
        return None
    order = np.argsort(p)
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    return float((ranks[pos].sum() - npos * (npos + 1) / 2.0) / (npos * nneg))


def feature_frame(d: pd.DataFrame) -> pd.DataFrame:
    """Sub-skor 7 komponen yang dinormalisasi ke [0,1]."""
    sc = score_frame(d)
    return pd.DataFrame(
        {c: (sc[c] / COMPONENT_MAX[c]).clip(0.0, 1.0) for c in SCORE_COMPONENTS},
        index=d.index,
    )


def _collect(tickers: list[str], horizon: int, min_bars: int):
    import data as datamod

    frames: list[pd.DataFrame] = []
    used: list[str] = []
    errors: list[dict] = []
    for t in tickers:
        try:
            df = datamod.get_ohlcv(t)
            d = add_indicators(df).dropna(subset=["ma50", "ma200", "atr", "supertrend"])
            if len(d) < min_bars:
                errors.append({"ticker": t.upper(), "error": "data kurang"})
                continue
            X = feature_frame(d)
            y = (d["Close"].shift(-horizon) / d["Close"] - 1.0) > 0
            y = y.astype(float)
            valid = (~y.isna()) & (~X.isna().any(axis=1))
            if valid.sum() < min_bars // 2:
                errors.append({"ticker": t.upper(), "error": "sampel kurang"})
                continue
            f = X[valid].copy()
            f["_y"] = y[valid].to_numpy()
            f["_date"] = d.index[valid]
            frames.append(f)
            used.append(t.upper())
        except Exception as exc:  # noqa: BLE001
            errors.append({"ticker": t.upper(), "error": str(exc)})
    return frames, used, errors


def train(tickers: list[str], horizon: int = 10, folds: int = 5, min_bars: int = MIN_BARS,
          save: bool = True, alpha: float | None = None) -> dict:
    frames, used, errors = _collect(tickers, horizon, min_bars)
    if not frames:
        raise ValueError("Tidak ada data valid untuk melatih model")

    pooled = pd.concat(frames).sort_values("_date")
    X = pooled[SCORE_COMPONENTS].to_numpy(dtype=float)
    y = pooled["_y"].to_numpy(dtype=float)
    n = len(y)
    folds = max(2, min(folds, 8))

    oos_p: list[np.ndarray] = []
    oos_y: list[np.ndarray] = []
    fold_size = max(1, n // folds)
    for k in range(1, folds):
        tr_end = k * fold_size
        te_end = (k + 1) * fold_size if k + 1 < folds else n
        if tr_end < 30 or te_end <= tr_end:
            continue
        Xtr, ytr = X[:tr_end], y[:tr_end]
        Xte, yte = X[tr_end:te_end], y[tr_end:te_end]
        mu, sd = Xtr.mean(0), Xtr.std(0)
        sd[sd == 0] = 1.0
        w, b = _fit((Xtr - mu) / sd, ytr)
        oos_p.append(_sigmoid(((Xte - mu) / sd) @ w + b))
        oos_y.append(yte)

    base = float(y.mean())
    acc = bal = auc = auc_min = auc_max = None
    fold_auc: list[float] = []
    if oos_p:
        aucs = [_auc(yy, pp) for pp, yy in zip(oos_p, oos_y)]
        fold_auc = [round(a, 4) for a in aucs if a is not None]
        auc = float(np.mean(fold_auc)) if fold_auc else None
        auc_min = float(min(fold_auc)) if fold_auc else None
        auc_max = float(max(fold_auc)) if fold_auc else None
        accs, bals = [], []
        for pp, yy in zip(oos_p, oos_y):
            pred = pp > 0.5
            accs.append(float((pred == (yy > 0.5)).mean()))
            tp = float(((pred) & (yy == 1)).sum())
            fn = float((~pred & (yy == 1)).sum())
            tn = float((~pred & (yy == 0)).sum())
            fp = float((pred & (yy == 0)).sum())
            tpr = tp / (tp + fn) if (tp + fn) else 0.0
            tnr = tn / (tn + fp) if (tn + fp) else 0.0
            bals.append((tpr + tnr) / 2.0)
        acc = float(np.mean(accs))
        bal = float(np.mean(bals))
    edge = (bal - 0.5) if bal is not None else None
    edge_ok = bool(auc is not None and auc >= settings.min_oos_auc)

    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    w, b = _fit((X - mu) / sd, y)

    raw_coef = {name: float(w[i] / sd[i]) for i, name in enumerate(SCORE_COMPONENTS)}
    abs_sum = sum(abs(v) for v in raw_coef.values()) or 1.0
    importance = {k: round(abs(v) / abs_sum * 100.0, 2) for k, v in raw_coef.items()}
    eff_alpha = float(alpha if alpha is not None else settings.ml_blend_alpha)
    if not edge_ok:
        eff_alpha = 0.0

    model = {
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "horizon": int(horizon),
        "features": list(SCORE_COMPONENTS),
        "coef": [float(x) for x in w],
        "intercept": float(b),
        "mu": [float(x) for x in mu],
        "sd": [float(x) for x in sd],
        "base_rate": base,
        "oos_accuracy": acc,
        "balanced_accuracy": bal,
        "oos_edge": edge,
        "auc": auc,
        "auc_min": auc_min,
        "auc_max": auc_max,
        "folds_auc": fold_auc,
        "min_oos_auc": float(settings.min_oos_auc),
        "edge_ok": edge_ok,
        "n_samples": int(n),
        "n_tickers": len(used),
        "folds": folds,
        "alpha": float(alpha if alpha is not None else settings.ml_blend_alpha),
        "effective_alpha": eff_alpha,
        "component_weights": importance,
        "component_coef": raw_coef,
    }
    if save:
        save_model(model)
    return {"model": model, "universe": used, "errors": errors}


# --- Model cache & persistence ---
_MODEL_CACHE: dict = {"mtime": None, "model": None, "path": None}


def save_model(model: dict) -> None:
    path = _model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    _MODEL_CACHE.update(mtime=path.stat().st_mtime, model=model, path=str(path))


def load_model() -> dict | None:
    path = _model_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if (_MODEL_CACHE["model"] is not None and _MODEL_CACHE["mtime"] == mtime
            and _MODEL_CACHE["path"] == str(path)):
        return _MODEL_CACHE["model"]
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    _MODEL_CACHE.update(mtime=mtime, model=model, path=str(path))
    return model


def prob_up(d: pd.DataFrame, model: dict | None = None) -> float | None:
    model = model or load_model()
    if not model:
        return None
    X = feature_frame(d).iloc[-1].to_numpy(dtype=float)
    if np.isnan(X).any():
        return None
    mu = np.asarray(model["mu"], dtype=float)
    sd = np.asarray(model["sd"], dtype=float)
    w = np.asarray(model["coef"], dtype=float)
    return float(_sigmoid(((X - mu) / sd) @ w + model["intercept"]))


def prob_to_score(prob: float, base: float) -> float:
    """Peta probabilitas -> skor 0..100 (base_rate = 50, monoton)."""
    base = min(max(float(base), 1e-6), 1.0 - 1e-6)
    scale = max(base, 1.0 - base)
    return float(np.clip(50.0 + (prob - base) / scale * 50.0, 0.0, 100.0))


def status() -> dict:
    model = load_model()
    if not model:
        return {"available": False, "path": str(_model_path())}
    return {
        "available": True,
        "path": str(_model_path()),
        "model": model,
    }
