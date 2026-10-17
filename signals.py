from __future__ import annotations

import logging
from dataclasses import dataclass, field
from math import floor

import numpy as np
import pandas as pd

from config import settings
from indicators import (
    add_indicators,
    divergence,
    fib_levels,
    rsi_divergence,
    supply_demand_zones,
    swing_points,
    volume_profile,
)

from factors import (
    CANDIDATE_FACTORS,
    CANDIDATE_LABELS,
    FACTOR_KEYS,
    candidate_frame,
    confluence_frame,
    score_frame,
)

_log = logging.getLogger("laumology.signals")


def support_resistance(d: pd.DataFrame) -> tuple[float, float]:
    price = float(d["Close"].iloc[-1])
    hi_flags, lo_flags = swing_points(d["High"], d["Low"], order=3)
    highs = d.loc[hi_flags, "High"]
    lows = d.loc[lo_flags, "Low"]
    above = highs[highs > price]
    below = lows[lows < price]
    resistance = float(above.min()) if not above.empty else float(d["High"].tail(20).max())
    support = float(below.max()) if not below.empty else float(d["Low"].tail(20).min())
    return support, resistance


def weekly_trend(df: pd.DataFrame) -> str:
    try:
        weekly = df["Close"].resample("W").last().dropna()
        if len(weekly) < 12:
            return "Netral"
        ma = weekly.rolling(10).mean()
        last, m = float(weekly.iloc[-1]), float(ma.iloc[-1])
        rising = float(weekly.iloc[-1]) > float(weekly.iloc[-5])
        falling = float(weekly.iloc[-1]) < float(weekly.iloc[-5])
        if last > m and rising:
            return "Bullish"
        if last < m and falling:
            return "Bearish"
        return "Netral"
    except Exception:
        return "Netral"


def monthly_trend(df: pd.DataFrame) -> str:
    try:
        try:
            monthly = df["Close"].resample("ME").last().dropna()
        except (ValueError, KeyError):
            monthly = df["Close"].resample("M").last().dropna()
        if len(monthly) < 6:
            return "Netral"
        ma = monthly.rolling(6).mean()
        last, m = float(monthly.iloc[-1]), float(ma.iloc[-1])
        rising = last > float(monthly.iloc[-2])
        falling = last < float(monthly.iloc[-2])
        if last > m and rising:
            return "Bullish"
        if last < m and falling:
            return "Bearish"
        return "Netral"
    except Exception:
        return "Netral"


def relative_strength(df: pd.DataFrame) -> tuple[float | None, bool | None]:
    try:
        import data as datamod

        bench = datamod.get_ohlcv(
            settings.benchmark, suffix=settings.benchmark_suffix, period=settings.period
        )
        b = bench["Close"].reindex(df.index).ffill()
        rs = df["Close"] / b
        if len(rs.dropna()) < 25:
            return None, None
        rs_ma = rs.rolling(20).mean()
        change = float(rs.iloc[-1] / rs.iloc[-21] - 1.0) * 100.0
        return change, bool(rs.iloc[-1] > rs_ma.iloc[-1])
    except Exception:
        return None, None


_MKT_CACHE: dict = {"ts": 0.0, "regime": "unknown"}


def market_regime() -> str:
    """Regime pasar dari IHSG (uptrend/downtrend/ranging), cache 5 menit.

    Bukti uji: edge faktor jauh lebih baik saat IHSG uptrend, ~0/negatif saat downtrend.
    """
    import time as _t
    now = _t.time()
    age = now - _MKT_CACHE["ts"]
    # Regime valid dipakai hingga 5 menit; "unknown" hanya 60 detik supaya
    # scan tidak menghujani fetch benchmark saat data IHSG tak tersedia.
    if age < 60:
        return _MKT_CACHE["regime"]
    if age < 300 and _MKT_CACHE["regime"] != "unknown":
        return _MKT_CACHE["regime"]
    regime = "unknown"
    try:
        import data as datamod
        b = add_indicators(datamod.get_ohlcv(
            settings.benchmark, suffix=settings.benchmark_suffix, period=settings.period))
        c = float(b["Close"].iloc[-1])
        ma20 = float(b["ma20"].iloc[-1])
        ma50 = float(b["ma50"].iloc[-1])
        if c > ma50 and ma20 > ma50:
            regime = "uptrend"
        elif c < ma50:
            regime = "downtrend"
        else:
            regime = "ranging"
    except Exception:
        regime = "unknown"
    _MKT_CACHE.update(ts=now, regime=regime)
    return regime


