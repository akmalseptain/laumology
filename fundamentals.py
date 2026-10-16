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

# Dividen. yfinance lama mengirim pecahan (0,0627 = 6,27%). yfinance 1.x yang
# sekarang terpasang mengirim persen (6,27). Yield IDX di atas 25% sebagai
# pecahan tidak masuk akal; di atas 40% sebagai persen dibuang.
_YIELD_FRACTION_MAX = 0.25
_YIELD_PCT_MAX = 40.0

# Ambang layar bila sektor tidak dikenal. Bukan fakta "murah/mahal".
PE_RENDAH = 12.0
PE_WAJAR = 22.0
# Pita acuan PER TTM per sektor IDX: (batas bawah sedang, batas atas sedang).
# Di bawah batas pertama = rendah untuk sektor itu, di atas batas kedua = tinggi.
# Ini pita tetap, bukan median pasar hari ini.
_SECTOR_PE_BAND: dict[str, tuple[float, float]] = {
    "Perbankan": (8.0, 14.0),
    "Energi": (6.0, 12.0),
    "Batubara": (6.0, 12.0),
    "Tambang": (6.0, 12.0),
    "Teknologi": (18.0, 35.0),
    "Konsumer": (14.0, 28.0),
    "Kesehatan": (15.0, 30.0),
    "Telekomunikasi": (10.0, 18.0),
    "Properti": (8.0, 16.0),
    "Infrastruktur": (10.0, 20.0),
    "Industri": (8.0, 16.0),
    "Semen & Material": (8.0, 16.0),
    "Petrokimia": (8.0, 16.0),
    "Media": (10.0, 20.0),
    "Perdagangan": (10.0, 20.0),
    "Peternakan": (10.0, 20.0),
}
_YAHOO_SECTOR = {
    "financial services": "Perbankan",
    "banks": "Perbankan",
    "energy": "Energi",
    "technology": "Teknologi",
    "consumer defensive": "Konsumer",
    "consumer cyclical": "Konsumer",
    "communication services": "Telekomunikasi",
    "real estate": "Properti",
    "healthcare": "Kesehatan",
    "industrials": "Industri",
    "utilities": "Infrastruktur",
}
ROE_BAIK = 0.15


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


def _yield_from_cash(rate, price) -> float | None:
    """Yield persen = dividen per saham / harga × 100. Definisi, bukan label Yahoo."""
    rate_f = _clean(rate)
    price_f = _clean(price)
    if rate_f is None or price_f is None or price_f <= 0 or rate_f < 0:
        return None
    y = rate_f / price_f * 100.0
    if y > _YIELD_PCT_MAX:
        return None
    return y


def _published_yield_pct(raw) -> float | None:
    """Satu satuan persen untuk field yield Yahoo (pecahan lama atau persen baru)."""
    y = _clean(raw)
    if y is None or y < 0:
        return None
    if y <= _YIELD_FRACTION_MAX:
        y *= 100.0
    if y > _YIELD_PCT_MAX:
        return None
    return round(y, 4)


def _normalize_dividend(raw, price, rate) -> tuple[float | None, str | None, str | None]:
    """Yield yang ditampilkan, basis, dan catatan bila angka tunai bertentangan.

    Angka utama adalah yield yang Yahoo terbitkan. Dividen per saham / harga
    hanya dipakai bila yield itu kosong, atau disebut sebagai pembanding.
    Nilai tunai debu (misalnya 0,007 pada harga ribuan) tidak boleh menimpa yield.
    """
    published = _published_yield_pct(raw)
    cash = _yield_from_cash(rate, price)
    if published is not None and published >= 1.0 and cash is not None and cash < 0.05:
        cash = None
        dust = True
    else:
        dust = False
    if published is not None:
        note = None
        if dust:
            note = "Dividen per saham dari sumber tidak masuk akal dan diabaikan."
        elif cash is not None and abs(cash - published) / published > 0.25:
            note = (f"Trailing dividen/harga {cash:.2f}% berbeda dari yield {published:.2f}%. "
                    "Yang ditampilkan adalah yield sumber.")
        elif cash is not None:
            note = f"Trailing dividen/harga {cash:.2f}%."
        return published, "yield sumber", note
    if cash is not None:
        return round(cash, 4), "dividen per saham / harga", None
    return None, None, None


