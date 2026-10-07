from __future__ import annotations

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
    if now - _MKT_CACHE["ts"] < 300 and _MKT_CACHE["regime"] != "unknown":
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
    plus_di = float(last["plus_di"])
    minus_di = float(last["minus_di"])
    if adx_val >= settings.adx_trend_threshold:
        regime = "Trending Kuat" if plus_di > minus_di else "Downtrend Kuat"
    elif chop_val >= 61.8:
        regime = "Ranging / Choppy"
    elif adx_val >= 20:
        regime = "Trending" if plus_di > minus_di else "Melemah"
    else:
        regime = "Ranging / Sideways"

    if atr_pctl >= 75:
        vol_regime = "Tinggi"
    elif atr_pctl <= 25:
        vol_regime = "Rendah"
    else:
        vol_regime = "Normal"

    extended = rsi_val > 68 or price >= float(last["bb_upper"]) * 0.995
    breakout = price >= float(last["high20"]) * 0.99

    score_heuristic = int(round(float(srow["score"])))
    confidence = int(round(float(crow["confidence"])))
    prob_up: float | None = None
    score_opt: float | None = None
    model_used = False
    score = score_heuristic
    if settings.use_optimized_score:
        try:
            import calibration
            model = calibration.load_model()
            if model:
                prob_up = calibration.prob_up(d, model)
                if prob_up is not None:
                    score_opt = calibration.prob_to_score(prob_up, float(model.get("base_rate", 0.5)))
                    alpha = float(model.get("effective_alpha", model.get("alpha", settings.ml_blend_alpha)))
                    alpha = min(max(alpha, 0.0), 1.0)
                    if alpha > 0.0:
                        score = int(round((1.0 - alpha) * score_heuristic + alpha * score_opt))
                        model_used = True
        except Exception:
            prob_up = None

    signal, action = _action(score, uptrend, extended, breakout)
    grade = _grade(score, confidence, uptrend)

    mkt_regime = market_regime() if settings.regime_filter else "unknown"
    if settings.regime_filter and mkt_regime == "downtrend" and signal in ("BUY", "STRONG BUY"):
        signal, action = "HOLD", "TAHAN (IHSG downtrend)"

    stop_loss = min(
        price - settings.atr_sl_mult * atr_val,
        support - 0.3 * atr_val,
    )
    if stop_loss >= price:
        stop_loss = price - settings.atr_sl_mult * atr_val
    risk = max(price - stop_loss, 0.4 * atr_val)
    stop_loss = price - risk
    risk_pct = risk / price * 100.0

    demand_below = sorted(
        [z for z in zones if z["type"] == "demand" and z["top"] < price],
        key=lambda z: z["top"], reverse=True,
    )
    support_candidates = [
        float(last["ema21"]), float(last["ma20"]), float(fib["0.382"]), float(fib["0.5"]),
        avwap_val, float(vp["val"]),
    ]
    if demand_below:
        support_candidates.append(demand_below[0]["top"])
    support_candidates = [x for x in support_candidates if np.isfinite(x)]
    below = [x for x in support_candidates if x < price]
    entry_pullback = max(below) if below else price * 0.97
    entry_breakout = float(last["high20"]) * 1.003
    zone_high = min(entry_pullback * 1.01, price)
    zone_low = min(below) if below else entry_pullback * 0.98
    if zone_low > zone_high:
        zone_low, zone_high = zone_high, zone_low

    tp1_base = price + settings.tp1_rr * risk
    near = [
        x for x in (resistance, float(piv["r1"]), float(fib["ext_1.272"]))
        if price + 1.0 * risk <= x <= price + 2.5 * risk
    ]
    tp1 = min(near) if near else tp1_base
    tp2 = max(price + settings.tp2_rr * risk, tp1 + 1.5 * risk)
    tp3 = max(price + settings.tp3_rr * risk, float(fib["ext_1.618"]), tp2 + 1.5 * risk)

    rr1 = (tp1 - price) / risk if risk else 0.0
    rr2 = (tp2 - price) / risk if risk else 0.0
    rr3 = (tp3 - price) / risk if risk else 0.0

    trail = float(last["chandelier"])
    if trail <= 0 or trail >= price:
        trail = price - settings.trail_mult * atr_val

    risk_amount = settings.capital * settings.risk_pct / 100.0
    per_lot_risk = risk * settings.lot_size
    lots = int(floor(risk_amount / per_lot_risk)) if per_lot_risk > 0 else 0
    position_value = lots * settings.lot_size * price
    max_loss = lots * per_lot_risk

    if light:
        rs_change, rs_strong = None, None
        rsi_bull = rsi_bear = macd_bull = macd_bear = obv_bull = obv_bear = False
    else:
        rs_change, rs_strong = relative_strength(df)
        rsi_bull, rsi_bear = divergence(d["Close"], d["rsi"])
        macd_bull, macd_bear = divergence(d["Close"], d["macd_hist"])
        obv_bull, obv_bear = divergence(d["Close"], d["obv"])

    decision_data: dict = {}
    stock_data: dict = {}
    if settings.enable_decision:
        try:
            import decision as decision_mod
            import stock as stock_mod
            from config import sector_of
            liq = stock_mod.liquidity(d)
            dataq = stock_mod.data_quality(d)
            gapv = stock_mod.gap(d)
            avg_turnover = float((d["Close"] * d["Volume"]).tail(20).mean())
            decision_data = decision_mod.evaluate(
                d, ticker, market=mkt_regime, weekly=w_trend, monthly=m_trend,
                support=support, resistance=resistance, fib=fib, vp=vp, turnover=avg_turnover,
                data_status=dataq["status"], liquidity_status=liq["status"], gap_pct=gapv["gap_pct"],
                data_quality_score=dataq.get("score"))
            stock_data = stock_mod.evaluate_stock(
                d, ticker, decision_data, sector_name=sector_of(ticker),
                rs_change=rs_change, rs_strong=rs_strong)
        except Exception:
            decision_data = {}
            stock_data = {}

    patterns: list[str] = []
    for name, label in [
        ("cp_bull_engulf", "Bullish Engulfing"),
        ("cp_bear_engulf", "Bearish Engulfing"),
        ("cp_hammer", "Hammer"),
        ("cp_shooting_star", "Shooting Star"),
        ("cp_marubozu_bull", "Marubozu Bullish"),
        ("cp_marubozu_bear", "Marubozu Bearish"),
        ("cp_doji", "Doji"),
        ("cp_morning_star", "Morning Star"),
        ("cp_evening_star", "Evening Star"),
        ("cp_three_white_soldiers", "Three White Soldiers"),
        ("cp_three_black_crows", "Three Black Crows"),
        ("cp_bull_harami", "Bullish Harami"),
        ("cp_bear_harami", "Bearish Harami"),
        ("cp_tweezer_bottom", "Tweezer Bottom"),
        ("cp_tweezer_top", "Tweezer Top"),
    ]:
        if bool(last.get(name, False)):
            patterns.append(label)

    divergences: list[str] = []
    if rsi_bull:
        divergences.append("Bullish divergence (RSI)")
    if rsi_bear:
        divergences.append("Bearish divergence (RSI)")
    if macd_bull:
        divergences.append("Bullish divergence (MACD)")
    if macd_bear:
        divergences.append("Bearish divergence (MACD)")
    if obv_bull:
        divergences.append("Bullish divergence (OBV)")
    if obv_bear:
        divergences.append("Bearish divergence (OBV)")

    vol_ratio = float(last["Volume"] / last["vol_ma20"]) if last["vol_ma20"] else 0.0

    hma_val = float(last["hma20"]) if np.isfinite(last["hma20"]) else price
    kama_val = float(last["kama"]) if np.isfinite(last["kama"]) else price
    aroon_up_val = float(last["aroon_up"]) if np.isfinite(last["aroon_up"]) else 0.0
    aroon_down_val = float(last["aroon_down"]) if np.isfinite(last["aroon_down"]) else 0.0
    vortex_plus_val = float(last["vortex_plus"]) if np.isfinite(last["vortex_plus"]) else 0.0
    vortex_minus_val = float(last["vortex_minus"]) if np.isfinite(last["vortex_minus"]) else 0.0
    ao_val = float(last["ao"]) if np.isfinite(last["ao"]) else 0.0
    uo_val = float(last["uo"]) if np.isfinite(last["uo"]) else 50.0
    rvol_val = float(last["rvol"]) if np.isfinite(last["rvol"]) else 1.0

    checklist = [(k, bool(crow[k])) for k in FACTOR_KEYS]

    reasons: list[str] = []
    warnings: list[str] = []

    if last["st_dir"] == 1:
        reasons.append("Supertrend bullish (tren pendek naik)")
    if price > float(last["senkou_a"]) and price > float(last["senkou_b"]):
        reasons.append("Harga di atas Ichimoku Cloud (bias bullish)")
    if last["adx"] >= settings.adx_trend_threshold and plus_di > minus_di:
        reasons.append(f"ADX {adx_val:.0f} + DI+ dominant (tren kuat)")
    if last["macd"] > last["macd_signal"] and last["macd_hist"] > 0:
        reasons.append("MACD bullish dengan histogram positif")
    if 50 <= rsi_val <= 70:
        reasons.append(f"RSI {rsi_val:.0f} di zona sehat bullish")
    if vol_ratio >= 1.2:
        reasons.append(f"Volume {vol_ratio:.1f}x rata-rata (konfirmasi)")
    if bool(last.get("cp_bullish", False)):
        reasons.append("Pola candlestick bullish terdeteksi")
    if rsi_bull:
        reasons.append("Bullish divergence RSI (indikasi pembalikan naik)")
    if macd_bull or obv_bull:
        reasons.append("Divergence momentum/volume bullish (MACD/OBV)")
    if rs_strong:
        reasons.append("Relative strength di atas IHSG (outperform)")
    if w_trend == "Bullish":
        reasons.append("Tren mingguan bullish (multi-timeframe selaras)")
    if bool(last["squeeze_off"]) and float(last["sqz_mom"]) > 0 and float(last["sqz_dir"]) > 0:
        reasons.append("Squeeze release + momentum naik (potensi breakout)")
    if price > avwap_val:
        reasons.append("Harga di atas Anchored VWAP (bias bullish)")
    if chop_val < 38:
        reasons.append("Choppiness rendah (pasar cenderung trending)")
    if mtf.startswith("Selaras Bullish"):
        reasons.append("Multi-timeframe D/W/M selaras bullish")
    if demand_below:
        reasons.append(f"Zona demand terdekat {demand_below[0]['bottom']:,.0f} - {demand_below[0]['top']:,.0f}")
    if model_used and prob_up is not None:
        reasons.append(f"Skor dioptimasi (walk-forward): probabilitas naik {prob_up*100:.0f}%")

    if rsi_val > 78:
        warnings.append(f"RSI overbought ({rsi_val:.0f}) - rawan koreksi")
    if atr_pct > 5:
        warnings.append(f"Volatilitas tinggi (ATR {atr_pct:.1f}%)")
    if price < float(last["ma50"]):
        warnings.append("Harga di bawah MA50 (tren lemah)")
    if vol_ratio < 0.7:
        warnings.append("Volume tipis (<0.7x rata-rata)")
    if rsi_bear or macd_bear or obv_bear:
        warnings.append("Divergence bearish (RSI/MACD/OBV) - waspada pelemahan")
    if w_trend == "Bearish":
        warnings.append("Tren mingguan bearish (bentrok multi-timeframe)")
    if regime.startswith("Downtrend"):
        warnings.append("ADX menunjukkan downtrend kuat")
    if bool(last["squeeze_on"]):
        warnings.append("Squeeze aktif (kompresi volatilitas) - tunggu arah breakout")
    if price < avwap_val:
        warnings.append("Harga di bawah Anchored VWAP (tekanan jual)")
    if chop_val >= 61.8:
        warnings.append("Choppiness tinggi (pasar sideways, sinyal rawan palsu)")
    if adr_pct and (tp1 - price) / price * 100.0 > 3.0 * adr_pct:
        warnings.append(f"TP1 > 3x ADR harian ({adr_pct:.1f}%) - butuh waktu lebih lama")
    if mkt_regime == "downtrend":
        warnings.append("IHSG downtrend - sinyal beli ditahan (regime filter)")
    elif mkt_regime == "ranging":
        warnings.append("IHSG ranging - edge faktor lemah, utamakan saham terkuat")
    if mkt_regime == "uptrend":
        reasons.append("IHSG uptrend - edge faktor historis lebih baik")

    return Analysis(
        ticker=ticker.upper(),
        price=price,
        change_1d=change_1d,
        signal=signal,
        action=action,
        score=score,
        confidence=confidence,
        grade=grade,
        trend=trend,
        weekly_trend=w_trend,
        regime=regime,
        entry=price,
        entry_pullback=entry_pullback,
        entry_breakout=entry_breakout,
        buy_zone_low=zone_low,
        buy_zone_high=zone_high,
        stop_loss=stop_loss,
        stop_trail=trail,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        rr1=rr1,
        rr2=rr2,
        rr3=rr3,
        atr=atr_val,
        atr_pct=atr_pct,
        rsi=rsi_val,
        stoch_k=float(last["stoch_k"]),
        macd_hist=float(last["macd_hist"]),
        adx=adx_val,
        plus_di=plus_di,
        minus_di=minus_di,
        cci=float(last["cci"]),
        mfi=float(last["mfi"]),
        cmf=float(last["cmf"]),
        vol_ratio=vol_ratio,
        ret_20d=float(last["ret_20d"]) if not np.isnan(last["ret_20d"]) else 0.0,
        support=support,
        resistance=resistance,
        pivot=piv,
        fib=fib,
        rs_change=rs_change,
        rs_strong=rs_strong,
        lots=lots,
        position_value=position_value,
        max_loss=max_loss,
        risk_amount=risk_amount,
        patterns=patterns,
        divergences=divergences,
        checklist=checklist,
        components={
            "tren": float(srow["tren"]),
            "momentum": float(srow["momentum"]),
            "kekuatan": float(srow["kekuatan"]),
            "volume": float(srow["volume"]),
            "setup": float(srow["setup"]),
            "risiko": float(srow["risiko"]),
            "konfluensi": float(srow["konfluensi"]),
        },
        reasons=reasons,
        warnings=warnings,
        score_heuristic=score_heuristic,
        score_opt=score_opt,
        prob_up=prob_up,
        model_used=model_used,
        market_regime=mkt_regime,
        decision=decision_data,
        stock=stock_data,
        st_dir_up=bool(last["st_dir"] == 1),
        squeeze_on=bool(last["squeeze_on"]),
        squeeze_mom=float(last["sqz_mom"]) if np.isfinite(last["sqz_mom"]) else 0.0,
        chop=chop_val,
        adr_pct=adr_pct,
        atr_pctl=atr_pctl,
        avwap=avwap_val,
        vol_regime=vol_regime,
        monthly_trend=m_trend,
        mtf=mtf,
        hma20=hma_val,
        kama=kama_val,
        aroon_up=aroon_up_val,
        aroon_down=aroon_down_val,
        vortex_plus=vortex_plus_val,
        vortex_minus=vortex_minus_val,
        ao=ao_val,
        uo=uo_val,
        rvol=rvol_val,
        vp=vp,
        zones=zones,
    )