@dataclass
class Analysis:
    ticker: str
    price: float
    change_1d: float
    signal: str
    action: str
    score: int
    confidence: int
    grade: str
    trend: str
    weekly_trend: str
    regime: str

    entry: float
    entry_pullback: float
    entry_breakout: float
    buy_zone_low: float
    buy_zone_high: float

    stop_loss: float
    stop_trail: float
    tp1: float
    tp2: float
    tp3: float
    rr1: float
    rr2: float
    rr3: float

    atr: float
    atr_pct: float
    rsi: float
    stoch_k: float
    macd_hist: float
    adx: float
    plus_di: float
    minus_di: float
    cci: float
    mfi: float
    cmf: float
    vol_ratio: float
    ret_20d: float

    support: float
    resistance: float
    pivot: dict = field(default_factory=dict)
    fib: dict = field(default_factory=dict)

    rs_change: float | None = None
    rs_strong: bool | None = None
    st_dir_up: bool = True

    squeeze_on: bool = False
    squeeze_mom: float = 0.0
    chop: float = 50.0
    adr_pct: float = 0.0
    atr_pctl: float = 50.0
    avwap: float = 0.0
    vol_regime: str = "Normal"
    monthly_trend: str = "Netral"
    mtf: str = "Campuran"
    hma20: float = 0.0
    kama: float = 0.0
    aroon_up: float = 0.0
    aroon_down: float = 0.0
    vortex_plus: float = 0.0
    vortex_minus: float = 0.0
    ao: float = 0.0
    uo: float = 0.0
    rvol: float = 0.0
    psar: float = 0.0
    psar_up: bool = False
    ema50: float = 0.0
    bb_pct: float = 0.5
    ha_bull: bool = False
    vp: dict = field(default_factory=dict)
    zones: list = field(default_factory=list)

    lots: int = 0
    position_value: float = 0.0
    max_loss: float = 0.0
    risk_amount: float = 0.0

    patterns: list = field(default_factory=list)
    divergences: list = field(default_factory=list)
    checklist: list = field(default_factory=list)
    components: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    score_heuristic: int = 0
    score_opt: float | None = None
    prob_up: float | None = None
    model_used: bool = False
    market_regime: str = "unknown"
    decision: dict = field(default_factory=dict)
    stock: dict = field(default_factory=dict)

    def as_row(self) -> dict:
        return {
            "Ticker": self.ticker,
            "Price": round(self.price, 2),
            "Signal": self.signal,
            "Action": self.action,
            "Score": self.score,
            "Conf": self.confidence,
            "Grade": self.grade,
            "Trend": self.trend,
            "Wk": self.weekly_trend,
            "ADX": round(self.adx, 1),
            "ST": "UP" if self.st_dir_up else "DN",
            "RSI": round(self.rsi, 1),
            "Vol": round(self.vol_ratio, 2),
            "Entry": round(self.entry, 2),
            "SL": round(self.stop_loss, 2),
            "TP1": round(self.tp1, 2),
            "TP2": round(self.tp2, 2),
            "RR": round(self.rr2, 2),
            "ATR%": round(self.atr_pct, 2),
            "Sqz": "ON" if self.squeeze_on else "OFF",
            "SqzMom": round(self.squeeze_mom, 1),
            "Chop": round(self.chop, 1),
            "ADR%": round(self.adr_pct, 2),
            "MTF": self.mtf,
            "Decision": (self.decision or {}).get("direction", ""),
            "Buyable": bool((self.decision or {}).get("direction") in ("BUY", "ACCUMULATE")),
            "NoTrade": bool((self.decision or {}).get("no_trade")),
            "Conf2": (self.decision or {}).get("confidence"),
            "POC": round(self.vp.get("poc", 0.0), 2) if self.vp else 0.0,
            "VAH": round(self.vp.get("vah", 0.0), 2) if self.vp else 0.0,
            "VAL": round(self.vp.get("val", 0.0), 2) if self.vp else 0.0,
        }


def _trend_label(d: pd.DataFrame) -> str:
    c = float(d["Close"].iloc[-1])
    ma20, ma50, ma200 = (float(d[k].iloc[-1]) for k in ("ma20", "ma50", "ma200"))
    if c > ma20 > ma50 > ma200:
        return "Uptrend Kuat"
    if c > ma50 > ma200:
        return "Uptrend"
    if c < ma50 < ma200:
        return "Downtrend"
    return "Sideways"


