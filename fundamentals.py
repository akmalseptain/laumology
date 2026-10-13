from __future__ import annotations

import math
import threading
import time

import yfinance as yf

import data
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

# Field kunci yang menentukan payload fundamental benar-benar terisi. Bukan
# ``if info`` (truthiness mentah) karena Yahoo bisa mengembalikan dict parsial
# (mis. hanya ``{"sector": ...}``) yang truthy padahal finansial kosong.
_KEY_FIELDS = ("price", "pe", "pb")

# Field finansial (berasal laporan keuangan, bukan harga pasar). Dipakai untuk
# memisahkan "hanya harga yang tersedia" dari data fundamental sungguhan,
# sehingga emiten rugi/tanpa PER-PBV tetap bisa tampil tanpa mengklaim
# rasio yang sebenarnya kosong.
_FIN_FIELDS = ("pe", "pb", "roe", "eps")

# Rentang rasio. Di luar ini nilai mustahil secara akuntansi (PER/PBV negatif
# atau > 500, DER negatif) -> ``None`` agar tidak menyesatkan keputusan.
# Nilai ekstrem namun sah (mis. PBV bank dengan book value tipis) tetap
# dipertahankan namun ditandai ``suspect`` untuk transparansi.
_RATIO_MAX = 500.0
_SUSPECT_PE = 200.0
_SUSPECT_PB = 20.0
_SUSPECT_DER = 500.0


def _clean(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _ratio(v, maxv: float = _RATIO_MAX, minv: float = 0.0):
    """Bersihkan rasio lalu buang hanya nilai mustahil (negatif / > batas)."""
    f = _clean(v)
    if f is None or f < minv or f > maxv:
        return None
    return f


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


def _fallback_price(yt: str) -> float | None:
    """Resolusi harga terakhir dari layer ``data`` saat ``.info`` parsial.

    Memakai ``data.get_quote`` (fast_info + fallback riwayat 1m yang sudah
    ter-cache) lalu ``data.get_ohlcv`` untuk emiten tanpa ``currentPrice``.
    Semua kegagalan ditelan (best-effort) agar resolusi fundamental tak pernah
    melempar ke pemanggil dan nilai non-finit tetap mengembalikan ``None``.
    """
    try:
        quote = data.get_quote(yt)
    except Exception:
        quote = None
    if isinstance(quote, dict):
        p = _clean(quote.get("last"))
        if p is not None:
            return p
    try:
        df = data.get_ohlcv(yt)
    except Exception:
        return None
    try:
        if df is not None and not df.empty:
            return _clean(df["Close"].iloc[-1])
    except Exception:
        return None
    return None


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
    # ``fetch_ok`` memisahkan kegagalan fetch (transien) dari data kosong yang
    # sah, supaya kegagalan jaringan tidak pernah ditandai sebagai data sah.
    fetch_ok = False
    t = None
    try:
        t = yf.Ticker(yt)
        info = t.info or {}
        fetch_ok = True
    except Exception:
        info = {}
    if not info and t is not None:
        # Fallback untuk error transien: ``get_info()`` memakai jalur yang
        # sama dengan ``.info`` di yfinance, jadi berguna saat panggilan
        # pertama gagal, bukan saat Yahoo memang mengembalikan data kosong.
        try:
            fallback = t.get_info() or {}
            if isinstance(fallback, dict) and fallback:
                info = fallback
                fetch_ok = True
        except Exception:
            pass

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
        "pe": _ratio(g("trailingPE", "forwardPE")),
        "pb": _ratio(g("priceToBook")),
        "roe": _clean(g("returnOnEquity")),
        "der": _ratio(g("debtToEquity")),
        "eps": _clean(g("trailingEps")),
        "dividend_yield": _clean(g("dividendYield")),
        "profit_margin": _clean(g("profitMargins")),
        "revenue_growth": _clean(g("revenueGrowth")),
        "earnings_growth": _clean(g("earningsGrowth")),
        "beta": _clean(g("beta")),
        "high_52w": _clean(g("fiftyTwoWeekHigh")),
        "low_52w": _clean(g("fiftyTwoWeekLow")),
        "price": _clean(g("currentPrice", "regularMarketPrice")),
        "pe_forward": _ratio(g("forwardPE")),
        "peg": _ratio(g("pegRatio", "trailingPegRatio")),
        "ps": _ratio(g("priceToSalesTrailing12Months")),
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
    # Bila ``.info`` parsial (umum pada emiten rugi/tanpa book value), lengkapi
    # harga dari layer ``data`` yang sudah andal. Hanya bila info benar-benar
    # tak memberi harga agar tak menimpa nilai resmi dari Yahoo.
    if out["price"] is None:
        out["price"] = _fallback_price(yt)
    # Market cap turunan (harga x lembar saham) sebagai jaring pengaman bila
    # ``marketCap`` tak tersedia; tidak mengubah rumus rasio apa pun.
    if out["market_cap"] is None and out["price"] is not None and out["shares"]:
        out["market_cap"] = _clean(out["price"] * out["shares"])
    # ``has_financials`` terpisah dari ketersediaan harga: emiten dengan harga
    # tapi tanpa rasio tetap ``available`` namun ditandai agar UI tidak
    # menampilkan label "data tidak tersedia" yang menyesatkan.
    out["has_financials"] = any(out.get(k) is not None for k in _FIN_FIELDS)
    # ``available`` berbasis field kunci, bukan truthiness ``info`` mentah.
    out["available"] = any(out.get(k) is not None for k in _KEY_FIELDS)
    # Alasan eksplisit: kegagalan fetch (transien) dibedakan dari data kosong sah.
    if out["available"]:
        out["reason"] = "ok"
    elif fetch_ok:
        out["reason"] = "empty"
    else:
        out["reason"] = "error"
    suspects = []
    if out["pe"] is not None and out["pe"] > _SUSPECT_PE:
        suspects.append("pe")
    if out["pb"] is not None and out["pb"] > _SUSPECT_PB:
        suspects.append("pb")
    if out["der"] is not None and out["der"] > _SUSPECT_DER:
        suspects.append("der")
    out["suspect"] = suspects
    ttl = _TTL if out["available"] else _NEGATIVE_TTL
    with _cache_lock:
        _cache[yt] = (now, out, ttl)
        _prune_cache_locked()
    return out
