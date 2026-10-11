from __future__ import annotations

import os
import re
import tempfile
import threading
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from config import settings

# Hanya karakter ini yang boleh muncul pada komponen nama berkas cache.
# Pemisah path (``/`` dan ``\``) serta ``:`` (drive Windows/UNC) diganti ``_``
# agar ``ticker`` dari klien tidak bisa keluar dari ``settings.cache_dir``.
_CACHE_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


def to_yahoo(ticker: str, suffix: str = ".JK") -> str:
    t = ticker.upper().strip()
    if suffix and not t.endswith(suffix):
        t = f"{t}{suffix}"
    return t


def _cache_path(ticker: str, period: str, interval: str) -> Path:
    safe = ticker.replace(".", "_").replace("^", "idx_")
    safe = _CACHE_SAFE.sub("_", safe)
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


def _drop_corrupt(path: Path) -> None:
    """Hapus berkas cache rusak secara best-effort.

    Penghapusan bisa gagal karena race baca paralel (terutama di Windows).
    Kegagalan itu diabaikan agar guard justru tidak menjadi sumber error baru.
    """
    try:
        path.unlink()
    except OSError:
        pass


def _read_cache(path: Path) -> pd.DataFrame | None:
    """Baca cache CSV dengan jaring pengaman untuk berkas rusak/terpotong.

    Berkas cache bisa 0-byte atau terpotong bila proses di-kill saat menulis
    (``to_csv`` di sini tak atomik). Tanpa guard, ``pd.read_csv`` melempar
    ``EmptyDataError``/``ParserError`` dan ticker rusak sampai TTL habis.
    Di sini hanya error *parse cache* yang ditangkap: berkas rusak dihapus,
    lalu ``None`` dikembalikan agar pemanggil bisa mengunduh ulang. Jalur
    cache valid tak berubah sama sekali.
    """
    try:
        return pd.read_csv(path, index_col=0, parse_dates=True)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, OSError):
        _drop_corrupt(path)
        return None


def _write_cache(df: pd.DataFrame, path: Path) -> None:
    """Tulis cache CSV secara atomik.

    ``df.to_csv(path)`` langsung tidak atomik: bila proses di-kill di tengah
    tulis, tersisa CSV separuh yang lolos sebagai "segar" di ``_is_fresh`` dan
    diterima ``_read_cache`` (pendek-tapi-valid). Di sini tulis ke berkas
    sementara unik di direktori yang sama, lalu ``os.replace`` (atomik pada
    volume yang sama, termasuk Windows). Temp dibersihkan di ``finally`` agar
    direktori cache tidak penuh sampah bila penulisan gagal.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        # mkstemp mengembalikan fd terbuka; wajib ditutup sebelum to_csv agar
        # berkas tidak terkunci (Windows) saat os.replace.
        os.close(fd)
        df.to_csv(tmp)
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                # Windows: reader paralel (mis. screener) bisa sedang memegang
                # path. Coba beberapa kali sebelum menyerah.
                last_err = exc
                time.sleep(0.05 * (attempt + 1))
        if last_err is not None:
            raise last_err
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


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
        cached = _read_cache(path)
        if cached is not None and not cached.empty:
            return cached

    raw = None
    last_err: Exception | None = None
    for _attempt in range(2):
        try:
            raw = yf.download(
                yt,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception as exc:  # termasuk 401 "Invalid Crumb" sesaat
            raw = None
            last_err = exc
        if raw is not None and not raw.empty:
            break
        time.sleep(1.0)

    if raw is None or raw.empty:
        if path.exists():
            cached = _read_cache(path)
            if cached is not None and not cached.empty:
                return cached
        if last_err is not None:
            raise last_err
        raise ValueError(f"Tidak ada data untuk {ticker} ({yt})")

    df = _normalize(raw)
    _write_cache(df, path)
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
                    _write_cache(df, path)
                    done += 1
            except Exception:
                continue
    return done


_quote_cache: dict[str, tuple[float, dict]] = {}
_quote_lock = threading.Lock()

# Batas keras jumlah entri cache quote. Key dibentuk dari ticker yang bisa
# datang dari klien (`/api/quote?ticker=...`), sehingga tanpa batas ini cache
# tumbuh selamanya selama quote masih segar dan bisa menghabiskan memori pada
# proses berjalan lama. Eviksi hanya memicu ambil ulang quote yang sama, bukan
# hasil yang salah. (Selaras dengan `ttlcache._MAX_ENTRIES`.)
_QUOTE_CACHE_MAX = 512


def _prune_quote_cache_locked() -> None:
    """Buang entri quote tertua bila melebihi batas.

    Dipanggil saat ``_quote_lock`` sedang dipegang. Hanya membuang entri dari
    cache; permintaan berikutnya untuk ticker itu akan mengambil ulang quote.
    """
    assert _quote_lock.locked(), "harus dipanggil dengan _quote_lock dipegang"
    excess = len(_quote_cache) - _QUOTE_CACHE_MAX
    if excess <= 0:
        return
    oldest = sorted(_quote_cache.items(), key=lambda kv: kv[1][0])[:excess]
    for key, _entry in oldest:
        _quote_cache.pop(key, None)


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
        if cached:
            if now - cached[0] < ttl:
                return cached[1]
            _quote_cache.pop(yt, None)

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
            _prune_quote_cache_locked()
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
