from __future__ import annotations

import pandas as pd

import data
from config import sector_of
from indicators import add_indicators


def _pct(series: pd.Series, n: int) -> float:
    try:
        if len(series) <= n:
            return 0.0
        return float(series.iloc[-1] / series.iloc[-1 - n] - 1.0) * 100.0
    except Exception:
        return 0.0


def ihsg() -> dict:
    try:
        df = data.get_ohlcv("^JKSE", suffix="", period="1y")
        d = add_indicators(df)
        last = d.iloc[-1]
        price = float(last["Close"])
        if price > float(last["ma50"]) and float(last["ma20"]) > float(last["ma50"]):
            regime = "Bullish"
        elif price < float(last["ma50"]):
            regime = "Bearish"
        else:
            regime = "Netral"
        return {
            "price": price,
            "ret_1d": _pct(df["Close"], 1),
            "ret_5d": _pct(df["Close"], 5),
            "ret_20d": _pct(df["Close"], 20),
            "regime": regime,
            "adx": float(last["adx"]),
            "rsi": float(last["rsi"]),
            "st_up": bool(last["st_dir"] == 1),
        }
    except Exception as exc:
        return {"error": str(exc)}


def sector_strength(tickers: list[str]) -> dict:
    """Peta kekuatan sektor (chg_20d, breadth) dari universum, untuk stock layer."""
    out = overview(tickers)
    m: dict = {}
    for s in out.get("sectors", []):
        m[s["sector"]] = {"chg_20d": s["chg_20d"], "breadth": s["breadth"], "n": s["n"]}
    return m


def overview(tickers: list[str]) -> dict:
    above50 = 0
    adv = 0
    dec = 0
    total = 0
    sectors: dict[str, dict] = {}
    rs_rows: list[dict] = []

    for t in tickers:
        try:
            df = data.get_ohlcv(t)
            if len(df) < 60:
                continue
            d = add_indicators(df)
            last = d.iloc[-1]
            price = float(last["Close"])
            chg_1d = _pct(df["Close"], 1)
            chg_5d = _pct(df["Close"], 5)
            chg_20d = _pct(df["Close"], 20)
            total += 1
            if price > float(last["ma50"]):
                above50 += 1
            if chg_1d > 0:
                adv += 1
            elif chg_1d < 0:
                dec += 1

            sec = sector_of(t)
            s = sectors.setdefault(sec, {"n": 0, "sum1d": 0.0, "sum5d": 0.0, "sum20d": 0.0, "above50": 0})
            s["n"] += 1
            s["sum1d"] += chg_1d
            s["sum5d"] += chg_5d
            s["sum20d"] += chg_20d
            if price > float(last["ma50"]):
                s["above50"] += 1

            rs_rows.append({"ticker": t, "sector": sec, "chg_1d": chg_1d, "chg_20d": chg_20d})
        except Exception:
            continue

    heat = [
        {
            "sector": k,
            "n": v["n"],
            "chg_1d": round(v["sum1d"] / v["n"], 2),
            "chg_5d": round(v["sum5d"] / v["n"], 2),
            "chg_20d": round(v["sum20d"] / v["n"], 2),
            "breadth": round(v["above50"] / v["n"] * 100.0, 1),
        }
        for k, v in sectors.items()
    ]
    heat.sort(key=lambda x: x["chg_1d"], reverse=True)
    rs_rows.sort(key=lambda x: x["chg_20d"], reverse=True)

    return {
        "ihsg": ihsg(),
        "breadth": {
            "total": total,
            "above_ma50": above50,
            "pct_above_ma50": round(above50 / total * 100.0, 1) if total else 0.0,
            "advancers": adv,
            "decliners": dec,
        },
        "sectors": heat,
        "rs_ranking": rs_rows[:15],
    }
