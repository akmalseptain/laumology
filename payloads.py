"""Payload builders untuk endpoint analisis & OHLC (dipakai blueprint analysis)."""
from __future__ import annotations

import math

import pandas as pd

import data
import indicators
from signals import analyze

INTERVAL_PERIOD = {
    "1d": "1y",
    "1wk": "5y",
    "1h": "60d",
    "30m": "30d",
    "15m": "20d",
    "5m": "10d",
}


def num_or_none(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def time_formatter(interval: str):
    daily = interval in ("1d", "1wk", "1mo", "3mo")

    def fmt(ts):
        ts = pd.Timestamp(ts)
        if daily:
            return {"year": int(ts.year), "month": int(ts.month), "day": int(ts.day)}
        return int(ts.timestamp())

    return fmt


def analysis_payload(ticker: str, refresh: bool, bars: int, interval: str) -> dict:
    period = INTERVAL_PERIOD.get(interval, "1y")
    df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
    quote = data.get_quote(ticker)
    df, live = data.apply_live_quote(df, quote, interval)
    a = analyze(df, ticker)
    if live:
        a.price = live["price"]
        if live.get("prev_close"):
            a.change_1d = (live["price"] / live["prev_close"] - 1.0) * 100.0
    return {
        "ticker": a.ticker,
        "last_date": df.index[-1].strftime("%d %b %Y %H:%M"),
        "bars": len(df),
        "interval": interval,
        "tv_symbol": "IDX:" + a.ticker,
        "price": a.price,
        "change_1d": a.change_1d,
        "change_20d": a.ret_20d,
        "live": bool(live),
        "quote_source": live.get("source") if live else None,
        "quote_time": live.get("quote_time") if live else None,
        "day_high": live.get("day_high") if live else None,
        "day_low": live.get("day_low") if live else None,
        "signal": a.signal,
        "action": a.action,
        "score": a.score,
        "confidence": a.confidence,
        "grade": a.grade,
        "trend": a.trend,
        "weekly_trend": a.weekly_trend,
        "regime": a.regime,
        "entry": a.entry,
        "entry_pullback": a.entry_pullback,
        "entry_breakout": a.entry_breakout,
        "buy_zone_low": a.buy_zone_low,
        "buy_zone_high": a.buy_zone_high,
        "stop_loss": a.stop_loss,
        "stop_trail": a.stop_trail,
        "tp1": a.tp1,
        "tp2": a.tp2,
        "tp3": a.tp3,
        "rr1": a.rr1,
        "rr2": a.rr2,
        "rr3": a.rr3,
        "risk_pct": (a.entry - a.stop_loss) / a.entry * 100.0 if a.entry else 0.0,
        "atr_pct": a.atr_pct,
        "rsi": a.rsi,
        "stoch_k": a.stoch_k,
        "macd_hist": a.macd_hist,
        "adx": a.adx,
        "plus_di": a.plus_di,
        "minus_di": a.minus_di,
        "cci": a.cci,
        "mfi": a.mfi,
        "cmf": a.cmf,
        "vol_ratio": a.vol_ratio,
        "support": a.support,
        "resistance": a.resistance,
        "pivot": a.pivot,
        "fib": a.fib,
        "rs_change": a.rs_change,
        "rs_strong": a.rs_strong,
        "st_dir_up": a.st_dir_up,
        "lots": a.lots,
        "position_value": a.position_value,
        "max_loss": a.max_loss,
        "risk_amount": a.risk_amount,
        "patterns": a.patterns,
        "divergences": a.divergences,
        "checklist": [{"label": k, "pass": v} for k, v in a.checklist],
        "components": a.components,
        "reasons": a.reasons,
        "warnings": a.warnings,
        "squeeze_on": a.squeeze_on,
        "squeeze_mom": a.squeeze_mom,
        "chop": a.chop,
        "adr_pct": a.adr_pct,
        "atr_pctl": a.atr_pctl,
        "vol_regime": a.vol_regime,
        "avwap": a.avwap,
        "monthly_trend": a.monthly_trend,
        "mtf": a.mtf,
        "hma20": a.hma20,
        "kama": a.kama,
        "aroon_up": a.aroon_up,
        "aroon_down": a.aroon_down,
        "vortex_plus": a.vortex_plus,
        "vortex_minus": a.vortex_minus,
        "ao": a.ao,
        "uo": a.uo,
        "rvol": a.rvol,
        "vp": a.vp,
        "zones": a.zones,
    }


def ohlc_payload(ticker: str, interval: str, bars: int, refresh: bool = False) -> dict:
    period = INTERVAL_PERIOD.get(interval, "1y")
    df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
    quote = data.get_quote(ticker)
    df, live = data.apply_live_quote(df, quote, interval)
    a = analyze(df, ticker)
    if live:
        a.price = live["price"]
        if live.get("prev_close"):
            a.change_1d = (live["price"] / live["prev_close"] - 1.0) * 100.0

    d = indicators.add_indicators(df).tail(bars)
    fmt_time = time_formatter(interval)

    candles: list[dict] = []
    volume: list[dict] = []
    for ts, row in d.iterrows():
        o = num_or_none(row.get("Open"))
        h = num_or_none(row.get("High"))
        low = num_or_none(row.get("Low"))
        c = num_or_none(row.get("Close"))
        if None in (o, h, low, c):
            continue
        t = fmt_time(ts)
        candles.append({"time": t, "open": o, "high": h, "low": low, "close": c})
        vol = num_or_none(row.get("Volume")) or 0.0
        volume.append({"time": t, "value": vol, "color": "#26a69a" if c >= o else "#ef5350"})

    def line(col: str) -> list[dict]:
        out: list[dict] = []
        if col not in d.columns:
            return out
        for ts, v in d[col].items():
            fv = num_or_none(v)
            if fv is None:
                continue
            out.append({"time": fmt_time(ts), "value": round(fv, 4)})
        return out

    st_up: list[dict] = []
    st_down: list[dict] = []
    for ts, row in d.iterrows():
        sv = num_or_none(row.get("supertrend"))
        if sv is None:
            continue
        point = {"time": fmt_time(ts), "value": round(sv, 4)}
        if num_or_none(row.get("st_dir")) == 1.0:
            st_up.append(point)
        else:
            st_down.append(point)

    levels = [
        {"price": a.entry, "color": "#2962ff", "title": "ENTRY"},
        {"price": a.stop_loss, "color": "#d50000", "title": "SL"},
        {"price": a.tp1, "color": "#00c853", "title": "TP1"},
        {"price": a.tp2, "color": "#00a03a", "title": "TP2"},
        {"price": a.tp3, "color": "#00701f", "title": "TP3"},
        {"price": a.vp.get("poc"), "color": "#f5c518", "title": "POC"},
        {"price": a.vp.get("vah"), "color": "#ff8f00", "title": "VAH"},
        {"price": a.vp.get("val"), "color": "#ff8f00", "title": "VAL"},
    ]

    benchmark: list[dict] = []
    try:
        bdf = data.get_ohlcv("^JKSE", suffix="", period=period, interval=interval, use_cache=not refresh)
        b = bdf["Close"].reindex(d.index).ffill()
        c0 = num_or_none(d["Close"].iloc[0])
        b0 = num_or_none(b.iloc[0])
        if c0 and b0:
            scale = c0 / b0
            for ts, v in b.items():
                fv = num_or_none(v)
                if fv is not None:
                    benchmark.append({"time": fmt_time(ts), "value": round(fv * scale, 4)})
    except Exception:
        benchmark = []

    return {
        "ticker": a.ticker,
        "interval": interval,
        "bars": len(candles),
        "live": bool(live),
        "quote_source": live.get("source") if live else None,
        "last_date": df.index[-1].strftime("%d %b %Y %H:%M"),
        "price": a.price,
        "change_1d": a.change_1d,
        "candles": candles,
        "volume": volume,
        "overlays": {
            "ma20": line("ma20"),
            "ma50": line("ma50"),
            "ma200": line("ma200"),
            "ema21": line("ema21"),
            "avwap": line("avwap"),
            "supertrend_up": st_up,
            "supertrend_down": st_down,
        },
        "rsi": line("rsi"),
        "macd": line("macd"),
        "macd_signal": line("macd_signal"),
        "macd_hist": line("macd_hist"),
        "levels": [lv for lv in levels if lv["price"]],
        "benchmark": benchmark,
        "signal": a.signal,
        "action": a.action,
        "score": a.score,
        "confidence": a.confidence,
        "grade": a.grade,
    }
