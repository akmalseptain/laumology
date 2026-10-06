from __future__ import annotations

from math import sqrt

import numpy as np


def _returns(curve: list[float]) -> np.ndarray:
    arr = np.asarray(curve, dtype=float)
    if arr.size < 3:
        return np.array([])
    r = np.diff(arr) / arr[:-1]
    return r[np.isfinite(r)]


def risk_metrics(equity_curve: list[float], trade_returns_pct: list[float] | None = None,
                 periods_per_year: int = 252) -> dict:
    out: dict = {}
    r = _returns(equity_curve)
    if r.size:
        mean = float(r.mean())
        std = float(r.std(ddof=1)) if r.size > 1 else 0.0
        downside = r[r < 0]
        dstd = float(downside.std(ddof=1)) if downside.size > 1 else 0.0
        out["sharpe"] = round(mean / std * sqrt(periods_per_year), 2) if std > 0 else 0.0
        out["sortino"] = round(mean / dstd * sqrt(periods_per_year), 2) if dstd > 0 else 0.0
        var95 = float(np.percentile(r, 5))
        cvar = r[r <= var95]
        out["var95"] = round(var95 * 100.0, 2)
        out["cvar95"] = round((float(cvar.mean()) if cvar.size else var95) * 100.0, 2)
        out["ann_vol"] = round(std * sqrt(periods_per_year) * 100.0, 2)
    else:
        out.update(sharpe=0.0, sortino=0.0, var95=0.0, cvar95=0.0, ann_vol=0.0)

    if equity_curve:
        arr = np.asarray(equity_curve, dtype=float)
        peak = np.maximum.accumulate(arr)
        dd = (arr - peak) / peak
        mdd = float(dd.min()) if dd.size else 0.0
        total = float(arr[-1] / arr[0] - 1.0) if arr[0] else 0.0
        out["max_dd"] = round(mdd * 100.0, 2)
        out["calmar"] = round(total / abs(mdd), 2) if mdd < 0 else 0.0

    if trade_returns_pct:
        rets = np.asarray(trade_returns_pct, dtype=float) / 100.0
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        wr = float(len(wins) / len(rets)) if len(rets) else 0.0
        aw = float(wins.mean()) if wins.size else 0.0
        al = float(-losses.mean()) if losses.size else 0.0
        b = aw / al if al > 0 else 0.0
        out["win_rate"] = round(wr, 3)
        out["payoff"] = round(b, 2)
        out["kelly"] = round(wr - (1.0 - wr) / b, 3) if b > 0 else 0.0
        out["expectancy_pct"] = round(float(rets.mean()) * 100.0, 2) if len(rets) else 0.0
    return out