def _grade(score: int, confidence: int, uptrend: bool) -> str:
    if score >= 85 and confidence >= 70 and uptrend:
        return "A+"
    if score >= 78 and confidence >= 60 and uptrend:
        return "A"
    if score >= 65 and confidence >= 50:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _action(score: int, uptrend: bool, extended: bool, breakout: bool) -> tuple[str, str]:
    if score >= settings.strong_buy_score and uptrend:
        if extended:
            return "STRONG BUY", "BELI BERTAHAP (PULLBACK)"
        return "STRONG BUY", "BELI SEKARANG / BREAKOUT"
    if score >= settings.buy_score and uptrend:
        if breakout:
            return "BUY", "BELI BREAKOUT"
        if extended:
            return "BUY", "BELI SAAT PULLBACK"
        return "BUY", "BELI SEKARANG"
    if uptrend and score >= 50:
        return "ACCUMULATE", "AKUMULASI BERTAHAP"
    if score <= 25:
        return "AVOID", "HINDARI / TUNGGU"
    if score <= settings.sell_score:
        return "SELL", "REDUCE / JUAL"
    if not uptrend:
        return "HOLD", "TUNGGU KONFIRMASI"
    return "HOLD", "TAHAN"


@dataclass
class _Ranked:
    signal: str

    @property
    def rank(self) -> int:
        return {
            "STRONG BUY": 5, "BUY": 4, "ACCUMULATE": 3, "HOLD": 2,
            "SELL": 1, "AVOID": 0,
        }.get(self.signal, 0)


def analyze(df: pd.DataFrame, ticker: str = "", light: bool = False,
            d: pd.DataFrame | None = None) -> Analysis:
    if d is None:
        d = add_indicators(df)
    else:
        d = d.copy()  # isolasi: jangan mutasi objek yang mungkin dibagi antar-endpoint
    d = d.dropna(subset=["ma50", "ma200", "atr", "supertrend"])
    if d.empty or len(d) < 2:
        raise ValueError(f"Data tidak cukup untuk {ticker}")
    d.index = pd.to_datetime(d.index)

    sc = score_frame(d)
    cf = confluence_frame(d)
    last = d.iloc[-1]
    srow = sc.iloc[-1]
    crow = cf.iloc[-1]

    price = float(last["Close"])
    prev = float(d["Close"].iloc[-2])
    change_1d = (price / prev - 1.0) * 100.0 if prev else 0.0
    atr_val = float(last["atr"])
    atr_pct = float(last["atr_pct"])
    rsi_val = float(last["rsi"])

    support, resistance = support_resistance(d)
    piv = {
        "pp": float(last["pivot_pp"]), "r1": float(last["pivot_r1"]), "s1": float(last["pivot_s1"]),
        "r2": float(last["pivot_r2"]), "s2": float(last["pivot_s2"]),
        "r3": float(last["pivot_r3"]), "s3": float(last["pivot_s3"]),
    }

    recent = d.tail(90)
    swing_low = float(recent["Low"].min())
    swing_high = float(recent["High"].max())
    fib = fib_levels(swing_low, swing_high)

    vp = volume_profile(d["High"], d["Low"], d["Close"], d["Volume"], bins=24,
                        lookback=min(120, len(d)))
    zones = [] if light else supply_demand_zones(d, lookback=min(120, len(d)), order=3)
    avwap_val = float(last["avwap"]) if np.isfinite(last["avwap"]) else price
    chop_val = float(last["chop"]) if np.isfinite(last["chop"]) else 50.0
    adr_pct = float(last["adr_pct"]) if np.isfinite(last["adr_pct"]) else 0.0
    atr_pctl = float(last["atr_pctl"]) if np.isfinite(last["atr_pctl"]) else 50.0

    sup_pool = [support, avwap_val] + [x for x in (vp["val"], vp["poc"]) if x and x < price]
    res_pool = [resistance] + [x for x in (vp["vah"], vp["poc"]) if x and x > price]
    sup_below = [x for x in sup_pool if x and x < price]
    res_above = [x for x in res_pool if x and x > price]
    if sup_below:
        support = max(sup_below)
    if res_above:
        resistance = min(res_above)

    trend = _trend_label(d)
    w_trend = weekly_trend(df)
    m_trend = monthly_trend(df)
    uptrend = trend in ("Uptrend", "Uptrend Kuat") or (last["st_dir"] == 1 and price > float(last["ma50"]))

    if w_trend == "Bullish" and m_trend == "Bullish":
        mtf = "Selaras Bullish"
    elif w_trend == "Bearish" and m_trend == "Bearish":
        mtf = "Selaras Bearish"
    elif w_trend == "Bullish" or m_trend == "Bullish":
        mtf = "Sebagian Bullish"
    elif w_trend == "Bearish" or m_trend == "Bearish":
        mtf = "Sebagian Bearish"
    else:
        mtf = "Campuran"

    adx_val = float(last["adx"])
