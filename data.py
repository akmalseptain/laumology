from __future__ import annotations

import threading
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from config import settings


def to_yahoo(ticker: str, suffix: str = ".JK") -> str:
    t = ticker.upper().strip()
    if suffix and not t.endswith(suffix):
        t = f"{t}{suffix}"
    return t


def _cache_path(ticker: str, period: str, interval: str) -> Path:
    safe = ticker.replace(".", "_").replace("^", "idx_")
    return Path(settings.cache_dir) / f"{safe}_{period}_{interval}.csv"


def _is_fresh(path: Path, ttl_hours: float) -> bool:
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    return age_hours < ttl_hours


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        chosen = df.columns.get_level_values(0)
        for lvl in range(df.columns.nlevels):
            values = [str(v).lower() for v in df.columns.get_level_values(lvl)]
            if "close" in values:
                chosen = df.columns.get_level_values(lvl)
                break
        df.columns = chosen
    renamed = {c: str(c).title() for c in df.columns}
    df = df.rename(columns=renamed)
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].copy()
    for col in keep:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df.index = pd.to_datetime(df.index)
    return df


def get_ohlcv(
    ticker: str,
    period: str | None = None,
    interval: str | None = None,
    use_cache: bool = True,
    suffix: str = ".JK",
) -> pd.DataFrame:
    period = period or settings.period
    interval = interval or settings.interval
    yt = to_yahoo(ticker, suffix)
    path = _cache_path(yt, period, interval)

    if use_cache and _is_fresh(path, settings.cache_ttl_hours):
        cached = pd.read_csv(path, index_col=0, parse_dates=True)
        if not cached.empty:
            return cached

    raw = yf.download(
        yt,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if raw is None or raw.empty:
        if path.exists():
            return pd.read_csv(path, index_col=0, parse_dates=True)
        raise ValueError(f"Tidak ada data untuk {ticker} ({yt})")

    df = _normalize(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    return df


def get_many(
    tickers: list[str],
    period: str | None = None,
    interval: str | None = None,
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            df = get_ohlcv(t, period, interval, use_cache)
            if len(df) > 60:
                out[t.upper()] = df
        except Exception as exc:
            print(f"  ! {t}: {exc}")
    return out


def prefetch(
    tickers: list[str],
    period: str | None = None,
    interval: str | None = None,
    chunk: int = 60,
    suffix: str = ".JK",
) -> int:
    """Unduh banyak ticker sekaligus (batch) lalu simpan ke cache per ticker.

    Ini yang membuat scan seluruh emiten IDX tetap realistis (1 request per
    ~60 ticker, bukan 1 request per ticker).
    """
    period = period or settings.period
    interval = interval or settings.interval
    yts = [to_yahoo(t, suffix) for t in tickers]
    done = 0
    for i in range(0, len(yts), chunk):
        part = yts[i: i + chunk]
        try:
            raw = yf.download(
                part, period=period, interval=interval, auto_adjust=True,
                progress=False, threads=True, group_by="ticker",
            )
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        for yt in part:
            sub = None
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    if yt in raw.columns.get_level_values(0):
                        sub = raw[yt]
                    elif yt in raw.columns.get_level_values(-1):
                        sub = raw.xs(yt, axis=1, level=-1)
                elif len(part) == 1:
                    sub = raw
            except Exception:
                sub = None
            if sub is None or sub.empty:
                continue
            try:
                df = _normalize(sub)
                if df is not None and not df.empty:
                    path = _cache_path(yt, period, interval)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    df.to_csv(path)
                    done += 1
            except Exception:
                continue
    return done


_quote_cache: dict[str, tuple[float, dict]] = {}
_quote_lock = threading.Lock()


def _fi_num(fi, *names) -> float | None:
    for n in names:
        v = None
        try:
            v = getattr(fi, n)
        except Exception:
            v = None
        if v is None:
            try:
                v = fi[n]
            except Exception:
                v = None
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _quote_from_history(yt: str, now: float) -> dict | None:
    try:
        t = yf.Ticker(yt)
        h = t.history(period="1d", interval="1m", auto_adjust=True)
        if h is None or h.empty:
            h = t.history(period="5d", interval="1d", auto_adjust=True)
        if h is None or h.empty:
            return None
        return {
            "symbol": yt,
            "last": float(h["Close"].iloc[-1]),
            "prev_close": float(h["Close"].iloc[-2]) if len(h) > 1 else None,
            "open": float(h["Open"].iloc[-1]),
            "day_high": float(h["High"].max()),
            "day_low": float(h["Low"].min()),
            "volume": float(h["Volume"].iloc[-1]),
            "time": now,
        }
    except Exception:
        return None


def get_quote(ticker: str, suffix: str = ".JK", ttl: float | None = None) -> dict | None:
    yt = to_yahoo(ticker, suffix)
    now = time.time()
    ttl = settings.quote_ttl_seconds if ttl is None else ttl
    with _quote_lock:
        cached = _quote_cache.get(yt)
        if cached and now - cached[0] < ttl:
            return cached[1]

    quote = None
    try:
        import realtime

        quote = realtime.fetch_quote(yt)
    except Exception:
        quote = None

    if quote is None or quote.get("last") is None:
        quote = _yf_quote(yt, now)

    if quote and quote.get("last") is not None:
        with _quote_lock:
            _quote_cache[yt] = (now, quote)
        return quote
    return None


def _yf_quote(yt: str, now: float) -> dict | None:
    quote = None
    try:
        fi = yf.Ticker(yt).fast_info
        last = _fi_num(fi, "last_price", "lastPrice", "regularMarketPrice")
        if last is not None:
            quote = {
                "symbol": yt,
                "last": last,
                "prev_close": _fi_num(fi, "previous_close", "previousClose", "regularMarketPreviousClose"),
                "open": _fi_num(fi, "open"),
                "day_high": _fi_num(fi, "day_high", "dayHigh"),
                "day_low": _fi_num(fi, "day_low", "dayLow"),
                "volume": _fi_num(fi, "last_volume", "lastVolume"),
                "time": now,
                "source": "yfinance",
            }
    except Exception:
        quote = None

    if quote is None or quote.get("last") is None:
        quote = _quote_from_history(yt, now)
        if quote:
            quote["source"] = "yfinance(1m)"
    return quote


def apply_live_quote(
    df: pd.DataFrame, quote: dict | None, interval: str = "1d"
) -> tuple[pd.DataFrame, dict | None]:
    if not quote or quote.get("last") is None or df is None or df.empty:
        return df, None

    price = float(quote["last"])
    prev = quote.get("prev_close")
    out = df.copy()

    if interval in ("1d", "1wk", "1mo"):
        today = pd.Timestamp.now().normalize()
        last_idx = pd.Timestamp(out.index[-1]).normalize()
        if last_idx < today:
            out.loc[today] = {
                "Open": quote.get("open") or price,
                "High": quote.get("day_high") or price,
                "Low": quote.get("day_low") or price,
                "Close": price,
                "Volume": quote.get("volume") or 0.0,
            }
        else:
            i = len(out) - 1
            out.iloc[i, out.columns.get_loc("Close")] = price
            if quote.get("day_high"):
                out.iloc[i, out.columns.get_loc("High")] = max(float(out["High"].iloc[i]), quote["day_high"])
            if quote.get("day_low"):
                out.iloc[i, out.columns.get_loc("Low")] = min(float(out["Low"].iloc[i]), quote["day_low"])
    else:
        out.iloc[-1, out.columns.get_loc("Close")] = price

    out = out[~out.index.duplicated(keep="last")].sort_index()
    meta = {
        "price": price,
        "prev_close": prev,
        "live": True,
        "source": quote.get("source"),
        "day_high": quote.get("day_high"),
        "day_low": quote.get("day_low"),
        "quote_time": quote.get("time"),
    }
    return out, meta
