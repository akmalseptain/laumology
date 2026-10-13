from __future__ import annotations

import math

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

# Enum keandalan (reliability) per horizon — W-0021. Sengaja dibedakan TEGAS:
#   - "terbukti"       : ada faktor signifikan ∧ sampel forward & trade cukup ∧ tak timeout-dominated
#   - "belum_pasti"    : ada sinyal/edge tapi bukti belum kuat (timeout-dominated,
#                        atau trade belum cukup termasuk PF tak hingga)
#   - "sampel_kurang"  : sampel forward < min_n (populasi kurang, BUKAN sekadar timeout)
#   - "tidak_ada_edge" : sampel cukup tapi tak ada faktor signifikan
RELIABILITY_LEVELS = ("terbukti", "belum_pasti", "sampel_kurang", "tidak_ada_edge")

# Batas aman uji out-of-sample (`candidate_out_of_sample`): K fold & horizon
# dibatasi agar loop K×horizon tak jadi vektor DoS, dan `min_edge` dijaga finite.
MIN_FOLDS = 2
MAX_FOLDS = 8
MAX_HORIZON = 60


def _reliability_level(has_sig: bool, fwd_samples: int, trade_sufficient: bool,
                       timeout_dominated: bool, min_n: int) -> str:
    """Klasifikasi kejujuran bukti per horizon (W-0021).

    Murni (tanpa state). `timeout_dominated` (mis. horizon=1 pada `max_hold=1`,
    populasi trade didominasi TIMEOUT) TIDAK boleh terbaca "sampel_kurang":
    keduanya dibedakan agar point-estimate rapuh tidak diklaim "terbukti".
    Catatan: `profit_factor` tak hingga → `trade_sufficient=False` walau sampel
    cukup; kondisi itu jatuh ke "belum_pasti", bukan "sampel_kurang".
    """
    if timeout_dominated:
        return "belum_pasti"
    if fwd_samples < min_n:
        return "sampel_kurang"
    if has_sig and trade_sufficient:
        return "terbukti"
    if has_sig:
        return "belum_pasti"
    return "tidak_ada_edge"


def horizon_band_verdict(rows: list[dict] | None) -> dict:
    """Ringkas reliabilitas lintas-horizon jadi SATU verdict band (W-0021 lanjutan).

    Murni (tanpa state/I/O): hanya membaca `row["reliability"]["level"]` +
    `"has_significant"`. Dipakai panel Akurasi multi-horizon (1/5/10/15 bar ⇒
    band "harian–3 mingguan") agar headline tidak lagi memakai edge titik mentah
    yang bisa overclaim saat tiap horizon berlabel "tanpa edge".

    Aturan (dibakukan dari reaksi tim, bukan sekadar urutan naif):
      - `tidak_ada_edge` MENVETO: satu horizon sampel-cukup-tanpa-edge sudah
        cukup menolak klaim "terbukti" — jangan overclaim.
      - `terbukti` bila ADA horizon `terbukti` ∧ TAK ada `tidak_ada_edge`.
        Horizon h=1 yang selalu timeout-dominated (`belum_pasti`, artefak
        `max_hold=1`) TIDAK memveto; kalau ia memveto, band tak akan pernah
        "terbukti" karena default horizon selalu memuat 1.
      - lalu `sampel_kurang` bila ada; sisanya `belum_pasti`.
    """
    levels: list[str] = []
    horizons: list[int] = []
    n_significant = 0
    for row in rows or []:
        rel = row.get("reliability") or {}
        lvl = rel.get("level")
        if lvl not in RELIABILITY_LEVELS:
            continue
        levels.append(lvl)
        try:
            horizons.append(int(row.get("horizon")))
        except (TypeError, ValueError):
            pass
        if rel.get("has_significant"):
            n_significant += 1
    present = set(levels)
    if not present:
        level = None
    elif "tidak_ada_edge" in present:
        level = "tidak_ada_edge"
    elif "terbukti" in present:
        level = "terbukti"
    elif "sampel_kurang" in present:
        level = "sampel_kurang"
    else:
        level = "belum_pasti"
    return {
        "level": level,
        "n_horizons": len(levels),
        "n_terbukti": levels.count("terbukti"),
        "n_significant_horizons": n_significant,
        "horizons": horizons,
    }


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


def analyze_accuracy(df: pd.DataFrame, horizon: int | None = None, min_n: int = 20, min_edge: float = MIN_EDGE,
                     d: pd.DataFrame | None = None) -> dict:
    """Measure predictive edge of each factor and calibrate the composite score.

    Forward return = close[t+horizon] / close[t] - 1. This is a historical
    study: the last `horizon` bars are dropped (look-ahead free).

    `horizon=None` mengambil `settings.swing_horizon_days` (satu sumber kebenaran).
    `d` opsional: hasil `add_indicators` yang sudah dihitung agar tidak mengulang
    (lihat `accuracy_by_horizon`). Bila `None`, dihitung sendiri.
    """
    horizon = settings.swing_horizon_days if horizon is None else horizon
    d = add_indicators(df) if d is None else d
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


