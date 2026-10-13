from __future__ import annotations

import math

import numpy as np
import pandas as pd

import data
import screener
from backtest import _simulate
from config import settings
from indicators import add_indicators
from signals import score_frame


def _prepared(df: pd.DataFrame):
    d = add_indicators(df)
    sc = score_frame(d)
    d = d.join(sc[["score"]]).dropna(subset=["ma50", "atr", "cmf", "mfi", "obv"])
    if len(d) < 60:
        return None
    return d


def _votes(d: pd.DataFrame):
    tech = np.clip((d["score"].to_numpy(dtype=float) - 50.0) / 30.0, -1.0, 1.0)
    cmf = d["cmf"].to_numpy(dtype=float)
    mfi = d["mfi"].to_numpy(dtype=float)
    obv = d["obv"].to_numpy(dtype=float)
    obvma = d["obv_ma20"].to_numpy(dtype=float)
    band = np.zeros(len(d))
    band += np.where(cmf > 0.03, 1.0, 0.0) + np.where(cmf < -0.03, -1.0, 0.0)
    band += np.where(mfi > 55, 1.0, 0.0) + np.where(mfi < 45, -1.0, 0.0)
    band += np.where(obv > obvma, 1.0, -1.0)
    return tech, np.clip(band / 3.0, -1.0, 1.0)


def _run(d: pd.DataFrame, wt: float, wb: float, thr: float,
         tp_rr: float, sl_mult: float, max_hold: int) -> dict:
    tech, band = _votes(d)
    cons = wt * tech + wb * band
    pseudo = (cons + 1.0) * 50.0
    min_score = (thr + 1.0) * 50.0
    return _simulate(
        d["Open"].to_numpy(dtype=float), d["High"].to_numpy(dtype=float),
        d["Low"].to_numpy(dtype=float), d["Close"].to_numpy(dtype=float),
        d["atr"].to_numpy(dtype=float), pseudo, d["ma50"].to_numpy(dtype=float),
        min_score, tp_rr, sl_mult, max_hold,
        fee_buy=settings.fee_buy_pct / 100.0,
        fee_sell=settings.fee_sell_pct / 100.0,
        slip=settings.slippage_pct / 100.0,
    )


def optimize_weights(universe: str = "idx30", tp_rr: float = 3.0,
                     sl_mult: float = 2.0, max_hold: int | None = None) -> dict:
    max_hold = max_hold if max_hold is not None else settings.swing_horizon_days
    tickers = screener.resolve_watchlist(universe)
    prepared = {}
    for t in tickers:
        try:
            d = _prepared(data.get_ohlcv(t))
            if d is not None:
                prepared[t] = d
        except Exception:
            continue
    if not prepared:
        raise ValueError("Tidak ada data untuk universe ini")

    combos = [(0.5, 0.5), (0.6, 0.4), (0.7, 0.3), (0.4, 0.6), (0.3, 0.7), (0.8, 0.2), (0.2, 0.8)]
    thresholds = [0.3, 0.4, 0.5]
    leaderboard = []
    for wt, wb in combos:
        for thr in thresholds:
            rets, pfs, wins, trades = [], [], [], 0
            for d in prepared.values():
                s = _run(d, wt, wb, thr, tp_rr, sl_mult, max_hold)
                rets.append(s["total_return"])
                win = s["win_rate"]
                wins.append(win)
                trades += s["n_trades"]
                if s["profit_factor"] is not None:
                    pfs.append(min(s["profit_factor"], 10.0))
            leaderboard.append({
                "w_technical": wt,
                "w_bandarmologi": wb,
                "threshold": thr,
                "mean_return": round(float(np.mean(rets)) * 100.0, 2),
                "median_return": round(float(np.median(rets)) * 100.0, 2),
                "mean_win_rate": round(float(np.mean(wins)), 3),
                "mean_pf": round(float(np.mean(pfs)), 2) if pfs else None,
                "trades": trades,
            })

    leaderboard.sort(key=lambda x: (x["mean_return"], x["mean_pf"] or 0), reverse=True)
    return {
        "universe": universe,
        "tickers": len(prepared),
        "tested": len(leaderboard),
        "best": leaderboard[0] if leaderboard else None,
        "leaderboard": leaderboard,
        "note": ("Bobot fundamental & sentimen tidak dioptimasi historis (data tidak tersedia "
                 "per tanggal). Rasio technical:bandarmologi disarankan dari uji ini; "
                 "skala sisanya proporsional."),
    }
