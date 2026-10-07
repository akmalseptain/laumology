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
                        "risk_pct": round(position["risk"] / position["entry"] * 100.0, 2),
                        "r_multiple": round((exit_eff - entry_eff) / position["risk"], 2) if position["risk"] else 0.0,
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


def backtest_decision(
    df: pd.DataFrame,
    ticker: str = "",
    max_hold: int = 20,
    tp_rr: float | None = None,
    sl_mult: float | None = None,
    fee_buy: float | None = None,
    fee_sell: float | None = None,
    slip: float | None = None,
) -> BacktestResult:
    """Backtest memakai Decision Engine (structure + regime + filter) vs legacy."""
    from decision import signal_series

    tp_rr = tp_rr if tp_rr is not None else settings.tp2_rr
    sl_mult = sl_mult if sl_mult is not None else settings.atr_sl_mult
    fee_buy = (settings.fee_buy_pct / 100.0) if fee_buy is None else fee_buy
    fee_sell = (settings.fee_sell_pct / 100.0) if fee_sell is None else fee_sell
    slip = (settings.slippage_pct / 100.0) if slip is None else slip

    d = add_indicators(df).dropna(subset=["ma50", "atr"])
    if len(d) < 30:
        raise ValueError(f"Data terlalu pendek untuk backtest-decision {ticker}")

    regime = None
    try:
        from validation import _benchmark_regime
        _p = "5y" if len(d) > 1000 else ("2y" if len(d) > 500 else "1y")
        regime = _benchmark_regime(period=_p).reindex(d.index).ffill()
    except Exception:
        regime = None
    sig = signal_series(d, regime=regime).to_numpy(dtype=int)
    open_ = d["Open"].to_numpy(dtype=float)
    high = d["High"].to_numpy(dtype=float)
    low = d["Low"].to_numpy(dtype=float)
    close = d["Close"].to_numpy(dtype=float)
    atr_v = d["atr"].to_numpy(dtype=float)
    ma50 = d["ma50"].to_numpy(dtype=float)
    dates = d.index

    position = None
    trades = []
    equity = 1.0
    curve = [1.0]
    for i in range(1, len(d)):
        if position is None:
            if sig[i - 1] == 1 and close[i] > ma50[i]:
                entry = open_[i]
                risk = sl_mult * atr_v[i - 1]
                position = {"entry": entry, "sl": entry - risk, "tp": entry + tp_rr * risk,
                            "i": i, "risk": risk}
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
                trades.append({"entry_date": dates[position["i"]], "exit_date": dates[i],
                               "entry": round(position["entry"], 2), "exit": round(exit_price, 2),
                               "bars": i - position["i"], "reason": reason,
                               "return_pct": round(ret * 100.0, 2),
                               "risk_pct": round(position["risk"] / position["entry"] * 100.0, 2),
                               "r_multiple": round((exit_eff - entry_eff) / position["risk"], 2) if position["risk"] else 0.0})
                position = None
        curve.append(equity)

    buy_hold = close[-1] / close[0] - 1.0
    tdf = pd.DataFrame(trades)
    curve_out = [round(float(x), 4) for x in curve]
    dates_out = [str(x)[:10] for x in dates]
    if tdf.empty:
        return BacktestResult(ticker.upper(), 0.0, buy_hold, 0, 0.0, 0.0, 0.0, 0.0, 0.0, tdf, curve_out, dates_out)
    rets = tdf["return_pct"].to_numpy() / 100.0
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    gw = wins.sum() if wins.size else 0.0
    gl = -losses.sum() if losses.size else 0.0
    pf = gw / gl if gl > 0 else float("inf")
    arr = np.array(curve)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return BacktestResult(
        ticker=ticker.upper(), total_return=equity - 1.0, buy_hold_return=buy_hold,
        n_trades=len(tdf), win_rate=float(len(wins) / len(tdf)),
        avg_win=float(wins.mean()) if wins.size else 0.0,
        avg_loss=float(losses.mean()) if losses.size else 0.0,
        profit_factor=pf, max_drawdown=float(dd.min()) if dd.size else 0.0,
        expectancy=float(rets.mean()), trades=tdf, equity_curve=curve_out, dates=dates_out,
    )


def _pack(r: BacktestResult) -> dict:
    import metrics

    tr = r.trades
    trades = [t.get("return_pct") for t in tr.to_dict("records")] if not tr.empty else []
    tp = sl = to = 0
    avg_bars = 0.0
    if not tr.empty:
        reasons = tr["reason"].tolist()
        tp = reasons.count("TP")
        sl = reasons.count("SL")
        to = reasons.count("TIMEOUT")
        avg_bars = float(tr["bars"].mean())
    return {
        "total_return": r.total_return, "buy_hold": r.buy_hold_return, "n_trades": r.n_trades,
        "win_rate": r.win_rate, "profit_factor": (r.profit_factor if math.isfinite(r.profit_factor) else None),
        "max_drawdown": r.max_drawdown, "expectancy": r.expectancy,
        "avg_win": r.avg_win, "avg_loss": r.avg_loss,
        "tp_hits": tp, "sl_hits": sl, "timeouts": to,
        "tp_rate": (tp / r.n_trades) if r.n_trades else 0.0,
        "sl_rate": (sl / r.n_trades) if r.n_trades else 0.0,
        "timeout_rate": (to / r.n_trades) if r.n_trades else 0.0,
        "avg_bars": round(avg_bars, 1),
        "risk": metrics.risk_metrics(r.equity_curve, trades),
    }


