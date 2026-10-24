"""Uji edge indikator: event study kausal + stabilitas walk-forward per semester.

Aturan anti-bias (WAJIB dibaca sebelum memodifikasi file ini):
- Semua event didefinisikan a priori di EVENT_RULES. JANGAN menyetel
  threshold setelah melihat hasil — itu overfitting, bukan edge.
- Bar pemanasan dibuang: butuh kolom bar_count >= 250 (branch ini punya),
  atau posisi bar >= 250 sebagai fallback. Indikator jendela panjang
  (ma200, hi52_pct) tidak valid sebelum itu.
- Forward return hanya untuk evaluasi riset. Jangan pernah dipakai
  sebagai input sinyal/skor (itu look-ahead).
- Event dengan sampel < min_count tidak diperingkat: tidak signifikan.
- Untuk event arah turun (dir=-1), "hit" = harga turun setelah event.

Pemakaian:
    python indicator_edge.py --list lq45
    python indicator_edge.py --list lq45 --horizon 10 --top 25 --out edge_report.json
"""
from __future__ import annotations

import argparse
import json
import logging
import time

import numpy as np
import pandas as pd

import data
import screener
from indicators import add_indicators

_log = logging.getLogger("laumology.indicator_edge")

# (nama, kolom acuan, arah, ekspresi boolean) — a priori, jangan dituning.
EVENT_RULES: list[tuple[str, int, object]] = [
    ("rsi_oversold", +1, lambda i: i["rsi"] < 30),
    ("rsi_overbought", -1, lambda i: i["rsi"] > 70),
    ("macd_hist_pos", +1, lambda i: i["macd_hist"] > 0),
    ("macd_bull_cross", +1, lambda i: (i["macd_hist"] > 0) & (i["macd_hist"].shift(1) <= 0)),
    ("macd_bear_cross", -1, lambda i: (i["macd_hist"] < 0) & (i["macd_hist"].shift(1) >= 0)),
    ("bb_lower_touch", +1, lambda i: i["Close"] <= i["bb_lower"]),
    ("bb_upper_touch", -1, lambda i: i["Close"] >= i["bb_upper"]),
    ("squeeze_bull_release", +1, lambda i: i["squeeze_off"] & (i["sqz_mom"] > 0) & (i["sqz_mom"].shift(1) <= 0)),
    ("chop_trending", +1, lambda i: i["chop"] < 38.2),
    ("chop_choppy", -1, lambda i: i["chop"] > 61.8),
    ("vol_surge", +1, lambda i: i["rvol"] > 2.0),
    ("cp_bullish", +1, lambda i: i["cp_bullish"]),
    ("cp_bearish", -1, lambda i: i["cp_bearish"]),
    ("psar_bull_flip", +1, lambda i: (i["psar_dir"] == 1) & (i["psar_dir"].shift(1) == -1)),
    ("psar_bear_flip", -1, lambda i: (i["psar_dir"] == -1) & (i["psar_dir"].shift(1) == 1)),
    ("near_52w_high", +1, lambda i: i["hi52_pct"] >= 95.0),
    ("z20_high", +1, lambda i: i["z20"] >= 2.0),
    ("z20_low", -1, lambda i: i["z20"] <= -2.0),
    ("obv_slope_pos", +1, lambda i: i["obv_slope"] > 0.0),
    ("dc_breakout", +1, lambda i: i["Close"] >= i["dc_upper"]),
    ("mfi_oversold", +1, lambda i: i["mfi"] < 20.0),
    ("mfi_overbought", -1, lambda i: i["mfi"] > 80.0),
]

WARMUP_BARS = 250


def _hits(fwd: pd.Series, dir_: int) -> pd.Series:
    """Hit = forward return searah dengan prediksi event."""
    return (fwd * dir_ > 0).astype(float)


def _halfyear(ts: pd.Index) -> pd.Series:
    return pd.Series([(t.year, 1 if t.month <= 6 else 2) for t in ts], index=ts, dtype="object")


