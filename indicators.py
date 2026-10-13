from __future__ import annotations

import numpy as np
import pandas as pd

from config import settings


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(window=n, min_periods=1).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def wilder(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = wilder(gain, n)
    avg_loss = wilder(loss, n)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(50.0)


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(
    close: pd.Series, n: int = 20, k: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(close, n)
    std = close.rolling(window=n, min_periods=1).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return wilder(true_range(high, low, close), n)


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3
) -> tuple[pd.Series, pd.Series]:
    lowest = low.rolling(window=k, min_periods=1).min()
    highest = high.rolling(window=k, min_periods=1).max()
    denom = (highest - lowest).replace(0.0, np.nan)
    k_line = (100.0 * (close - lowest) / denom).fillna(50.0)
    d_line = k_line.rolling(window=d, min_periods=1).mean()
    return k_line, d_line


def stoch_rsi(close: pd.Series, n: int = 14, k: int = 3, d: int = 3) -> tuple[pd.Series, pd.Series]:
    r = rsi(close, n)
    lo = r.rolling(n, min_periods=1).min()
    hi = r.rolling(n, min_periods=1).max()
    denom = (hi - lo).replace(0.0, np.nan)
    srsi = ((r - lo) / denom).fillna(0.5)
    srsi_k = srsi.rolling(k, min_periods=1).mean()
    srsi_d = srsi_k.rolling(d, min_periods=1).mean()
    return srsi_k, srsi_d


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume).cumsum()


def mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 14) -> pd.Series:
    tp = (high + low + close) / 3.0
    mf = tp * volume
    pos = mf.where(tp > tp.shift(1), 0.0).rolling(n, min_periods=1).sum()
    neg = mf.where(tp < tp.shift(1), 0.0).rolling(n, min_periods=1).sum()
    ratio = pos / neg.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + ratio)).fillna(50.0)


def cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 21) -> pd.Series:
    rng = (high - low).replace(0.0, np.nan)
    mfm = ((close - low) - (high - close)) / rng
    mfv = mfm.fillna(0.0) * volume
    return mfv.rolling(n, min_periods=1).sum() / volume.rolling(n, min_periods=1).sum()


def cci(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    tp = (high + low + close) / 3.0
    ma = tp.rolling(n, min_periods=1).mean()
    mad = tp.rolling(n, min_periods=n).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    return (tp - ma) / (0.015 * mad.replace(0.0, np.nan))


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    hh = high.rolling(n, min_periods=1).max()
    ll = low.rolling(n, min_periods=1).min()
    return -100.0 * (hh - close) / (hh - ll).replace(0.0, np.nan)


def keltner(
    high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20, mult: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = ema(close, n)
    a = atr(high, low, close, n)
    return mid + mult * a, mid, mid - mult * a


def rolling_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 20) -> pd.Series:
    tp = (high + low + close) / 3.0
    return (tp * volume).rolling(n, min_periods=1).sum() / volume.rolling(n, min_periods=1).sum()


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=close.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=close.index)
    tr = true_range(high, low, close)
    a = wilder(tr, n).replace(0.0, np.nan)
    plus_di = 100.0 * wilder(plus_dm, n) / a
    minus_di = 100.0 * wilder(minus_dm, n) / a
    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx_line = wilder(dx.fillna(0.0), n)
    return adx_line, plus_di, minus_di


def supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, mult: float = 3.0
) -> tuple[pd.Series, pd.Series]:
    hl2 = (high + low) / 2.0
    a = atr(high, low, close, period)
    basic_ub = (hl2 + mult * a).to_numpy(dtype=float)
    basic_lb = (hl2 - mult * a).to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)
    n = len(c)
    final_ub = basic_ub.copy()
    final_lb = basic_lb.copy()
    st = np.full(n, np.nan)
    direction = np.ones(n, dtype=int)
    for i in range(1, n):
        final_ub[i] = (
            basic_ub[i]
            if (basic_ub[i] < final_ub[i - 1] or c[i - 1] > final_ub[i - 1] or np.isnan(final_ub[i - 1]))
            else final_ub[i - 1]
        )
        final_lb[i] = (
            basic_lb[i]
            if (basic_lb[i] > final_lb[i - 1] or c[i - 1] < final_lb[i - 1] or np.isnan(final_lb[i - 1]))
            else final_lb[i - 1]
        )
        if c[i] > final_ub[i - 1]:
            direction[i] = 1
        elif c[i] < final_lb[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        st[i] = final_lb[i] if direction[i] == 1 else final_ub[i]
    return pd.Series(st, index=close.index), pd.Series(direction, index=close.index)


def chandelier(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 22, mult: float = 3.0) -> pd.Series:
    a = atr(high, low, close, period)
    return high.rolling(period, min_periods=1).max() - mult * a


def ichimoku(
    high: pd.Series, low: pd.Series, close: pd.Series,
    tenkan: int = 9, kijun: int = 26, senkou: int = 52,
) -> dict[str, pd.Series]:
    conv = (high.rolling(tenkan, min_periods=1).max() + low.rolling(tenkan, min_periods=1).min()) / 2.0
    base = (high.rolling(kijun, min_periods=1).max() + low.rolling(kijun, min_periods=1).min()) / 2.0
    span_a = ((conv + base) / 2.0).shift(kijun)
    span_b = ((high.rolling(senkou, min_periods=1).max() + low.rolling(senkou, min_periods=1).min()) / 2.0).shift(kijun)
    return {
        "tenkan": conv,
        "kijun": base,
        "senkou_a": span_a,
        "senkou_b": span_b,
    }


def pivot_points(high: float, low: float, close: float) -> dict[str, float]:
    pp = (high + low + close) / 3.0
    return {
        "pp": pp,
        "r1": 2 * pp - low,
        "s1": 2 * pp - high,
        "r2": pp + (high - low),
        "s2": pp - (high - low),
        "r3": high + 2 * (pp - low),
        "s3": low - 2 * (high - pp),
    }


def swing_points(high: pd.Series, low: pd.Series, order: int = 3) -> tuple[pd.Series, pd.Series]:
    is_high = pd.Series(True, index=high.index)
    is_low = pd.Series(True, index=low.index)
    for k in range(1, order + 1):
        is_high &= (high >= high.shift(k)) & (high >= high.shift(-k))
        is_low &= (low <= low.shift(k)) & (low <= low.shift(-k))
    return is_high.fillna(False), is_low.fillna(False)


def fib_levels(swing_low: float, swing_high: float) -> dict[str, float]:
    diff = swing_high - swing_low
    return {
        "0.0": swing_high,
        "0.236": swing_high - 0.236 * diff,
        "0.382": swing_high - 0.382 * diff,
        "0.5": swing_high - 0.5 * diff,
        "0.618": swing_high - 0.618 * diff,
        "0.786": swing_high - 0.786 * diff,
        "ext_1.272": swing_low + 1.272 * diff,
        "ext_1.618": swing_low + 1.618 * diff,
    }


def divergence(
    close: pd.Series, osc: pd.Series, order: int = 5, lookback: int = 60
) -> tuple[bool, bool]:
    price = close.to_numpy(dtype=float)
    ind = osc.to_numpy(dtype=float)
    n = len(price)
    start = max(order, n - lookback)
    lows, highs = [], []
    for i in range(start, n - order):
        window_p = price[i - order: i + order + 1]
        if np.isnan(window_p).any():
            continue
        if price[i] == window_p.min():
            lows.append(i)
        if price[i] == window_p.max():
            highs.append(i)
    bullish = False
    bearish = False
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if price[b] < price[a] and ind[b] > ind[a]:
            bullish = True
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if price[b] > price[a] and ind[b] < ind[a]:
            bearish = True
    return bullish, bearish


def rsi_divergence(
    close: pd.Series, osc: pd.Series, order: int = 5, lookback: int = 60
) -> tuple[bool, bool]:
    return divergence(close, osc, order=order, lookback=lookback)


def squeeze_momentum(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bb_n: int = 20, bb_mult: float = 2.0, kc_n: int = 20, kc_mult: float = 1.5,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """TTM / LazyBear Squeeze Momentum.

    Returns (squeeze_on, squeeze_off, momentum). Momentum is the
    linear-regression value of the delta; positive = bullish impulse.
    """
    basis = sma(close, bb_n)
    dev = close.rolling(bb_n, min_periods=1).std(ddof=0)
    bb_upper = basis + bb_mult * dev
    bb_lower = basis - bb_mult * dev

    ma = sma(close, kc_n)
    atr_kc = sma(true_range(high, low, close), kc_n)
    kc_upper = ma + kc_mult * atr_kc
    kc_lower = ma - kc_mult * atr_kc

    squeeze_on = (bb_lower > kc_lower) & (bb_upper < kc_upper)
    squeeze_off = ~squeeze_on

    highest = high.rolling(bb_n, min_periods=1).max()
    lowest = low.rolling(bb_n, min_periods=1).min()
    avg = (highest + lowest) / 2.0
    delta = (close - (avg + basis) / 2.0).to_numpy(dtype=float)

    n = len(delta)
    mom = np.full(n, np.nan)
    x = np.arange(bb_n)
    xm = x.mean()
    denom = ((x - xm) ** 2).sum()
    for i in range(bb_n - 1, n):
        y = delta[i - bb_n + 1: i + 1]
        if np.isnan(y).any():
            continue
        ym = y.mean()
        slope = ((x - xm) * (y - ym)).sum() / denom if denom else 0.0
        intercept = ym - slope * xm
        mom[i] = slope * (bb_n - 1) + intercept

    return squeeze_on, squeeze_off, pd.Series(mom, index=close.index)


def choppiness_index(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    tr_sum = true_range(high, low, close).rolling(n, min_periods=1).sum()
    hh = high.rolling(n, min_periods=1).max()
    ll = low.rolling(n, min_periods=1).min()
    rng = (hh - ll).replace(0.0, np.nan)
    chop = 100.0 * np.log10(tr_sum / rng) / np.log10(n)
    return chop.clip(0, 100).fillna(50.0)


def adr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> tuple[pd.Series, pd.Series]:
    rng = (high - low).abs()
    adr_val = rng.rolling(n, min_periods=1).mean()
    return adr_val, (adr_val / close.replace(0.0, np.nan) * 100.0)


def anchored_vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, anchor_idx: int
) -> pd.Series:
    tp = (high + low + close) / 3.0
    pv = (tp * volume).to_numpy(dtype=float)
    vol = volume.to_numpy(dtype=float)
    n = len(close)
    out = np.full(n, np.nan)
    cum_pv = 0.0
    cum_v = 0.0
    anchor_idx = max(0, min(anchor_idx, n - 1))
    for i in range(anchor_idx, n):
        if np.isnan(pv[i]) or np.isnan(vol[i]):
            continue
        cum_pv += pv[i]
        cum_v += vol[i]
        out[i] = cum_pv / cum_v if cum_v else np.nan
    return pd.Series(out, index=close.index)


def auto_anchor_index(low: pd.Series, high: pd.Series, lookback: int = 120, order: int = 5) -> int:
    n = len(low)
    win = min(lookback, n)
    sub_low = low.iloc[-win:]
    sub_high = high.iloc[-win:]
    _, lo_flags = swing_points(sub_high, sub_low, order=order)
    candidates = sub_low[lo_flags]
    if not candidates.empty:
        pos = sub_low.index.get_loc(candidates.index[-1])
        return int(n - win + pos)
    return int(n - win + int(np.nanargmin(sub_low.to_numpy(dtype=float))))


def _causal_anchor_index(low_arr: np.ndarray, start: int, end: int, order: int = 5) -> int:
    """Anchor pada window [start, end] dengan aturan identik `auto_anchor_index`.

    Hanya memakai data dalam window (<= end) sehingga bebas look-ahead.
    """
    sub = low_arr[start:end + 1]
    m = sub.size
    is_low = np.ones(m, dtype=bool)
    for k in range(1, order + 1):
        left = np.full(m, -np.inf)
        right = np.full(m, -np.inf)
        if m > k:
            left[k:] = sub[:-k]
            right[:-k] = sub[k:]
        is_low &= (sub <= left) & (sub <= right)
    cand = np.nonzero(is_low)[0]
    if cand.size:
        return start + int(cand[-1])
    return start + int(np.nanargmin(sub))


def causal_anchored_vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
    lookback: int = 120, order: int = 5,
) -> pd.Series:
    """AVWAP kausal: anchor bar t hanya dari window yang berakhir di bar t.

    Bebas look-ahead untuk backtest/ML/kalibrasi. Bar terakhir identik dengan
    `anchored_vwap(high, low, close, volume, auto_anchor_index(...))` karena
    window tail sama. Bar awal tetap NaN (bukan 0) saat price/volume NaN.
    """
    tp = (high + low + close) / 3.0
    pv = (tp * volume).to_numpy(dtype=float)
    vol = volume.to_numpy(dtype=float)
    lo = low.to_numpy(dtype=float)
    n = len(close)
    out = np.full(n, np.nan)
    if n == 0:
        return pd.Series(out, index=close.index)

    cs_pv = np.empty(n + 1, dtype=float)
    cs_v = np.empty(n + 1, dtype=float)
    cs_pv[0] = 0.0
    cs_v[0] = 0.0
    np.cumsum(np.where(np.isfinite(pv), pv, 0.0), out=cs_pv[1:])
    np.cumsum(np.where(np.isfinite(vol), vol, 0.0), out=cs_v[1:])

    for t in range(n):
        if not (np.isfinite(pv[t]) and np.isfinite(vol[t])):
            continue
        start = t + 1 - min(lookback, t + 1)
        a = _causal_anchor_index(lo, start, t, order)
        den = cs_v[t + 1] - cs_v[a]
        if den:
            out[t] = (cs_pv[t + 1] - cs_pv[a]) / den
    return pd.Series(out, index=close.index)


def volume_profile(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
    bins: int = 24, lookback: int = 120,
) -> dict:
    h = high.tail(lookback).to_numpy(dtype=float)
    l = low.tail(lookback).to_numpy(dtype=float)
    c = close.tail(lookback).to_numpy(dtype=float)
    v = volume.tail(lookback).to_numpy(dtype=float)
    lo = float(np.nanmin(l))
    hi = float(np.nanmax(h))
    last = float(c[-1]) if len(c) else 0.0
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return {"poc": last, "vah": last, "val": last, "levels": [], "profile": []}
    edges = np.linspace(lo, hi, bins + 1)
    prof = np.zeros(bins)
    span = hi - lo
    for i in range(len(c)):
        if not np.isfinite(h[i]) or not np.isfinite(l[i]) or not np.isfinite(v[i]):
            continue
        a = max(0, min(bins - 1, int((l[i] - lo) / span * bins)))
        b = max(0, min(bins - 1, int((h[i] - lo) / span * bins)))
        share = v[i] / (b - a + 1)
        for k in range(a, b + 1):
            prof[k] += share
    centers = (edges[:-1] + edges[1:]) / 2.0
    poc = float(centers[int(np.argmax(prof))])
    total = float(prof.sum()) or 1.0
    order_idx = np.argsort(prof)[::-1]
    acc = 0.0
    chosen: list[int] = []
    for k in order_idx:
        acc += prof[k]
        chosen.append(int(k))
        if acc >= 0.7 * total:
            break
    vah = float(centers[max(chosen)])
    val = float(centers[min(chosen)])
    return {
        "poc": poc, "vah": vah, "val": val,
        "levels": [float(x) for x in centers],
        "profile": [float(x) for x in prof],
    }


def supply_demand_zones(
    df: pd.DataFrame, lookback: int = 90, order: int = 3, max_zones: int = 8
) -> list[dict]:
    d = df.tail(lookback)
    hi_flags, lo_flags = swing_points(d["High"], d["Low"], order=order)
    zones: list[dict] = []
    for ts in d.index[hi_flags]:
        row = d.loc[ts]
        top = float(row["High"])
        bottom = float(max(row["Open"], row["Close"]))
        if top > bottom:
            zones.append({"type": "supply", "top": top, "bottom": bottom,
                          "mid": (top + bottom) / 2.0, "time": str(ts)[:10]})
    for ts in d.index[lo_flags]:
        row = d.loc[ts]
        bottom = float(row["Low"])
        top = float(min(row["Open"], row["Close"]))
        if top > bottom:
            zones.append({"type": "demand", "top": top, "bottom": bottom,
                          "mid": (top + bottom) / 2.0, "time": str(ts)[:10]})
    zones.sort(key=lambda z: z["time"])
    return zones[-max_zones:]


def candle_patterns(
    o: pd.Series, h: pd.Series, l: pd.Series, c: pd.Series
) -> pd.DataFrame:
    body = (c - o).abs()
    rng = (h - l).replace(0.0, np.nan)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    out = pd.DataFrame(index=c.index)
    out["bull_engulf"] = (c > o) & (c.shift(1) < o.shift(1)) & (c >= o.shift(1)) & (o <= c.shift(1))
    out["bear_engulf"] = (c < o) & (c.shift(1) > o.shift(1)) & (c <= o.shift(1)) & (o >= c.shift(1))
    out["hammer"] = (lower >= 2 * body) & (upper <= body) & (body <= 0.4 * rng)
    out["shooting_star"] = (upper >= 2 * body) & (lower <= body) & (body <= 0.4 * rng)
    out["doji"] = body <= 0.1 * rng
    out["marubozu_bull"] = (c > o) & (body >= 0.9 * rng)
    out["marubozu_bear"] = (c < o) & (body >= 0.9 * rng)

    bull = c > o
    bear = c < o
    out["morning_star"] = (
        (~bull.shift(2, fill_value=False))
        & (body.shift(1) <= 0.35 * body.shift(2))
        & bull
        & (c > (o.shift(2) + c.shift(2)) / 2.0)
    )
    out["evening_star"] = (
        (~bear.shift(2, fill_value=False))
        & (body.shift(1) <= 0.35 * body.shift(2))
        & bear
        & (c < (o.shift(2) + c.shift(2)) / 2.0)
    )
    out["three_white_soldiers"] = (
        bull & bull.shift(1, fill_value=False) & bull.shift(2, fill_value=False)
        & (c > c.shift(1)) & (c.shift(1) > c.shift(2))
        & (o >= o.shift(1)) & (o.shift(1) >= o.shift(2))
    )
    out["three_black_crows"] = (
        bear & bear.shift(1, fill_value=False) & bear.shift(2, fill_value=False)
        & (c < c.shift(1)) & (c.shift(1) < c.shift(2))
        & (o <= o.shift(1)) & (o.shift(1) <= o.shift(2))
    )
    out["bull_harami"] = (
        (~bull.shift(1, fill_value=False)) & bull
        & (np.maximum(o, c) <= np.maximum(o.shift(1), c.shift(1)))
        & (np.minimum(o, c) >= np.minimum(o.shift(1), c.shift(1)))
        & (body.shift(1) >= 1.5 * body)
    )
    out["bear_harami"] = (
        (~bear.shift(1, fill_value=False)) & bear
        & (np.maximum(o, c) <= np.maximum(o.shift(1), c.shift(1)))
        & (np.minimum(o, c) >= np.minimum(o.shift(1), c.shift(1)))
        & (body.shift(1) >= 1.5 * body)
    )
    out["tweezer_bottom"] = (
        bull & (~bull.shift(1, fill_value=False))
        & ((l - l.shift(1)).abs() <= 0.1 * rng)
    )
    out["tweezer_top"] = (
        bear & (~bear.shift(1, fill_value=False))
        & ((h - h.shift(1)).abs() <= 0.1 * rng)
    )
    out["inside_bar"] = (h <= h.shift(1)) & (l >= l.shift(1))
    out["outside_bar"] = (h > h.shift(1)) & (l < l.shift(1))

    out["bullish"] = (
        out["bull_engulf"] | out["hammer"] | out["marubozu_bull"]
        | out["morning_star"] | out["three_white_soldiers"]
        | out["bull_harami"] | out["tweezer_bottom"]
    )
    out["bearish"] = (
        out["bear_engulf"] | out["shooting_star"] | out["marubozu_bear"]
        | out["evening_star"] | out["three_black_crows"]
        | out["bear_harami"] | out["tweezer_top"]
    )
    return out.fillna(False)


def wma(series: pd.Series, n: int) -> pd.Series:
    weights = np.arange(1, n + 1, dtype=float)
    return series.rolling(window=n, min_periods=1).apply(
        lambda x: float(np.dot(x, weights[-len(x):]) / weights[-len(x):].sum()), raw=True
    )


def hma(series: pd.Series, n: int = 20) -> pd.Series:
    half = max(1, n // 2)
    root = max(1, int(np.sqrt(n)))
    return wma(2.0 * wma(series, half) - wma(series, n), root)


def kama(series: pd.Series, n: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    change = (series - series.shift(n)).abs()
    volatility = series.diff().abs().rolling(window=n, min_periods=1).sum()
    er = (change / volatility.replace(0.0, np.nan)).fillna(0.0)
    fast_sc = 2.0 / (fast + 1.0)
    slow_sc = 2.0 / (slow + 1.0)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
    values = series.to_numpy(dtype=float)
    smooth = sc.to_numpy(dtype=float)
    out = np.empty(len(values), dtype=float)
    prev = values[0] if len(values) else np.nan
    for i in range(len(values)):
        prev = prev + smooth[i] * (values[i] - prev)
        out[i] = prev
    return pd.Series(out, index=series.index)


def aroon(high: pd.Series, low: pd.Series, n: int = 14) -> tuple[pd.Series, pd.Series]:
    up = high.rolling(n + 1, min_periods=1).apply(lambda x: float(np.argmax(x)) / n * 100.0, raw=True)
    down = low.rolling(n + 1, min_periods=1).apply(lambda x: (n - float(np.argmin(x))) / n * 100.0, raw=True)
    return up, down


def vortex(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> tuple[pd.Series, pd.Series]:
    tr = true_range(high, low, close).rolling(n, min_periods=1).sum()
    vm_plus = (high - low.shift(1)).abs().rolling(n, min_periods=1).sum()
    vm_minus = (low - high.shift(1)).abs().rolling(n, min_periods=1).sum()
    tr = tr.replace(0.0, np.nan)
    return vm_plus / tr, vm_minus / tr


def awesome_oscillator(high: pd.Series, low: pd.Series) -> pd.Series:
    median = (high + low) / 2.0
    return sma(median, 5) - sma(median, 34)


def ultimate_oscillator(
    high: pd.Series, low: pd.Series, close: pd.Series,
    fast: int = 7, mid: int = 14, slow: int = 28,
) -> pd.Series:
    prev_close = close.shift(1)
    true_low = pd.concat([low, prev_close], axis=1).min(axis=1)
    true_high = pd.concat([high, prev_close], axis=1).max(axis=1)
    bp = close - true_low
    tr = (true_high - true_low).replace(0.0, np.nan)

    def avg(n: int) -> pd.Series:
        return bp.rolling(n, min_periods=1).sum() / tr.rolling(n, min_periods=1).sum()

    return 100.0 * (4.0 * avg(fast) + 2.0 * avg(mid) + avg(slow)) / 7.0


def rvol(volume: pd.Series, n: int = 20) -> pd.Series:
    return volume / sma(volume, n).replace(0.0, np.nan)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [str(c).title() for c in d.columns]
    close, high, low, volume = d["Close"], d["High"], d["Low"], d["Volume"]

    d["ma20"] = sma(close, settings.ma_short)
    d["ma50"] = sma(close, settings.ma_mid)
    d["ma200"] = sma(close, settings.ma_long)
    d["ema9"] = ema(close, settings.ema_short)
    d["ema21"] = ema(close, settings.ema_mid)

    d["rsi"] = rsi(close, settings.rsi_period)
    d["rsi_ma"] = sma(d["rsi"], 14)

    macd_line, signal_line, hist = macd(
        close, settings.macd_fast, settings.macd_slow, settings.macd_signal
    )
    d["macd"] = macd_line
    d["macd_signal"] = signal_line
    d["macd_hist"] = hist

    bb_u, bb_m, bb_l = bollinger(close, settings.bb_period, settings.bb_std)
    d["bb_upper"], d["bb_mid"], d["bb_lower"] = bb_u, bb_m, bb_l
    d["bb_width"] = (bb_u - bb_l) / bb_m * 100.0

    d["atr"] = atr(high, low, close, settings.atr_period)
    d["atr_pct"] = d["atr"] / close * 100.0

    k_line, d_line = stochastic(high, low, close, settings.stoch_k, settings.stoch_d)
    d["stoch_k"], d["stoch_d"] = k_line, d_line

    srsi_k, srsi_d = stoch_rsi(close)
    d["stoch_rsi_k"], d["stoch_rsi_d"] = srsi_k, srsi_d

    d["cci"] = cci(high, low, close)
    d["williams_r"] = williams_r(high, low, close)

    adx_line, plus_di, minus_di = adx(high, low, close, settings.adx_period)
    d["adx"], d["plus_di"], d["minus_di"] = adx_line, plus_di, minus_di

    st_line, st_dir = supertrend(
        high, low, close, settings.supertrend_period, settings.supertrend_mult
    )
    d["supertrend"], d["st_dir"] = st_line, st_dir

    kc_u, kc_m, kc_l = keltner(high, low, close)
    d["kc_upper"], d["kc_mid"], d["kc_lower"] = kc_u, kc_m, kc_l

    ich = ichimoku(
        high, low, close,
        settings.ichimoku_tenkan, settings.ichimoku_kijun, settings.ichimoku_senkou,
    )
    d["tenkan"], d["kijun"] = ich["tenkan"], ich["kijun"]
    d["senkou_a"], d["senkou_b"] = ich["senkou_a"], ich["senkou_b"]

    d["vwap"] = rolling_vwap(high, low, close, volume)
    d["obv"] = obv(close, volume)
    d["obv_ma20"] = sma(d["obv"], 20)
    d["vol_ma20"] = sma(volume, 20)
    d["mfi"] = mfi(high, low, close, volume)
    d["cmf"] = cmf(high, low, close, volume)
    d["chandelier"] = chandelier(high, low, close, settings.trail_period, settings.trail_mult)

    w = settings.breakout_window
    d["high20"] = high.rolling(window=w, min_periods=1).max()
    d["low20"] = low.rolling(window=w, min_periods=1).min()

    ph, pl, pc = high.shift(1), low.shift(1), close.shift(1)
    pp = (ph + pl + pc) / 3.0
    rng = ph - pl
    d["pivot_pp"] = pp
    d["pivot_r1"] = 2 * pp - pl
    d["pivot_s1"] = 2 * pp - ph
    d["pivot_r2"] = pp + rng
    d["pivot_s2"] = pp - rng
    d["pivot_r3"] = ph + 2 * (pp - pl)
    d["pivot_s3"] = pl - 2 * (ph - pp)

    patterns = candle_patterns(d["Open"], high, low, close)
    for col in patterns.columns:
        d[f"cp_{col}"] = patterns[col]

    d["ret_1d"] = close.pct_change(1) * 100.0
    d["ret_5d"] = close.pct_change(5) * 100.0
    d["ret_20d"] = close.pct_change(20) * 100.0

    sqz_on, sqz_off, sqz_mom = squeeze_momentum(high, low, close)
    d["squeeze_on"] = sqz_on
    d["squeeze_off"] = sqz_off
    d["sqz_mom"] = sqz_mom
    d["sqz_dir"] = np.sign(sqz_mom.diff().fillna(0.0))

    d["chop"] = choppiness_index(high, low, close, 14)
    d["adr"], d["adr_pct"] = adr(high, low, close, 20)
    d["atr_pctl"] = d["atr_pct"].rolling(120, min_periods=20).rank(pct=True) * 100.0

    d["avwap"] = causal_anchored_vwap(high, low, close, volume, lookback=120, order=5)

    dc_n = 20
    d["dc_upper"] = high.rolling(dc_n, min_periods=1).max()
    d["dc_lower"] = low.rolling(dc_n, min_periods=1).min()
    d["dc_mid"] = (d["dc_upper"] + d["dc_lower"]) / 2.0

    efi = close.diff() * volume
    d["efi"] = ema(efi, 13)
    d["efi_signal"] = ema(d["efi"], 13)

    hl = np.log(high / low) ** 2
    co = np.log(close / close.shift(1)) ** 2
    gk = np.sqrt(np.clip((0.5 * hl) - ((2.0 * np.log(2.0) - 1.0) * co), 0.0, None))
    d["gk_vol"] = gk.rolling(20, min_periods=5).mean() * np.sqrt(252.0) * 100.0

    d["hma20"] = hma(close, 20)
    d["kama"] = kama(close)
    d["aroon_up"], d["aroon_down"] = aroon(high, low)
    d["vortex_plus"], d["vortex_minus"] = vortex(high, low, close)
    d["ao"] = awesome_oscillator(high, low)
    d["uo"] = ultimate_oscillator(high, low, close)
    d["rvol"] = rvol(volume)

    d["month"] = pd.DatetimeIndex(d.index).month

    return d