def sector_band_name(ticker: str, yahoo_sector: str | None = None) -> str:
    """Nama sektor untuk pita PER. Peta lokal menang; Yahoo hanya bila ticker belum dikenal."""
    from config import sector_of

    local = sector_of(ticker or "")
    if local != "Lainnya":
        return local
    return _YAHOO_SECTOR.get((yahoo_sector or "").strip().lower(), "")


def _pe_limits(sector: str | None) -> tuple[float, float, str]:
    name = (sector or "").strip()
    band = _SECTOR_PE_BAND.get(name)
    if band is None:
        return PE_RENDAH, PE_WAJAR, ""
    return band[0], band[1], name


def classify_ratios(pe, roe, der, sector: str | None = None) -> dict:
    """Label fundamental yang sama untuk layar dan musyawarah.

    DER yang kosong tidak dihitung sehat. PER forward tidak masuk ke sini.
    Sektor yang dikenal memakai pita PER sektor. Tanpa sektor, ambang layar lama.
    """
    pe_f = _clean(pe)
    roe_f = _clean(roe)
    der_f = _clean(der)
    low, high, sector_name = _pe_limits(sector)
    if pe_f is None:
        valuation_code, valuation_label = "n/a", "PER TTM tidak tersedia"
        valuation_note = "Tanpa EPS positif, PER TTM tidak dihitung. PER forward tidak dipakai sebagai pengganti."
    elif pe_f < low:
        valuation_code, valuation_label = "rendah", "PER TTM rendah"
        if sector_name:
            valuation_note = (f"PER TTM di bawah {low:.0f}, batas rendah pita {sector_name} "
                              f"({low:.0f}–{high:.0f}). Pita acuan, bukan median hari ini.")
        else:
            valuation_note = f"PER TTM di bawah {low:.0f}. Sektor tidak dikenal, jadi ambang layar umum."
    elif pe_f < high:
        valuation_code, valuation_label = "wajar", "PER TTM sedang"
        if sector_name:
            valuation_note = (f"PER TTM di dalam pita {sector_name} ({low:.0f}–{high:.0f}). "
                              "Pita acuan, bukan median hari ini.")
        else:
            valuation_note = f"PER TTM {low:.0f}–{high:.0f}. Sektor tidak dikenal, jadi ambang layar umum."
    else:
        valuation_code, valuation_label = "tinggi", "PER TTM tinggi"
        if sector_name:
            valuation_note = (f"PER TTM di atas {high:.0f}, batas atas pita {sector_name} "
                              f"({low:.0f}–{high:.0f}). Pita acuan, bukan median hari ini.")
        else:
            valuation_note = f"PER TTM di atas {high:.0f}. Sektor tidak dikenal, jadi ambang layar umum."

    if roe_f is None:
        quality_code, quality_label = "n/a", "ROE tidak tersedia"
        quality_note = "ROE kosong, kualitas tidak dinilai."
    elif roe_f < 0:
        quality_code, quality_label = "rugi", "Rugi"
        quality_note = "ROE negatif."
    elif roe_f >= ROE_BAIK and der_f is not None and 0 <= der_f < 100:
        quality_code, quality_label = "baik", "Kualitas baik"
        quality_note = "ROE minimal 15% dan DER di bawah 100."
    elif der_f is None:
        quality_code, quality_label = "sedang", "Kualitas belum lengkap"
        quality_note = "ROE ada, DER tidak tersedia. Tidak dinilai sehat hanya dari ROE."
    else:
        quality_code, quality_label = "sedang", "Kualitas sedang"
        quality_note = "ROE di bawah 15% atau DER 100 ke atas."
    return {
        "valuation_code": valuation_code,
        "valuation_label": valuation_label,
        "valuation_note": valuation_note,
        "quality_code": quality_code,
        "quality_label": quality_label,
        "quality_note": quality_note,
        "sector_band": sector_name or None,
        "pe_band_low": low,
        "pe_band_high": high,
    }


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


