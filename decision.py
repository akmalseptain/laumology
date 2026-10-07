"""Decision Engine (layer additive di atas indikator legacy).

Menggabungkan: regime pasar, market structure, momentum, volume, volatilitas,
multi-timeframe, dan validasi risiko -> keputusan BUY/SELL/HOLD/NO TRADE
dengan confidence, entry zone, SL, TP1-3, RR, dan alasan.

Tidak mengubah indikator/sinyal lama; hanya membaca outputnya.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import settings
from structure import market_structure

WEIGHTS = {
    "trend": 25.0,
    "structure": 20.0,
    "momentum": 15.0,
    "volume": 10.0,
    "htf": 15.0,
    "entry": 5.0,
}
_DIR_WEIGHT = sum(WEIGHTS.values())


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


def _last(d: pd.DataFrame, col: str, default: float = 0.0) -> float:
    try:
        v = float(d[col].iloc[-1])
        return v if np.isfinite(v) else default
    except Exception:
        return default


def _direction_component(d: pd.DataFrame, struct: dict) -> dict:
    close = _last(d, "Close")
    ma20, ma50, ma200 = _last(d, "ma20"), _last(d, "ma50"), _last(d, "ma200")
    ema9, ema21 = _last(d, "ema9"), _last(d, "ema21")
    st_dir = _last(d, "st_dir")

    trend = 0.0
    trend += 0.4 if close > ma20 else -0.4
    trend += 0.3 if ma20 > ma50 else -0.3
    trend += 0.3 if ma50 > ma200 else -0.3
    trend += 0.3 if st_dir == 1 else -0.3
    trend += 0.3 if ema9 > ema21 else -0.3
    if close > _last(d, "senkou_a") and close > _last(d, "senkou_b"):
        trend += 0.3
    else:
        trend -= 0.3
    trend = _clamp(trend / 1.9)

    sb = struct.get("bias")
    structure = 1.0 if sb == "bullish" else (-1.0 if sb == "bearish" else 0.0)
    if struct.get("bos") == "bullish":
        structure += 0.2
    elif struct.get("bos") == "bearish":
        structure -= 0.2
    if struct.get("choch"):
        structure *= -0.5
    structure = _clamp(structure)

    rsi = _last(d, "rsi", 50.0)
    stoch = _last(d, "stoch_k", 50.0)
    macd_hist = _last(d, "macd_hist")
    adx = _last(d, "adx")
    plus_di, minus_di = _last(d, "plus_di"), _last(d, "minus_di")
    momentum = (rsi - 50.0) / 30.0
    momentum += 0.3 if macd_hist > 0 else -0.3
    momentum += (stoch - 50.0) / 60.0
    if adx >= 25:
        momentum += 0.4 if plus_di > minus_di else -0.4
    momentum = _clamp(momentum / 1.9)

    rvol = _last(d, "rvol", 1.0)
    up_bar = _last(d, "ret_1d") >= 0
    volume = 0.0
    if rvol >= 1.1:
        volume += 0.5 if up_bar else -0.5
    volume += 0.3 if _last(d, "obv") > _last(d, "obv_ma20") else -0.3
    volume += 0.3 if _last(d, "cmf") > 0 else -0.3
    volume = _clamp(volume)

    return {"trend": trend, "structure": structure, "momentum": momentum, "volume": volume}


def _htf_component(weekly: str, monthly: str, market: str) -> float:
    def m(t: str) -> float:
        return {"Bullish": 1.0, "Bearish": -1.0}.get(t, 0.0)
    val = 0.5 * m(weekly) + 0.3 * m(monthly) + 0.2 * (
        {"uptrend": 1.0, "downtrend": -1.0}.get(market, 0.0))
    return _clamp(val)


def _entry_component(d: pd.DataFrame, support: float, resistance: float, bias_sign: float) -> float:
    close = _last(d, "Close")
    ema21 = _last(d, "ema21", close)
    bb_up = _last(d, "bb_upper", close * 1.1)
    rsi = _last(d, "rsi", 50.0)
    val = 0.0
    if bias_sign > 0:
        if support and close - support <= 0.02 * close:
            val += 0.7
        if ema21 < close <= ema21 * 1.02:
            val += 0.3
    if rsi > 78 or close >= bb_up * 0.995:
        val -= 0.5
    if resistance and resistance > close and (resistance - close) <= 0.01 * close:
        val -= 0.4
    return _clamp(val)


def evaluate(
    d: pd.DataFrame,
    ticker: str = "",
    market: str = "unknown",
    weekly: str = "Netral",
    monthly: str = "Netral",
    support: float | None = None,
    resistance: float | None = None,
    fib: dict | None = None,
    vp: dict | None = None,
    turnover: float | None = None,
    data_status: str | None = None,
    liquidity_status: str | None = None,
    gap_pct: float = 0.0,
    data_quality_score: float | None = None,
) -> dict:
    """Bangun keputusan lengkap dari bar terakhir `d` (sudah via add_indicators)."""
    close = _last(d, "Close")
    atr = _last(d, "atr", close * 0.02)
    atr_pct = _last(d, "atr_pct", 2.0)
    atr_pctl = _last(d, "atr_pctl", 50.0)
    chop = _last(d, "chop", 50.0)
    support = float(support) if support else close * 0.96
    resistance = float(resistance) if resistance else close * 1.04

    struct = market_structure(d)
    comps = _direction_component(d, struct)
    bias_sign = 1.0 if struct.get("bias") == "bullish" else (-1.0 if struct.get("bias") == "bearish" else 0.0)

    htf = _htf_component(weekly, monthly, market)
    entry = _entry_component(d, support, resistance, bias_sign)

    net = (
        WEIGHTS["trend"] * comps["trend"]
        + WEIGHTS["structure"] * comps["structure"]
        + WEIGHTS["momentum"] * comps["momentum"]
        + WEIGHTS["volume"] * comps["volume"]
        + WEIGHTS["htf"] * htf
        + WEIGHTS["entry"] * entry
    ) / _DIR_WEIGHT
    net = _clamp(net)
    signal_score = int(round((net + 1.0) / 2.0 * 100.0))

    # --- Market regime (kaya) ---
    adx = _last(d, "adx")
    plus_di, minus_di = _last(d, "plus_di"), _last(d, "minus_di")
    if atr_pctl >= 85:
        regime = "High Volatility"
    elif atr_pctl <= 15:
        regime = "Low Volatility"
    elif chop >= 61.8 and adx < 20:
        regime = "Sideways / Range"
    elif adx >= 25 and plus_di > minus_di:
        regime = "Strong Uptrend"
    elif adx >= 25 and minus_di > plus_di:
        regime = "Strong Downtrend"
    elif adx >= 20 and plus_di > minus_di:
        regime = "Weak Uptrend"
    elif adx >= 20 and minus_di > plus_di:
        regime = "Weak Downtrend"
    else:
        regime = "Unclear"
    if struct.get("choch") and adx >= 20:
        regime = "Possible Reversal"
    if _last(d, "high20") and close >= _last(d, "high20") * 0.995 and _last(d, "rvol", 1) >= 1.2:
        regime = "Breakout"

    # --- Filters / NO-TRADE ---
    no_trade = False
    reasons_no: list[str] = []
    if data_status == "INSUFFICIENT":
        no_trade = True
        reasons_no.append("Data tidak cukup (INSUFFICIENT) - NO TRADE")
    if data_quality_score is not None and data_quality_score < settings.min_data_quality:
        no_trade = True
        reasons_no.append(f"Kualitas data rendah ({data_quality_score:.0f}) - NO TRADE")
    if chop >= 61.8 and adx < 20:
        no_trade = True
        reasons_no.append("Pasar sideways (choppiness tinggi, ADX lemah)")
    if atr_pctl >= 90 or atr_pct >= 8:
        no_trade = True
        reasons_no.append(f"Volatilitas ekstrem (ATR {atr_pct:.1f}%, pctl {atr_pctl:.0f})")
    if abs(net) < 0.15:
        no_trade = True
        reasons_no.append("Indikator konflik / sinyal tidak jelas")
    if bias_sign > 0 and market == "downtrend" and weekly == "Bearish":
        no_trade = True
        reasons_no.append("Bentrok multi-timeframe (IHSG & weekly bearish)")

    # --- Entry / SL / TP (orientasi LONG) ---
    sl_mult = settings.atr_sl_mult
    sl_swing = (struct.get("last_swing_low") or support) - 0.3 * atr
    sl_atr = close - sl_mult * atr
    max_risk_pct = 8.0
    sl = sl_swing if (close - sl_swing) <= max_risk_pct / 100.0 * close else sl_atr
    if sl >= close:
        sl = sl_atr if sl_atr < close else close - 0.4 * atr
    risk = max(close - sl, 0.4 * atr)

    fib = fib or {}
    res_above = [x for x in (resistance, fib.get("ext_1.272"), fib.get("ext_1.618")) if x and x > close]
    tp1 = close + 1.5 * risk
    if res_above and close + risk <= res_above[0] <= close + 2.5 * risk:
        tp1 = res_above[0]
    tp2 = close + settings.tp2_rr * risk
    tp3 = max(close + settings.tp3_rr * risk, tp2 + 1.5 * risk)
    rr1 = (tp1 - close) / risk if risk else 0.0
    rr2 = (tp2 - close) / risk if risk else 0.0
    rr3 = (tp3 - close) / risk if risk else 0.0
    if rr2 < 1.2:
        no_trade = True
        reasons_no.append(f"Risk/Reward buruk (1:{rr2:.1f})")

    # --- Direction ---
    if no_trade:
        direction = "NO TRADE"
    elif net >= 0.45:
        direction = "BUY"
    elif net >= 0.18:
        direction = "ACCUMULATE"
    elif net <= -0.45:
        direction = "SELL"
    elif net <= -0.18:
        direction = "HOLD (REDUCE)"
    else:
        direction = "HOLD"

    # --- Confidence ---
    sign = 1.0 if net > 0 else -1.0
    agree_w = 0.0
    for k, c in (("trend", comps["trend"]), ("structure", comps["structure"]),
                 ("momentum", comps["momentum"]), ("volume", comps["volume"]),
                 ("htf", htf), ("entry", entry)):
        if c * sign > 0:
            agree_w += WEIGHTS[k]
    agreement = agree_w / _DIR_WEIGHT
    clarity = min(1.0, abs(net) / 0.6)
    regime_quality = {"Strong Uptrend": 1.0, "Strong Downtrend": 1.0, "Weak Uptrend": 0.8,
                      "Weak Downtrend": 0.8, "Breakout": 0.85, "Possible Reversal": 0.5,
                      "Sideways / Range": 0.4, "Unclear": 0.3,
                      "High Volatility": 0.4, "Low Volatility": 0.6}.get(regime, 0.5)
    vol_quality = 1.0 if 15 < atr_pctl < 85 else (0.5 if atr_pctl >= 90 else 0.6)
    bars = len(d)
    data_quality = min(1.0, bars / 200.0)
    if turnover is not None:
        liq = min(1.0, max(0.0, (float(turnover) / 5e9)))
        data_quality = 0.5 * data_quality + 0.5 * liq
    rr_quality = min(1.0, rr2 / 3.0)
    confidence = int(round(100.0 * _clamp(
        0.30 * clarity + 0.25 * agreement + 0.20 * regime_quality
        + 0.15 * vol_quality + 0.10 * rr_quality, 0.0, 1.0)))
    if no_trade:
        confidence = min(confidence, 40)
    if liquidity_status == "LOW":
        confidence = max(0, confidence - 15)
    if abs(gap_pct) >= 7.0:
        confidence = max(0, confidence - 10)

    # --- Reasons / invalidation ---
    why: list[str] = []
    if comps["trend"] > 0.2:
        why.append("Tren naik (MA & Supertrend searah)")
    elif comps["trend"] < -0.2:
        why.append("Tren turun (MA & Supertrend searah)")
    if struct["bias"] != "ranging":
        why.append(f"Struktur {struct['label']} ({struct['bias']})")
    if struct["bos"] != "none":
        why.append(f"BOS {struct['bos']}")
    if struct.get("choch"):
        why.append("CHoCH (indikasi pembalikan struktur)")
    if comps["momentum"] > 0.2:
        why.append("Momentum menguat")
    elif comps["momentum"] < -0.2:
        why.append("Momentum melemah")
    if comps["volume"] > 0.2:
        why.append("Volume mengkonfirmasi")
    why.append(f"Regime: {regime}")
    why.append(f"HTF weekly {weekly}, bulanan {monthly}")

    invalidation = sl if direction in ("BUY", "ACCUMULATE") else struct.get("last_swing_low", sl)

    return {
        "ticker": ticker.upper(),
        "direction": direction,
        "confidence": confidence,
        "signal_score": signal_score,
        "net": round(net, 3),
        "regime": regime,
        "market": market,
        "structure": struct,
        "components": {k: round(v, 3) for k, v in comps.items()} | {"htf": round(htf, 3), "entry": round(entry, 3)},
        "entry_zone_low": round(min(close, (support + close) / 2.0 if support < close else close * 0.99), 2),
        "entry_zone_high": round(close, 2),
        "ideal_entry": round(close, 2),
        "invalidation": round(float(invalidation), 2),
        "stop_loss": round(sl, 2) if direction in ("BUY", "ACCUMULATE") else None,
        "tp1": round(tp1, 2) if direction in ("BUY", "ACCUMULATE") else None,
        "tp2": round(tp2, 2) if direction in ("BUY", "ACCUMULATE") else None,
        "tp3": round(tp3, 2) if direction in ("BUY", "ACCUMULATE") else None,
        "rr1": round(rr1, 2), "rr2": round(rr2, 2), "rr3": round(rr3, 2),
        "no_trade": no_trade,
        "no_trade_reasons": reasons_no,
        "reasons": why,
    }


def signal_series(d: pd.DataFrame, regime: pd.Series | None = None,
                  min_turnover: float = 0.0) -> pd.Series:
    """Sinyal decision vektor (untuk backtest). +1 BUY, 0 HOLD/NO-TRADE, -1 SELL.

    Ketat & anti-overtrade: wajib uptrend (close>MA50 & MA20>MA50), net kuat,
    volatilitas wajar, dan (bila tersedia) regime IHSG bukan downtrend. Bebas lookahead.
    """
    close = d["Close"]
    ma20, ma50, ma200 = d["ma20"], d["ma50"], d["ma200"]
    ema9, ema21 = d["ema9"], d["ema21"]
    uptrend = (close > ma50) & (ma20 > ma50)
    trend = (
        (close > ma20).astype(float) * 0.4 + (ma20 > ma50).astype(float) * 0.3
        + (ma50 > ma200).astype(float) * 0.3 + (d["st_dir"] == 1).astype(float) * 0.3
        + (ema9 > ema21).astype(float) * 0.3
    ) - 0.65
    momentum = (((d["rsi"] - 50) / 30.0) + np.sign(d["macd_hist"]) * 0.3).clip(-1, 1)
    vol = np.where(d["rvol"] >= 1.1, np.sign(d["ret_1d"]) * 0.5, 0.0) \
        + (d["obv"] > d["obv_ma20"]).astype(float) * 0.3 - 0.15
    net = 0.5 * trend.clip(-1, 1) + 0.25 * momentum + 0.25 * pd.Series(vol, index=d.index).clip(-1, 1)

    chop_ok = (d["chop"] < 61.8) | (d["adx"] >= 20)
    vol_ok = d["atr_pctl"] <= 90
    ok = (net >= 0.45) & uptrend & chop_ok & vol_ok
    if min_turnover > 0:
        val = (d["Close"] * d["Volume"]).rolling(20, min_periods=5).mean()
        ok = ok & (val >= min_turnover)
    if regime is not None:
        rr = regime.reindex(d.index).ffill()
        ok = ok & (rr.fillna("ranging") != "downtrend")

    sig = pd.Series(0, index=d.index)
    sig[ok] = 1
    sig[(net <= -0.55) & (~uptrend) & chop_ok] = -1
    return sig
