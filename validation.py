from __future__ import annotations

import numpy as np
import pandas as pd

from factors import (
    CANDIDATE_FACTORS,
    FACTOR_KEYS,
    candidate_frame,
    confluence_frame,
    score_frame,
)
from config import settings
from indicators import add_indicators

BUCKETS = [
    (0, 40, "Lemah < 40"),
    (40, 65, "Sedang 40-64"),
    (65, 80, "Kuat 65-79"),
    (80, 101, "Sangat 80-100"),
]

# Ambang edge (win-rate di atas baseline) agar kandidat layak dipromosikan.
MIN_EDGE = 0.03

# Tingkat keyakinan 95% (z dua sisi) untuk batas bawah Wilson.
WILSON_Z = 1.96


def wilson_lower_bound(p: float, n: int, z: float = WILSON_Z) -> float:
    """Batas bawah interval keyakinan Wilson untuk proporsi `p` dari `n` sampel.

    Murni (tanpa state/dependensi baru). Mengembalikan 0.0 bila `n <= 0`.
    Dipakai agar promosi faktor butuh keyakinan statistik, bukan sekadar edge
    titik yang bisa lolos karena kebetulan.
    """
    if n <= 0:
        return 0.0
    p = float(p)
    z2 = z * z
    denom = 1.0 + z2 / n
    center = p + z2 / (2.0 * n)
    margin = z * ((p * (1.0 - p) / n + z2 / (4.0 * n * n)) ** 0.5)
    return max(0.0, (center - margin) / denom)


def _factor_stats(cf: pd.DataFrame, keys: list[str], fwd: pd.Series, base_wr: float, min_n: int) -> list[dict]:
    out = []
    for k in keys:
        mask = cf[k].astype(bool)
        r = fwd[mask].dropna()
        if len(r) < min_n:
            continue
        wr = float((r > 0).mean())
        out.append({
            "factor": k,
            "n": int(len(r)),
            "win_rate": wr,
            "win_rate_lo": wilson_lower_bound(wr, len(r)),
            "avg_ret": float(r.mean()),
            "median_ret": float(r.median()),
            "edge": wr - base_wr,
        })
    return out


def analyze_accuracy(df: pd.DataFrame, horizon: int | None = None, min_n: int = 20, min_edge: float = MIN_EDGE) -> dict:
    """Measure predictive edge of each factor and calibrate the composite score.

    Forward return = close[t+horizon] / close[t] - 1. This is a historical
    study: the last `horizon` bars are dropped (look-ahead free).

    `horizon=None` mengambil `settings.swing_horizon_days` (satu sumber kebenaran).
    """
    horizon = settings.swing_horizon_days if horizon is None else horizon
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
    factors = _factor_stats(cf, FACTOR_KEYS, fwd, base_wr, min_n)
    factors.sort(key=lambda x: x["edge"], reverse=True)

    candf = candidate_frame(d)
    candidates = _factor_stats(candf, CANDIDATE_FACTORS, fwd, base_wr, min_n)
    candidates.sort(key=lambda x: x["edge"], reverse=True)
    recommendations = [c for c in candidates if c["edge"] >= min_edge and c["win_rate_lo"] > base_wr]

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
        "min_edge": float(min_edge),
        "base_win_rate": base_wr,
        "base_avg_ret": base_avg,
        "base_median_ret": base_med,
        "calibration": calibration,
        "factors": factors,
        "candidates": candidates,
        "recommendations": recommendations,
        "agreement": agreement,
    }


