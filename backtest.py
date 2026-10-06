from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config import settings
from indicators import add_indicators
from signals import score_frame


@dataclass
class BacktestResult:
    ticker: str
    total_return: float
    buy_hold_return: float
    n_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    expectancy: float
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    equity_curve: list = field(default_factory=list)
    dates: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.ticker:>8} | Return {self.total_return*100:6.1f}% | "
            f"B&H {self.buy_hold_return*100:6.1f}% | Trades {self.n_trades:3d} | "
            f"Win {self.win_rate*100:4.0f}% | PF {self.profit_factor:4.2f} | "
            f"MDD {self.max_drawdown*100:5.1f}%"
        )


def backtest(
    df: pd.DataFrame,
    ticker: str = "",
    min_score: int | None = None,
    max_hold: int = 20,
    tp_rr: float | None = None,
    sl_mult: float | None = None,
    fee_buy: float | None = None,
    fee_sell: float | None = None,
    slip: float | None = None,
) -> BacktestResult:
    min_score = min_score if min_score is not None else settings.buy_score
    tp_rr = tp_rr if tp_rr is not None else settings.tp2_rr
    sl_mult = sl_mult if sl_mult is not None else settings.atr_sl_mult
    fee_buy = (settings.fee_buy_pct / 100.0) if fee_buy is None else fee_buy
    fee_sell = (settings.fee_sell_pct / 100.0) if fee_sell is None else fee_sell
    slip = (settings.slippage_pct / 100.0) if slip is None else slip

    d = add_indicators(df)
    sc = score_frame(d)
    d = d.join(sc[["score"]]).dropna(subset=["ma50", "atr"])

    if len(d) < 30:
        raise ValueError(f"Data terlalu pendek untuk backtest {ticker}")

    open_ = d["Open"].to_numpy(dtype=float)
    high = d["High"].to_numpy(dtype=float)
    low = d["Low"].to_numpy(dtype=float)
    close = d["Close"].to_numpy(dtype=float)
    atr_v = d["atr"].to_numpy(dtype=float)
    score = d["score"].to_numpy(dtype=float)
    ma50 = d["ma50"].to_numpy(dtype=float)
    dates = d.index

    entries = np.zeros(len(d), dtype=bool)
    for i in range(1, len(d)):
        if score[i - 1] < min_score <= score[i] and close[i] > ma50[i]:
            entries[i] = True

    position = None
    trades = []
    equity = 1.0
    curve = [1.0]

    for i in range(1, len(d)):
        if position is None:
            if entries[i - 1]:
                entry = open_[i]
                risk = sl_mult * atr_v[i - 1]
                sl = entry - risk
                tp = entry + tp_rr * risk
                position = {
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "risk": risk,
                    "i": i,
                }
        else:
            reason = None
            exit_price = None
            if low[i] <= position["sl"]:
                exit_price, reason = position["sl"], "SL"
            elif high[i] >= position["tp"]:
                exit_price, reason = position["tp"], "TP"
            elif i - position["i"] >= max_hold:
                exit_price, reason = close[i], "TIMEOUT"

            if reason:
                entry_eff = position["entry"] * (1.0 + slip) * (1.0 + fee_buy)
                exit_eff = exit_price * (1.0 - slip) * (1.0 - fee_sell)
                ret = exit_eff / entry_eff - 1.0
                equity *= 1.0 + ret
                trades.append(
                    {
                        "entry_date": dates[position["i"]],
                        "exit_date": dates[i],
                        "entry": round(position["entry"], 2),
                        "exit": round(exit_price, 2),
                        "bars": i - position["i"],
                        "reason": reason,
                        "return_pct": round(ret * 100.0, 2),
                    }
                )
                position = None

        curve.append(equity)

    buy_hold = close[-1] / close[0] - 1.0
    tdf = pd.DataFrame(trades)
    curve_out = [round(float(x), 4) for x in curve]
    dates_out = [str(x)[:10] for x in dates]

    if tdf.empty:
        return BacktestResult(
            ticker=ticker.upper(),
            total_return=0.0,
            buy_hold_return=buy_hold,
            n_trades=0,
            win_rate=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            expectancy=0.0,
            trades=tdf,
            equity_curve=curve_out,
            dates=dates_out,
        )

    rets = tdf["return_pct"].to_numpy() / 100.0
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    gross_win = wins.sum() if wins.size else 0.0
    gross_loss = -losses.sum() if losses.size else 0.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

    curve_arr = np.array(curve)
    peak = np.maximum.accumulate(curve_arr)
    dd = (curve_arr - peak) / peak
    max_dd = float(dd.min()) if dd.size else 0.0

    return BacktestResult(
        ticker=ticker.upper(),
        total_return=equity - 1.0,
        buy_hold_return=buy_hold,
        n_trades=len(tdf),
        win_rate=float(len(wins) / len(tdf)),
        avg_win=float(wins.mean()) if wins.size else 0.0,
        avg_loss=float(losses.mean()) if losses.size else 0.0,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        expectancy=float(rets.mean()),
        trades=tdf,
        equity_curve=curve_out,
        dates=dates_out,
    )


