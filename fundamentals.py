from __future__ import annotations

import threading
import time

import yfinance as yf

from data import to_yahoo

# Entri cache: (stempel waktu, payload, TTL entri). TTL disimpan per-entri agar
# hasil gagal/kosong (negatif) bisa dicache singkat tanpa mengubah bentuk respons.
_cache: dict[str, tuple[float, dict, float]] = {}
_cache_lock = threading.Lock()
_TTL = 21600.0

# Hasil kosong/gagal disimpan singkat untuk menahan banjir permintaan ulang ke
# Yahoo (ticker unik bergilir dari klien), lalu dicoba lagi.
_NEGATIVE_TTL = 300.0

# Batas keras jumlah entri cache fundamental. Key dibentuk dari ticker yang bisa
# datang dari klien (`GET /api/fundamental?ticker=...`, endpoint tanpa auth),
# sehingga tanpa batas ini cache tumbuh selamanya dan bisa menghabiskan memori
# pada proses berjalan lama (memory-DoS). Eviksi hanya memicu ambil ulang
# fundamental, bukan hasil yang salah. (Selaras dengan `news._CACHE_MAX`.)
_CACHE_MAX = 256

# Plafon panjang key normalisasi (``to_yahoo`` hanya upper/strip, tanpa batas
# panjang/charset). Ticker raksasa dari klien ditolak sebelum di-key agar tidak
# memperbesar memori tiap entri dan tidak memicu fetch Yahoo yang sia-sia.
_MAX_KEY_LEN = 16


def _clean(v):
    try:
        f = float(v)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return v


def _prune_cache_locked() -> None:
    """Buang entri fundamental kedaluwarsa lalu tertua bila melebihi batas.

    Dipanggil saat ``_cache_lock`` sedang dipegang. Hanya membuang entri dari
    cache; permintaan berikutnya akan mengambil ulang fundamental, bukan hasil
    yang salah. (Simetris dengan ``news._prune_cache_locked``.)
    """
    assert _cache_lock.locked(), "harus dipanggil dengan _cache_lock dipegang"
    fresh = time.time()
    expired = [k for k, (ts, _v, ttl) in _cache.items() if fresh - ts >= ttl]
    for key in expired:
        _cache.pop(key, None)
    excess = len(_cache) - _CACHE_MAX
    if excess <= 0:
        return
    oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[:excess]
    for key, _entry in oldest:
        _cache.pop(key, None)


def get_fundamentals(ticker: str) -> dict:
    yt = to_yahoo(ticker)
    if len(yt) > _MAX_KEY_LEN:
        return {"ticker": ticker.upper(), "error": "Kode saham tidak valid"}
    now = time.time()
    with _cache_lock:
        cached = _cache.get(yt)
        if cached and now - cached[0] < cached[2]:
            return cached[1]

    out: dict = {"ticker": ticker.upper()}
    info: dict = {}
    try:
        info = yf.Ticker(yt).info or {}
    except Exception:
        info = {}

    def g(*keys):
        for k in keys:
            v = info.get(k)
            if v is not None:
                return v
        return None

    out.update({
        "name": g("longName", "shortName"),
        "sector": g("sector"),
        "industry": g("industry"),
        "market_cap": _clean(g("marketCap")),
        "pe": _clean(g("trailingPE", "forwardPE")),
        "pb": _clean(g("priceToBook")),
        "roe": _clean(g("returnOnEquity")),
        "der": _clean(g("debtToEquity")),
        "eps": _clean(g("trailingEps")),
        "dividend_yield": _clean(g("dividendYield")),
        "profit_margin": _clean(g("profitMargins")),
        "revenue_growth": _clean(g("revenueGrowth")),
        "earnings_growth": _clean(g("earningsGrowth")),
        "beta": _clean(g("beta")),
        "high_52w": _clean(g("fiftyTwoWeekHigh")),
        "low_52w": _clean(g("fiftyTwoWeekLow")),
        "price": _clean(g("currentPrice", "regularMarketPrice")),
        "pe_forward": _clean(g("forwardPE")),
        "peg": _clean(g("pegRatio", "trailingPegRatio")),
        "ps": _clean(g("priceToSalesTrailing12Months")),
        "gross_margin": _clean(g("grossMargins")),
        "operating_margin": _clean(g("operatingMargins")),
        "current_ratio": _clean(g("currentRatio")),
        "book_value": _clean(g("bookValue")),
        "revenue": _clean(g("totalRevenue")),
        "net_income": _clean(g("netIncomeToCommon")),
        "ebitda": _clean(g("ebitda")),
        "free_cashflow": _clean(g("freeCashflow")),
        "cash": _clean(g("totalCash")),
        "debt": _clean(g("totalDebt")),
        "shares": _clean(g("sharesOutstanding")),
    })
    ttl = _TTL if info else _NEGATIVE_TTL
    with _cache_lock:
        _cache[yt] = (now, out, ttl)
        _prune_cache_locked()
    return out