def calibrate(tickers: list[str], horizon: int | None = None, min_edge: float = MIN_EDGE, min_tickers: int = 5) -> dict:
    """Kalibrasi bobot indikator kandidat lintas emiten.

    Menjalankan uji edge per faktor pada banyak saham, lalu merata-ratakan edge
    (dibobot jumlah sampel). Faktor kandidat yang lolos ambang edge diusulkan
    untuk dipromosikan ke skor, lengkap dengan bobot relatif ternormalisasi.

    `horizon=None` mengambil `settings.swing_horizon_days` (satu sumber kebenaran).
    """
    horizon = settings.swing_horizon_days if horizon is None else horizon
    import data

    per_factor: dict[str, dict] = {k: {"sum_w": 0.0, "sum_edge": 0.0, "sum_wr": 0.0, "n": 0} for k in (FACTOR_KEYS + CANDIDATE_FACTORS)}
    base_wrs: list[tuple[float, int]] = []
    used: list[str] = []
    errors: list[dict] = []

    for t in tickers:
        try:
            df = data.get_ohlcv(t)
            res = analyze_accuracy(df, horizon=horizon, min_edge=min_edge)
        except Exception as exc:
            errors.append({"ticker": t, "error": str(exc)})
            continue
        used.append(t.upper())
        base_wrs.append((float(res["base_win_rate"]), int(res["samples"])))
        for row in list(res["factors"]) + list(res["candidates"]):
            acc = per_factor[row["factor"]]
            w = row["n"]
            acc["sum_w"] += w
            acc["sum_edge"] += row["edge"] * w
            acc["sum_wr"] += row["win_rate"] * w
            acc["n"] += w

    if len(used) < min_tickers:
        raise ValueError(f"Perlu minimal {min_tickers} emiten valid (hanya {len(used)})")

    total_w = sum(w for _, w in base_wrs) or 1
    base_wr = sum(wr * w for wr, w in base_wrs) / total_w

    rows: list[dict] = []
    for k, acc in per_factor.items():
        if acc["n"] == 0:
            continue
        rows.append({
            "factor": k,
            "n": acc["n"],
            "win_rate": acc["sum_wr"] / acc["sum_w"],
            "win_rate_lo": wilson_lower_bound(acc["sum_wr"] / acc["n"], acc["n"]),
            "edge": acc["sum_edge"] / acc["sum_w"],
            "candidate": k in CANDIDATE_FACTORS,
        })
    rows.sort(key=lambda x: x["edge"], reverse=True)

    promoted = [r for r in rows if r["candidate"] and r["edge"] >= min_edge and r["win_rate_lo"] > base_wr]
    pos_sum = sum(max(r["edge"], 0.0) for r in promoted) or 1.0
    for r in promoted:
        r["suggested_weight"] = round(max(r["edge"], 0.0) / pos_sum, 4)

    return {
        "horizon": int(horizon),
        "min_edge": float(min_edge),
        "universe": used,
        "n_tickers": len(used),
        "base_win_rate": round(base_wr, 4),
        "factors": rows,
        "promoted": promoted,
        "errors": errors,
    }


REGIMES = ("uptrend", "downtrend", "ranging")


def _benchmark_regime(period: str | None = None) -> pd.Series:
    import data as datamod

    b = add_indicators(datamod.get_ohlcv("^JKSE", suffix="", period=period or settings.period))
    reg = pd.Series("ranging", index=b.index)
    reg[(b["Close"] > b["ma50"]) & (b["ma20"] > b["ma50"])] = "uptrend"
    reg[b["Close"] < b["ma50"]] = "downtrend"
    return reg


def calibrate_regime(tickers: list[str], horizon: int | None = None, min_n: int = 50) -> dict:
    """Edge tiap faktor dipisah menurut regime pasar (IHSG up/down/ranging)."""
    horizon = settings.swing_horizon_days if horizon is None else horizon
    import data as datamod

    reg = _benchmark_regime()
    keys = FACTOR_KEYS + CANDIDATE_FACTORS
    acc = {r: {k: [0, 0] for k in keys} for r in REGIMES}
    base = {r: [0, 0] for r in REGIMES}
    used: list[str] = []
    errors: list[dict] = []

    for t in tickers:
        try:
            d = add_indicators(datamod.get_ohlcv(t)).dropna(subset=["ma50", "ma200", "atr", "supertrend"])
            if len(d) < 80:
                errors.append({"ticker": t.upper(), "error": "data kurang"})
                continue
            f = confluence_frame(d)[FACTOR_KEYS].join(candidate_frame(d)[CANDIDATE_FACTORS])
            fwd = (d["Close"].shift(-horizon) / d["Close"] - 1.0)
            rr = reg.reindex(d.index).ffill()
            used.append(t.upper())
            for r in REGIMES:
                m = (rr == r).to_numpy()
                fl = fwd[m].dropna().to_numpy()
                if len(fl):
                    base[r][0] += int((fl > 0).sum())
                    base[r][1] += len(fl)
                for k in keys:
                    mask = m & f[k].to_numpy()
                    fr = fwd[mask].dropna().to_numpy()
                    if len(fr):
                        acc[r][k][0] += int((fr > 0).sum())
                        acc[r][k][1] += len(fr)
        except Exception as exc:  # noqa: BLE001
            errors.append({"ticker": t.upper(), "error": str(exc)})

    out: dict[str, dict] = {}
    for r in REGIMES:
        bwr = base[r][0] / base[r][1] if base[r][1] else None
        rows = []
        for k in keys:
            w, n = acc[r][k]
            if n < min_n or bwr is None:
                continue
            rows.append({"factor": k, "n": n, "win_rate": w / n,
                         "edge": w / n - bwr, "candidate": k in CANDIDATE_FACTORS})
        rows.sort(key=lambda x: x["edge"], reverse=True)
        out[r] = {"base_win_rate": bwr, "n": base[r][1], "factors": rows}

    return {"horizon": int(horizon), "min_n": int(min_n), "universe": used,
            "regimes": out, "errors": errors}