def candidate_out_of_sample(
    df: pd.DataFrame,
    horizon: int | None = None,
    folds: int = 5,
    min_n: int = 20,
    min_edge: float = MIN_EDGE,
    d: pd.DataFrame | None = None,
) -> dict:
    """Uji edge kandidat secara OUT-OF-SAMPLE (K-fold temporal) — READ-ONLY.

    Latar: `analyze_accuracy`/`calibrate` menguji kandidat **in-sample pada seri
    yang sama** (lihat `analyze_accuracy:192-195` dan `calibrate:441`) lalu
    mengusulkan promosi hanya dari edge+Wilson, tanpa pemisahan temporal. Fungsi
    ini adalah gate tambahan: bagi seri jadi `folds` blok temporal berurutan dan
    hitung edge forward tiap kandidat HANYA di blok uji.

    Bebas look-ahead tanpa reinvent: forward return dihitung dari irisan fold itu
    sendiri (`close.shift(-horizon)` per fold), jadi `horizon` bar terakhir tiap
    fold otomatis terbuang — sekaligus men-*purge* batas fold (tak memakai data
    lewat ujung fold), sejalan `calibration.train:120-134` & `backtest.walkforward`.

    Promosi (`verdict="terbukti"`) hanya bila median edge OOS >= `min_edge` ∧
    mayoritas fold edge positif; selebihnya `belum_pasti`/`tidak_ada_edge`/
    `sampel_kurang` (enum `RELIABILITY_LEVELS`, fail-closed). Kandidat dengan
    sampel per-fold < `min_n` tak dihitung agar tak jadi "sampel_kurang" palsu;
    fold pendek (`horizon` > panjang fold) dibuang fail-closed.

    Murni (tanpa I/O/network), TIDAK menyentuh `score_frame`/skor produksi.
    `min_edge` non-finite dipulihkan ke `MIN_EDGE`; `folds`/`horizon` di-clamp
    (anti-DoS). `d` opsional: hasil `add_indicators` yang sudah dihitung.
    """
    from metrics import risk_metrics

    horizon = settings.swing_horizon_days if horizon is None else int(horizon)
    horizon = max(1, min(horizon, MAX_HORIZON))
    try:
        folds = int(folds)
    except (TypeError, ValueError):
        folds = 5
    folds = max(MIN_FOLDS, min(folds, MAX_FOLDS))
    try:
        min_edge = float(min_edge)
    except (TypeError, ValueError):
        min_edge = MIN_EDGE
    if not math.isfinite(min_edge):
        min_edge = MIN_EDGE
    min_edge = max(0.0, min(1.0, min_edge))
    min_n = max(2, int(min_n))

    d = add_indicators(df) if d is None else d
    d = d.dropna(subset=["ma50", "ma200", "atr", "supertrend"])
    n = len(d)
    if n < 80:
        raise ValueError("Data tidak cukup untuk uji OOS (min 80 bar)")

    cf = candidate_frame(d)
    close = d["Close"]

    size = max(n // folds, 1)
    per_fold: list[dict] = []
    for k in range(folds):
        start = k * size
        end = n if k == folds - 1 else min((k + 1) * size, n)
        if end <= start:
            continue
        seg_close = close.iloc[start:end]
        fwd = (seg_close.shift(-horizon) / seg_close - 1.0) * 100.0
        base = fwd.dropna()
        if not len(base):
            continue
        per_fold.append({
            "fwd": fwd,
            "cf": cf.iloc[start:end],
            "base_wr": float((base > 0).mean()),
        })

    rows: list[dict] = []
    for k in CANDIDATE_FACTORS:
        fold_edges: list[float] = []
        pool_ret: list[float] = []
        n_total = 0
        for pf in per_fold:
            fwd = pf["fwd"]
            r = fwd[pf["cf"][k].astype(bool) & fwd.notna()].dropna()
            if len(r) < min_n:
                continue
            fold_edges.append(float((r > 0).mean()) - pf["base_wr"])
            pool_ret.extend(float(x) for x in r)
            n_total += len(r)

        n_valid = len(fold_edges)
        if n_valid == 0 or n_total < min_n:
            rows.append({
                "factor": k, "n": n_total, "n_folds": n_valid,
                "median_edge": None, "positive_folds": 0,
                "expectancy": None, "max_dd": None, "sharpe": None,
                "verdict": "sampel_kurang", "promote": False,
            })
            continue

        median_edge = float(np.median(fold_edges))
        positive = int(sum(1 for e in fold_edges if e > 0))
        promote = bool(median_edge >= min_edge and positive * 2 > n_valid)

        equity = [1.0]
        for x in pool_ret:
            equity.append(equity[-1] * (1.0 + x / 100.0))
        rm = risk_metrics(equity, pool_ret)

        if promote:
            verdict = "terbukti"
        elif median_edge > 0:
            verdict = "belum_pasti"
        else:
            verdict = "tidak_ada_edge"

        rows.append({
            "factor": k,
            "n": n_total,
            "n_folds": n_valid,
            "median_edge": median_edge,
            "positive_folds": positive,
            "expectancy": rm.get("expectancy_pct"),
            "max_dd": rm.get("max_dd"),
            "sharpe": rm.get("sharpe"),
            "verdict": verdict,
            "promote": promote,
        })

    rows.sort(
        key=lambda x: (x["median_edge"] is not None, x["median_edge"] if x["median_edge"] is not None else 0.0),
        reverse=True,
    )
    return {
        "horizon": int(horizon),
        "folds": len(per_fold),
        "min_n": int(min_n),
        "min_edge": float(min_edge),
        "candidates": rows,
        "promoted": [r["factor"] for r in rows if r["promote"]],
        "verdict_levels": list(RELIABILITY_LEVELS),
    }


def accuracy_by_horizon(
    df: pd.DataFrame,
    horizons: tuple[int, ...] = (1, 5, 10, 15),
    min_n: int = 20,
    min_edge: float = MIN_EDGE,
    d: pd.DataFrame | None = None,
) -> dict:
    """Studi akurasi lintas horizon (W-0017) — READ-ONLY & additive.

    Dua konstruk dibedakan TEGAS agar tak tertukar:
      - `forward`: win-rate ARAH return majemuk `close.shift(-h)/close-1`
        (dari `analyze_accuracy`); sampel = bars - h ⇒ look-ahead free.
      - `trade`: win-rate TRADE-level setelah TP/SL/timeout
        (`backtest(max_hold=h)`); populasi berbeda karena posisi bisa keluar
        lebih awal dari `h`, jadi `avg_bars < max_hold`.

    Indikator dihitung SEKALI (`d`) lalu dipakai ulang tiap horizon/metrik.
    `trade` ditandai `sufficient=False` bila `n_trades < min_n`; `profit_factor`
    `None` bila tak hingga (tak ada trade rugi). Tiap entri `factors`/`candidates`
    memuat `win_rate_lo` + `significant`. Tiap row memuat `reliability` (enum
    `RELIABILITY_LEVELS`, lihat `_reliability_level`): penanda "cocok/belum pasti"
    per horizon — `best_factor`/`best_edge` HANYA dari faktor `significant`, `None`
    bila tak ada.     `indicator_stability` merangkum lintas horizon (`avg_edge`
    dibobot `n`; `consistent` = hadir di semua `hs`, ≥2 horizon, edge>0 di tiap
    horizon).     `band_verdict` = ringkasan SATU band reliabilitas lintas-horizon
    (`horizon_band_verdict`), sedangkan tabel stabilitas tetap berbasis edge
    forward titik per-indikator — beda konstruk. Tidak menyentuh skor/rumus.
    `d` opsional: hasil `add_indicators` yang sudah dihitung agar tidak mengulang
    (lihat `analyze_accuracy`). Bila `None`, dihitung sendiri.
    """
    from backtest import backtest

    hs = sorted({int(h) for h in horizons if int(h) > 0})
    if not hs:
        raise ValueError("horizons kosong (minimal satu horizon > 0)")

    d = add_indicators(df) if d is None else d
    rows: list[dict] = []
    for h in hs:
        acc = analyze_accuracy(df, horizon=h, min_n=min_n, min_edge=min_edge, d=d)
        bt = backtest(df, max_hold=h, d=d)

        # Edge per-indikator tiap horizon: populasi `factors` (inti) dan
        # `candidates` (kandidat) dibedakan tegas lewat flag `candidate`.
        # `win_rate_lo` (batas bawah Wilson) + `significant` dibawa agar
        # penilaian per-horizon benar-benar statistik, sejalan dengan
        # `recommendations` (`edge >= min_edge` ∧ `win_rate_lo > base_wr`).
        base_wr = acc["base_win_rate"]
        factors = [
            {"factor": f["factor"], "n": f["n"], "win_rate": f["win_rate"],
             "win_rate_lo": f["win_rate_lo"],
             "significant": f["edge"] >= min_edge and f["win_rate_lo"] > base_wr,
             "edge": f["edge"], "candidate": False}
            for f in acc["factors"]
        ]
        candidates = [
            {"factor": c["factor"], "n": c["n"], "win_rate": c["win_rate"],
             "win_rate_lo": c["win_rate_lo"],
             "significant": c["edge"] >= min_edge and c["win_rate_lo"] > base_wr,
             "edge": c["edge"], "candidate": True}
            for c in acc["candidates"]
        ]
        # `best` HANYA dari faktor signifikan: point-estimate tanpa gerbang
        # signifikansi tak layak dipromosikan sebagai "yang terbaik" (W-0021).
        best_pool = [x for x in (factors + candidates) if x["significant"]]
        best = max(best_pool, key=lambda x: x["edge"], default=None)
        tr = bt.trades
        pf = float(bt.profit_factor) if math.isfinite(bt.profit_factor) else None
        avg_bars = float(tr["bars"].mean()) if not tr.empty else 0.0
        trade_sufficient = bt.n_trades >= min_n and pf is not None
        # Timeout-dominated: trade rata-rata keluar persis di batas `max_hold`
        # (mis. horizon=1) ⇒ populasi didominasi TIMEOUT, bukan TP/SL.
        timeout_dominated = bool(bt.n_trades > 0 and avg_bars >= h - 1e-9)
        has_sig = bool(best_pool)
        reliability = _reliability_level(
            has_sig=has_sig,
            fwd_samples=acc["samples"],
            trade_sufficient=trade_sufficient,
            timeout_dominated=timeout_dominated,
            min_n=min_n,
        )

        rows.append({
            "horizon": h,
            "factors": factors,
            "candidates": candidates,
            "forward": {
                "win_rate": acc["base_win_rate"],
                "avg_ret": acc["base_avg_ret"],
                "median_ret": acc["base_median_ret"],
                "samples": acc["samples"],
                "best_factor": best["factor"] if best else None,
                "best_edge": best["edge"] if best else None,
            },
            "trade": {
                "n_trades": bt.n_trades,
                "win_rate": bt.win_rate if bt.n_trades else None,
                "profit_factor": pf,
                "expectancy": bt.expectancy if bt.n_trades else None,
                "avg_bars": avg_bars,
                "sufficient": trade_sufficient,
            },
            "reliability": {
                "level": reliability,
                "has_significant": has_sig,
                "forward_samples": int(acc["samples"]),
                "trade_sufficient": trade_sufficient,
                "timeout_dominated": timeout_dominated,
            },
        })

    # Agregasi lintas horizon (W-0017 lanjutan): mana indikator yang konsisten
    # edge>0 di SELURUH horizon. `consistent` HANYA True bila hadir di semua `hs`
    # (n_horizons == len(hs)) ∧ minimal 2 horizon ∧ edge>0 di tiap horizon —
    # mencegah faktor sampel kecil (absen di horizon lain) diklaim "stabil".
    stability: dict[str, dict] = {}
    for row in rows:
        h = row["horizon"]
        for entry in list(row["factors"]) + list(row["candidates"]):
            st = stability.setdefault(entry["factor"], {
                "factor": entry["factor"],
                "candidate": entry["candidate"],
                "horizons": [],
                "sum_w": 0.0,
                "sum_edge_w": 0.0,
                "edges": [],
                "n_positive_edge": 0,
                "n_significant": 0,
            })
            st["horizons"].append(h)
            st["sum_w"] += entry["n"]
            st["sum_edge_w"] += entry["edge"] * entry["n"]
            st["edges"].append(entry["edge"])
            if entry["edge"] > 0:
                st["n_positive_edge"] += 1
            if entry["significant"]:
                st["n_significant"] += 1

    indicator_stability: list[dict] = []
    for st in stability.values():
        n_horizons = len(st["horizons"])
        avg_edge = (st["sum_edge_w"] / st["sum_w"]) if st["sum_w"] else 0.0
        indicator_stability.append({
            "factor": st["factor"],
            "candidate": st["candidate"],
            "n_horizons": n_horizons,
            "n_positive_edge": st["n_positive_edge"],
            "n_significant": st["n_significant"],
            "avg_edge": avg_edge,
            "min_edge": min(st["edges"]),
            "max_edge": max(st["edges"]),
            "consistent": (n_horizons == len(hs) and n_horizons >= 2
                           and st["n_positive_edge"] == n_horizons),
        })
    indicator_stability.sort(key=lambda x: x["avg_edge"], reverse=True)

    return {"horizons": hs, "min_n": int(min_n), "rows": rows,
            "indicator_stability": indicator_stability,
            "band_verdict": horizon_band_verdict(rows)}


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