def walkforward(
    df: pd.DataFrame,
    ticker: str = "",
    folds: int = 4,
    **kwargs,
) -> list[dict]:
    """Segment the history into `folds` consecutive out-of-sample windows."""
    n = len(df)
    if n < 60:
        raise ValueError(f"Data terlalu pendek untuk walk-forward {ticker}")
    size = max(n // folds, 20)
    out: list[dict] = []
    for i in range(folds):
        start = i * size
        end = n if i == folds - 1 else min((i + 1) * size, n)
        seg = df.iloc[start:end]
        if len(seg) < 30:
            continue
        try:
            r = backtest(seg, ticker, **kwargs)
            out.append({
                "fold": i + 1,
                "start": str(seg.index[0])[:10],
                "end": str(seg.index[-1])[:10],
                "bars": len(seg),
                "total_return": r.total_return,
                "buy_hold": r.buy_hold_return,
                "n_trades": r.n_trades,
                "win_rate": r.win_rate,
                "profit_factor": (r.profit_factor if math.isfinite(r.profit_factor) else None),
                "max_dd": r.max_drawdown,
            })
        except Exception as exc:
            out.append({"fold": i + 1, "start": str(seg.index[0])[:10], "end": str(seg.index[-1])[:10], "error": str(exc)})
    return out


def _simulate(open_, high, low, close, atr_v, score, ma50,
              min_score, tp_rr, sl_mult, max_hold,
              fee_buy=0.0, fee_sell=0.0, slip=0.0):
    entries = np.zeros(len(close), dtype=bool)
    for i in range(1, len(close)):
        if score[i - 1] < min_score <= score[i] and close[i] > ma50[i]:
            entries[i] = True
    position = None
    trades = []
    equity = 1.0
    curve = [1.0]
    for i in range(1, len(close)):
        if position is None:
            if entries[i - 1]:
                entry = open_[i]
                risk = sl_mult * atr_v[i - 1]
                position = {"entry": entry, "sl": entry - risk, "tp": entry + tp_rr * risk, "i": i, "risk": risk}
        else:
            reason = None
            exit_price = None
            if low[i] <= position["sl"]:
                exit_price, reason = position["sl"], "SL"
            elif high[i] >= position["tp"]:
                exit_price, reason = position["tp"], "TP"
            elif i - position["i"] >= max_hold:
                exit_price, reason = close[i], "TIMEOUT"
            if reason:
                entry_eff = position["entry"] * (1.0 + slip) * (1.0 + fee_buy)
                exit_eff = exit_price * (1.0 - slip) * (1.0 - fee_sell)
                ret = exit_eff / entry_eff - 1.0
                equity *= 1.0 + ret
                trades.append(ret)
                position = None
        curve.append(equity)
    total = equity - 1.0
    bh = close[-1] / close[0] - 1.0
    rets = np.array(trades)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    gross_w = wins.sum() if wins.size else 0.0
    gross_l = -losses.sum() if losses.size else 0.0
    pf = gross_w / gross_l if gross_l > 0 else float("inf")
    arr = np.array(curve)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return {
        "total_return": float(total),
        "buy_hold": float(bh),
        "n_trades": len(trades),
        "win_rate": float(len(wins) / len(rets)) if len(rets) else 0.0,
        "profit_factor": (float(pf) if math.isfinite(pf) else None),
        "max_dd": float(dd.min()) if dd.size else 0.0,
        "expectancy": float(rets.mean()) if len(rets) else 0.0,
    }


def optimize(df: pd.DataFrame, ticker: str = "", max_hold: int = 20,
             min_scores=None, tp_rrs=None, sl_mults=None):
    if min_scores is None:
        min_scores = [55, 60, 65, 70, 75]
    if tp_rrs is None:
        tp_rrs = [2.0, 3.0, 4.0]
    if sl_mults is None:
        sl_mults = [1.5, 2.0, 2.5]
    d = add_indicators(df)
    sc = score_frame(d)
    d = d.join(sc[["score"]]).dropna(subset=["ma50", "atr"])
    if len(d) < 60:
        raise ValueError(f"Data terlalu pendek untuk optimasi {ticker}")
    open_ = d["Open"].to_numpy(dtype=float)
    high = d["High"].to_numpy(dtype=float)
    low = d["Low"].to_numpy(dtype=float)
    close = d["Close"].to_numpy(dtype=float)
    atr_v = d["atr"].to_numpy(dtype=float)
    score = d["score"].to_numpy(dtype=float)
    ma50 = d["ma50"].to_numpy(dtype=float)

    results = []
    for ms in min_scores:
        for tp in tp_rrs:
            for sl in sl_mults:
                s = _simulate(open_, high, low, close, atr_v, score, ma50, ms, tp, sl, max_hold,
                              fee_buy=settings.fee_buy_pct / 100.0,
                              fee_sell=settings.fee_sell_pct / 100.0,
                              slip=settings.slippage_pct / 100.0)
                results.append({
                    "min_score": ms, "tp_rr": tp, "sl_mult": sl, "max_hold": max_hold, **s,
                })
    results.sort(
        key=lambda x: ((x["profit_factor"] or 0.0), x["total_return"], x["expectancy"]),
        reverse=True,
    )
    return {"ticker": ticker.upper(), "tested": len(results), "best": results[0] if results else None, "top": results[:10]}