def _as_frame(value):
    """Hanya DataFrame berisi angka. Objek mock atau kosong diabaikan."""
    import pandas as pd
    if isinstance(value, pd.DataFrame) and not value.empty:
        return value
    return None


def _series_numbers(frame, labels: tuple[str, ...]) -> list[float]:
    """Nilai baris laporan, dari periode terbaru. Label dicocokkan tanpa besar-kecil."""
    if frame is None:
        return []
    index = {str(name).strip().lower(): name for name in frame.index}
    row = None
    for label in labels:
        key = index.get(label.lower())
        if key is not None:
            row = frame.loc[key]
            break
    if row is None:
        return []
    numbers = []
    for value in list(row):
        number = _clean(value)
        if number is not None:
            numbers.append(number)
    return numbers


def _fill_from_statements(ticker_obj, out: dict, checks: list[str]) -> None:
    """Isi rasio dari laporan bila ringkasan Yahoo kosong.

    Empat kuartal dijumlahkan menjadi TTM. Kalau kuartal tidak lengkap, pakai
    laporan tahunan. Satu atau dua kuartal tidak dikali empat.
    """
    if ticker_obj is None:
        return
    if any(out.get(key) is not None for key in ("eps", "pe", "pb", "roe")):
        return
    try:
        income_q = _as_frame(getattr(ticker_obj, "quarterly_income_stmt", None))
        income_a = _as_frame(getattr(ticker_obj, "income_stmt", None))
        balance_q = _as_frame(getattr(ticker_obj, "quarterly_balance_sheet", None))
        balance_a = _as_frame(getattr(ticker_obj, "balance_sheet", None))
    except Exception:
        return
    if income_q is None and income_a is None and balance_q is None and balance_a is None:
        return
    ni_labels = ("Net Income", "Net Income Common Stockholders")
    quarterly_ni = _series_numbers(income_q, ni_labels)
    if len(quarterly_ni) >= 4:
        ttm_income = sum(quarterly_ni[:4])
    else:
        annual_ni = _series_numbers(income_a, ni_labels)
        ttm_income = annual_ni[0] if annual_ni else None
    balance = balance_q if balance_q is not None else balance_a
    equity_vals = _series_numbers(balance, (
        "Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest",
    ))
    share_vals = _series_numbers(balance, ("Ordinary Shares Number", "Share Issued"))
    debt_vals = _series_numbers(balance, ("Total Debt",))
    equity = equity_vals[0] if equity_vals else None
    shares = out.get("shares") or (share_vals[0] if share_vals else None)
    if out.get("shares") is None and shares:
        out["shares"] = shares
    if ttm_income is not None:
        out["net_income"] = out.get("net_income") or ttm_income
    if shares and shares > 0 and ttm_income is not None and out.get("eps") is None:
        out["eps"] = round(ttm_income / shares, 4)
    if shares and shares > 0 and equity is not None and equity > 0 and out.get("book_value") is None:
        out["book_value"] = round(equity / shares, 4)
    if equity and equity > 0 and ttm_income is not None and out.get("roe") is None:
        out["roe"] = round(ttm_income / equity, 4)
    if equity and equity > 0 and debt_vals and out.get("der") is None:
        out["der"] = round(debt_vals[0] / equity * 100.0, 4)
    revenue = _series_numbers(income_q, ("Total Revenue",))
    if len(revenue) >= 4 and out.get("revenue") is None:
        out["revenue"] = sum(revenue[:4])
    elif out.get("revenue") is None:
        annual_rev = _series_numbers(income_a, ("Total Revenue",))
        if annual_rev:
            out["revenue"] = annual_rev[0]
    if out.get("eps") is not None or out.get("book_value") is not None:
        checks.append("Rasio dihitung dari laporan Yahoo karena ringkasan emiten kosong.")


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
        "pe": _ratio(g("trailingPE")),
        "pb": _ratio(g("priceToBook")),
        "roe": _clean(g("returnOnEquity")),
        "der": _ratio(g("debtToEquity")),
        "eps": _clean(g("trailingEps")),
        "dividend_yield": None,
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
    checks: list[str] = []
    _fill_from_statements(t, out, checks)
    mismatch: list[str] = []
    # PER TTM = harga / EPS. Harus cocok dengan angka di layar. PER forward tidak
    # pernah disalin ke kolom PER TTM.
    price = out.get("price")
    eps = out.get("eps")
    if price is not None and eps is not None and eps > 0 and price > 0:
        calc_pe = price / eps
        if 0 < calc_pe <= _RATIO_MAX:
            reported = out.get("pe")
            if reported is None or abs(calc_pe - reported) / max(reported, 1e-9) > 0.02:
                if reported is not None:
                    checks.append("PER Yahoo selisih lebih dari 2% dari harga/EPS; dipakai harga/EPS.")
                    mismatch.append("pe")
                else:
                    checks.append("PER TTM dihitung dari harga / EPS.")
                out["pe"] = round(calc_pe, 4)
            else:
                checks.append("PER TTM selaras dengan harga / EPS (selisih ≤ 2%).")
        else:
            out["pe"] = None
            checks.append("PER harga/EPS di luar batas 500 dan dibuang.")
    elif eps is not None and eps <= 0:
        out["pe"] = None
        checks.append("EPS tidak positif. PER TTM dikosongkan. PER forward tetap terpisah.")
    book = out.get("book_value")
    if price is not None and book is not None and price > 0:
        if book <= 0:
            out["book_value"] = None
            out["pb"] = None
            checks.append("Nilai buku tidak positif dan dibuang.")
        else:
            calc_pb = price / book
            if calc_pb > _RATIO_MAX or calc_pb < 0.01:
                out["book_value"] = None
                out["pb"] = None
                mismatch.append("book_value")
                checks.append("Nilai buku tidak masuk akal terhadap harga. PBV dan nilai buku dikosongkan.")
            else:
                reported_pb = out.get("pb")
                if reported_pb is None or abs(calc_pb - reported_pb) / max(reported_pb, 1e-9) > 0.02:
                    out["pb"] = round(calc_pb, 4)
                    checks.append("PBV dihitung dari harga / nilai buku.")
                else:
                    checks.append("PBV selaras dengan harga / nilai buku (selisih ≤ 2%).")
    div_rate = _clean(g("trailingAnnualDividendRate", "dividendRate"))
    div_raw = g("dividendYield", "trailingAnnualDividendYield")
    dividend, div_basis, div_note = _normalize_dividend(div_raw, price, div_rate)
    out["dividend_yield"] = dividend
    out["dividend_basis"] = div_basis
    if dividend is not None and div_basis:
        checks.append(f"Dividen {dividend:.2f}% ({div_basis}).")
    if div_note:
        checks.append(div_note)
        if "diabaikan" in div_note or "berbeda" in div_note:
            mismatch.append("dividend")
    band = sector_band_name(ticker, out.get("sector") if isinstance(out.get("sector"), str) else None)
    labels = classify_ratios(out.get("pe"), out.get("roe"), out.get("der"), sector=band or None)
    out.update(labels)
    out["checks"] = checks
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
    for flag in mismatch:
        if flag not in suspects:
            suspects.append(flag)
    out["suspect"] = suspects
    ttl = _TTL if out["available"] else _NEGATIVE_TTL
    with _cache_lock:
        _cache[yt] = (now, out, ttl)
        _prune_cache_locked()
    return out
