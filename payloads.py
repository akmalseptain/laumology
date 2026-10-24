"""Payload builders untuk endpoint analisis & OHLC (dipakai blueprint analysis)."""
from __future__ import annotations

import math

import pandas as pd

import data
import external
import indicators
import ttlcache
from config import settings
from signals import analyze
from validate import MAX_STALE_DAYS, check_df

INTERVAL_PERIOD = {
    "1d": "1y",
    "1wk": "5y",
    "1h": "60d",
    "30m": "30d",
    "15m": "20d",
    "5m": "10d",
}

_ENRICH_TTL = 120.0  # detik; key memuat bar terakhir, jadi bar/quote baru otomatis invalid


def _enriched(ticker: str, period: str, interval: str, refresh: bool, df: pd.DataFrame) -> pd.DataFrame:
    """Bagikan satu DataFrame indikator antar endpoint (analyze & ohlc) untuk df identik.

    Key memuat ticker+periode+interval+len+bar terakhir (OHLCV) -> aman thd freshness.
    Selalu kembalikan salinan agar tidak ada endpoint yang memutasi objek bersama.
    """
    if refresh:
        return indicators.add_indicators(df)
    try:
        lr = df.iloc[-1]
        key = "enr:%s:%s:%s:%d:%s:%s:%s:%s:%s:%s" % (
            ticker, period, interval, len(df), df.index[-1],
            lr.get("Open"), lr.get("High"), lr.get("Low"), lr.get("Close"), lr.get("Volume"),
        )
        hit = ttlcache.get(key)
        if hit is not None:
            return hit.copy()
        d = indicators.add_indicators(df)
        ttlcache.set(key, d, _ENRICH_TTL)
        return d.copy()
    except Exception:
        return indicators.add_indicators(df)


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
    fresh_hist = check_df(df)
    quote = data.get_quote(ticker)
    df, live = data.apply_live_quote(df, quote, interval)
    a = analyze(df, ticker, d=_enriched(ticker, period, interval, refresh, df))
    if live:
        a.price = live["price"]
        if live.get("prev_close"):
            a.change_1d = (live["price"] / live["prev_close"] - 1.0) * 100.0
    fresh = check_df(df)
    stale_days = int(fresh_hist.get("stale_days") or 0)
    out = {
        "ticker": a.ticker,
        "last_date": df.index[-1].strftime("%d %b %Y %H:%M"),
        "bars": len(df),
        "interval": interval,
        "horizon": settings.swing_horizon_days,
        "data_freshness": {
            "last_bar": fresh.get("last"),
            "history_last_bar": fresh_hist.get("last"),
            "live_bar": bool(live),
            "stale_days": stale_days,
            "max_stale_days": MAX_STALE_DAYS,
            "fresh": stale_days <= MAX_STALE_DAYS,
            "warnings": fresh.get("warnings", []),
        },
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
        "score_heuristic": a.score_heuristic,
        "score_opt": a.score_opt,
        "prob_up": a.prob_up,
        "model_used": a.model_used,
        "market_regime": a.market_regime,
        "regime_gate": a.regime_gate,
        "market_recovery": a.market_recovery,
        "decision": a.decision,
        "stock": a.stock,
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
        "psar": a.psar,
        "psar_up": a.psar_up,
        "ema50": a.ema50,
        "bb_pct": a.bb_pct,
        "ha_bull": a.ha_bull,
        "vp": a.vp,
        "zones": a.zones,
    }
    # Lapisan penjelasan. Tidak masuk rumus skor (uji: skor tetap sama).
    ext = external.for_stock(
        a.ticker, change_1d=a.change_1d, rs_change=a.rs_change, our_signal=a.signal,
    )
    out["external"] = ext
    # Tidak mengubah skor. Hanya menandai bila jendela indikator belum sah.
    if len(df) < 200:
        out["warnings"] = list(out["warnings"]) + [
            "Riwayat kurang dari 200 bar pada interval ini: MA200 belum penuh, jangan dibaca sebagai rata-rata 200 periode."
        ]
    if interval != "1d":
        out["warnings"] = list(out["warnings"]) + [
            f"Indikator dihitung pada interval {interval}, bukan pada candle harian."
        ]
    if ext.get("status") in (
        "tekanan_luar", "pelemahan_pasar", "tekanan_emiten", "waspada_luar",
    ) and ext.get("summary"):
        out["warnings"] = list(out["warnings"]) + [ext["summary"]]
    return out


def ohlc_payload(ticker: str, interval: str, bars: int, refresh: bool = False) -> dict:
    period = INTERVAL_PERIOD.get(interval, "1y")
    df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
    quote = data.get_quote(ticker)
    df, live = data.apply_live_quote(df, quote, interval)
    d_all = _enriched(ticker, period, interval, refresh, df)
    a = analyze(df, ticker, d=d_all)
    if live:
        a.price = live["price"]
        if live.get("prev_close"):
            a.change_1d = (live["price"] / live["prev_close"] - 1.0) * 100.0

    d = d_all.tail(bars)
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
    psar_up: list[dict] = []
    psar_down: list[dict] = []
    for ts, row in d.iterrows():
        sv = num_or_none(row.get("supertrend"))
        if sv is not None:
            point = {"time": fmt_time(ts), "value": round(sv, 4)}
            if num_or_none(row.get("st_dir")) == 1.0:
                st_up.append(point)
            else:
                st_down.append(point)
        pv = num_or_none(row.get("psar"))
        if pv is not None:
            pp = {"time": fmt_time(ts), "value": round(pv, 4)}
            if num_or_none(row.get("psar_dir")) == 1.0:
                psar_up.append(pp)
            else:
                psar_down.append(pp)

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
            "ema50": line("ema50"),
            "psar_up": psar_up,
            "psar_down": psar_down,
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