def compare_backtest(df: pd.DataFrame, ticker: str = "", **kwargs) -> dict:
    """Bandingkan sistem legacy (skor) vs Decision Engine pada data sama."""
    legacy = backtest(df, ticker, **kwargs)
    decision = backtest_decision(df, ticker, **kwargs)
    return {"ticker": ticker.upper(), "legacy": _pack(legacy), "decision": _pack(decision)}


def compare_universe(tickers: list[str], **kwargs) -> dict:
    """A/B lintas emiten: agregat legacy vs Decision Engine (win-rate, PF, expectancy, DD)."""
    import data as datamod

    acc = {"legacy": {"n": 0, "wins": 0, "gw": 0.0, "gl": 0.0, "exp": [], "ret": [], "dd": [],
                      "tp": 0, "sl": 0, "to": 0, "bars": [], "r": [], "max_cl": 0, "max_cw": 0},
           "decision": {"n": 0, "wins": 0, "gw": 0.0, "gl": 0.0, "exp": [], "ret": [], "dd": [],
                        "tp": 0, "sl": 0, "to": 0, "bars": [], "r": [], "max_cl": 0, "max_cw": 0}}
    used = 0
    errors: list[dict] = []
    for t in tickers:
        try:
            df = datamod.get_ohlcv(t)
            if len(df) < 120:
                errors.append({"ticker": t.upper(), "error": "data kurang"})
                continue
            used += 1
            for name, res in (("legacy", backtest(df, t, **kwargs)),
                              ("decision", backtest_decision(df, t, **kwargs))):
                if res.trades.empty:
                    continue
                tr = res.trades
                rets = tr["return_pct"].to_numpy() / 100.0
                w = rets[rets > 0]
                losses = rets[rets <= 0]
                a = acc[name]
                a["n"] += len(rets)
                a["wins"] += len(w)
                a["gw"] += float(w.sum())
                a["gl"] += float(-losses.sum())
                a["exp"].append(float(rets.mean()))
                a["ret"].append(res.total_return)
                a["dd"].append(res.max_drawdown)
                a["bars"].extend(tr["bars"].tolist())
                if "r_multiple" in tr.columns:
                    rvals = tr["r_multiple"].tolist()
                    a["r"].extend(rvals)
                    cl = cw = 0
                    for rv in rvals:
                        if rv <= 0:
                            cl += 1
                            cw = 0
                        else:
                            cw += 1
                            cl = 0
                        a["max_cl"] = max(a["max_cl"], cl)
                        a["max_cw"] = max(a["max_cw"], cw)
                rs = tr["reason"].tolist()
                a["tp"] += rs.count("TP")
                a["sl"] += rs.count("SL")
                a["to"] += rs.count("TIMEOUT")
        except Exception as exc:  # noqa: BLE001
            errors.append({"ticker": t.upper(), "error": str(exc)})

    def summarize(a: dict) -> dict:
        pf = (a["gw"] / a["gl"]) if a["gl"] > 0 else None
        import statistics
        return {
            "n_trades": a["n"],
            "win_rate": round(a["wins"] / a["n"], 4) if a["n"] else 0.0,
            "profit_factor": round(pf, 3) if pf is not None else None,
            "expectancy_pct": round(float(np.mean(a["exp"])) * 100.0, 3) if a["exp"] else 0.0,
            "avg_return_pct": round(float(np.mean(a["ret"])) * 100.0, 2) if a["ret"] else 0.0,
            "avg_max_dd_pct": round(float(np.mean(a["dd"])) * 100.0, 2) if a["dd"] else 0.0,
            "avg_r": round(float(np.mean(a["r"])), 3) if a["r"] else 0.0,
            "median_r": round(float(statistics.median(a["r"])), 3) if a["r"] else 0.0,
            "best_r": round(float(max(a["r"])), 2) if a["r"] else 0.0,
            "worst_r": round(float(min(a["r"])), 2) if a["r"] else 0.0,
            "max_consec_losses": int(a["max_cl"]),
            "max_consec_wins": int(a["max_cw"]),
            "tp_rate": round(a["tp"] / a["n"], 3) if a["n"] else 0.0,
            "sl_rate": round(a["sl"] / a["n"], 3) if a["n"] else 0.0,
            "timeout_rate": round(a["to"] / a["n"], 3) if a["n"] else 0.0,
            "avg_bars": round(float(np.mean(a["bars"])) if a["bars"] else 0.0, 1),
        }

    return {"n_tickers": used, "legacy": summarize(acc["legacy"]),
            "decision": summarize(acc["decision"]), "errors": errors}