def evaluate(universe: str = "lq45", horizon: int = 5, min_count: int = 30) -> dict:
    tickers = screener.resolve_watchlist(universe)
    per_event_fwd: dict[str, list[pd.Series]] = {name: [] for name, _, _ in EVENT_RULES}
    all_fwd: list[pd.Series] = []
    n_ok = 0

    for t in tickers:
        try:
            df = data.get_ohlcv(t, period="3y")
            if df is None or len(df) < WARMUP_BARS + horizon + 5:
                continue
            ind = add_indicators(df)
            if "bar_count" in ind.columns:
                valid = ind["bar_count"] >= WARMUP_BARS
            else:
                valid = pd.Series(np.arange(len(ind)) >= WARMUP_BARS, index=ind.index)
            close = ind["Close"]
            fwd = close.shift(-horizon) / close - 1.0
            valid = valid & np.isfinite(fwd)
            if not valid.any():
                continue
            n_ok += 1
            all_fwd.append(fwd[valid])
            for name, _, expr in EVENT_RULES:
                mask = expr(ind).fillna(False) & valid
                if mask.any():
                    per_event_fwd[name].append(fwd[mask])
        except Exception as exc:
            # Degradasi per-ticker terlihat di log; payload tetap jujur lewat
            # tickers_evaluated vs tickers_total (pola batch-48).
            _log.warning("ticker %s dilewati dari evaluasi edge - error: %s",
                         t, exc.__class__.__name__)
            continue

    if not n_ok and tickers:
        _log.warning("event study %s: 0/%d emiten lolos ambang riwayat (> %d bar) - hasil kosong",
                     universe, len(tickers), WARMUP_BARS + horizon + 5)
    pool = pd.concat(all_fwd) if all_fwd else pd.Series(dtype=float)
    base_hit = float((pool > 0).mean()) if len(pool) else 0.0
    base_med = float(pool.median()) if len(pool) else 0.0

    results = []
    for name, dir_, _ in EVENT_RULES:
        chunks = per_event_fwd[name]
        if not chunks:
            continue
        s = pd.concat(chunks)
        n = int(len(s))
        if n < min_count:
            results.append({"event": name, "dir": dir_, "n": n, "ranked": False})
            continue
        hit = float(_hits(s, dir_).mean())
        med = float(s.median() * dir_)
        # stabilitas walk-forward: hit rate per semester, ambil yang terburuk
        halves = _halfyear(s.index)
        grp = _hits(s, dir_).groupby(halves)
        per_half = grp.mean()
        worst = float(per_half.min()) if len(per_half) else 0.0
        n_halves = int(per_half.shape[0])
        results.append({
            "event": name,
            "dir": dir_,
            "n": n,
            "ranked": True,
            f"hit_{horizon}d": round(hit, 4),
            f"med_ret_{horizon}d": round(med, 6),
            "uplift_vs_baseline": round(hit - base_hit, 4),
            "worst_half_hit": round(worst, 4),
            "n_halves": n_halves,
        })

    ranked = [r for r in results if r.get("ranked")]
    ranked.sort(key=lambda r: r["uplift_vs_baseline"], reverse=True)
    skipped = [r["event"] for r in results if not r.get("ranked")]
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "universe": universe,
        "horizon_days": horizon,
        "warmup_bars": WARMUP_BARS,
        "min_count": min_count,
        "tickers_evaluated": n_ok,
        "tickers_total": len(tickers),
        "baseline_hit": round(base_hit, 4),
        "baseline_med_ret": round(base_med, 6),
        "ranking": ranked,
        "skipped_low_sample": skipped,
        "catatan": (
            "Event didefinisikan a priori dan tidak boleh dituning setelah hasil "
            "keluar. Uplift dihitung vs baseline semua bar. worst_half_hit rendah "
            "berarti edge tidak stabil antar periode — jangan dipakai untuk skoring."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="LAUMOLOGY uji edge indikator (event study kausal)")
    ap.add_argument("--list", default="lq45", help="universe: lq45 / idx80 / dst (lihat screener)")
    ap.add_argument("--horizon", type=int, default=5, help="forward return dalam hari bursa (default 5)")
    ap.add_argument("--min-count", type=int, default=30, help="sampel minimum per event (default 30)")
    ap.add_argument("--top", type=int, default=25, help="berapa baris teratas dicetak")
    ap.add_argument("--out", default="edge_report.json", help="file JSON hasil")
    args = ap.parse_args()

    rep = evaluate(args.list, args.horizon, args.min_count)

    print(f"Universe {rep['universe']}: {rep['tickers_evaluated']}/{rep['tickers_total']} emiten dievaluasi")
    print(f"Baseline hit-rate {args.horizon}d: {rep['baseline_hit']*100:.1f}% (semua bar, arah naik)")
    print()
    print(f"{'event':22s} {'n':>6s} {'hit':>7s} {'uplift':>7s} {'worst-half':>11s}")
    for r in rep["ranking"][: args.top]:
        h = r[f"hit_{args.horizon}d"]
        print(f"{r['event']:22s} {r['n']:>6d} {h*100:>6.1f}% {r['uplift_vs_baseline']*100:>+6.1f}% {r['worst_half_hit']*100:>10.1f}%")
    if rep["skipped_low_sample"]:
        print(f"\nDilewati (sampel < {args.min_count}): {', '.join(rep['skipped_low_sample'])}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"\nHasil lengkap: {args.out}")


if __name__ == "__main__":
    main()
