"""Tekanan di luar teknikal dan fundamental emiten.

Lapisan ini tidak mengubah skor teknikal. Musyawarah memakai status
tekanan_luar / dukungan_luar yang sudah terkonfirmasi untuk vote sentimen.
Ia menjelaskan apakah
pergerakan lebih mirip tekanan pasar (MSCI/FTSE, arus asing, kurs, suku bunga,
komoditas, bursa global) atau khas emiten. Penyebab disebut hanya bila judul
berita atau proksi harga benar-benar menunjuk ke sana.
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import data
import market
import news

# Ambang persen. Didokumentasikan supaya bukan angka siluman:
# - IHSG 1 hari ±1% atau 5 hari ±3% = gejolak pasar yang layak dijelaskan.
# - USD/IDR 5 hari ±1% = rupiah bergerak cukup untuk menekan/menopang aset IDR.
# - S&P 500 5 hari ±2% = risiko global yang biasa ikut terasa di IDX.
# - Saham 1 hari ±1,5% dan selisih ≥1 poin vs IHSG = gerak khas emiten.
IHSG_SHOCK_1D = 1.0
IHSG_SHOCK_5D = 3.0
USDIDR_STRESS_5D = 1.0
GLOBAL_SHOCK_5D = 2.0
STOCK_IDIO_1D = 1.5
STOCK_DIVERGE = 1.0

_BUNDLE_TTL = 600.0
_bundle_lock = threading.Lock()
_bundle_cache: dict = {"ts": 0.0, "data": None}

# Kueri pendek (AND di mesin berita). Sengaja terpisah agar "MSCI" tidak
# hilang hanya karena judul tidak menyebut rupiah sekaligus.
MACRO_QUERIES = (
    "IHSG MSCI",
    "IHSG FTSE",
    "IHSG investor asing",
    "rupiah dolar IHSG",
    "suku bunga Fed IHSG",
    "IHSG Wall Street",
)

# (id, label, jarum pada berita makro)
_THEMES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("indeks_pasif", "Rebalancing indeks (MSCI/FTSE)",
     ("msci", "ftse", "rebalancing", "rebalance")),
    ("arus_asing", "Arus dana asing",
     ("investor asing", "dana asing", "asing jual", "asing beli", "net sell",
      "net buy", "foreign sell", "foreign inflow", "net foreign",
      "capital outflow", "capital inflow")),
    ("kurs", "Kurs rupiah",
     ("rupiah", "usd/idr", "kurs dolar", "pelemahan rupiah")),
    ("suku_bunga", "Suku bunga",
     ("suku bunga", "the fed", "fomc", "bi rate", "bank indonesia")),
    ("komoditas", "Harga komoditas",
     ("batu bara", "nikel", "cpo", "minyak mentah", "brent", "harga emas")),
    ("global", "Pasar global",
     ("wall street", "bursa global", "risk-off", "risk off", "nasdaq",
      "s&p", "geopolitik")),
    ("regulasi", "Kebijakan pasar",
     ("ojk", "auto rejection", "pajak dividen")),
)

# Berita emiten lebih sempit: "batu bara" di judul saham tambang bukan
# serta-merta tekanan makro seluruh pasar.
_TICKER_NEEDLES: dict[str, tuple[str, ...]] = {
    "indeks_pasif": ("msci", "ftse", "rebalancing", "rebalance"),
    "arus_asing": ("investor asing", "dana asing", "asing jual", "asing beli",
                   "net foreign", "foreign sell", "foreign inflow"),
    "kurs": ("rupiah", "usd/idr"),
    "suku_bunga": ("suku bunga", "the fed", "fomc", "bi rate"),
    "global": ("wall street", "bursa global", "risk-off", "risk off"),
}

# Tema arus/indeks yang disebut tanpa kata arah tetap diikatkan ke gejolak
# IHSG. "MSCI umumkan rebalancing" + IHSG -2% dibaca sebagai tekanan, bukan
# diabaikan. Tema lain butuh kata arah supaya tidak salah tembak.
_FLOW_THEMES = {"indeks_pasif", "arus_asing"}

_LABELS = {
    "tekanan_luar": "Tekanan luar",
    "dukungan_luar": "Dukungan luar",
    "pelemahan_pasar": "Pelemahan pasar",
    "penguatan_pasar": "Penguatan pasar",
    "waspada_luar": "Waspada tekanan luar",
    "peluang_luar": "Peluang dari luar",
    "tekanan_emiten": "Tekanan emiten",
    "kekuatan_emiten": "Kekuatan emiten",
    "netral": "Netral",
    "tidak_tersedia": "Belum bisa dinilai",
}


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    return number


def _fmt_pct(value) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"{number:+.2f}%"


def _blob(item: dict) -> str:
    title = str(item.get("title") or "")
    summary = item.get("summary") if isinstance(item.get("summary"), str) else ""
    return re.sub(r"\s+", " ", f"{title}. {summary}").strip()


def _direction(text: str, theme_id: str) -> str:
    """Arah dampak ke bursa domestik, bukan sekadar kata naik/turun mentah."""
    low = text.lower()
    if theme_id == "suku_bunga":
        hike = any(word in low for word in (
            "naik", "kenaikan", "menaikkan", "dinaikkan", "hiked", "higher",
        ))
        cut = any(word in low for word in (
            "turun", "pemangkasan", "dipangkas", "pangkas", "menurunkan", "cut",
        ))
        if hike and not cut:
            return "turun"
        if cut and not hike:
            return "naik"
    if theme_id == "kurs":
        if "dolar menguat" in low or "usd menguat" in low or "rupiah melemah" in low:
            return "turun"
        if "dolar melemah" in low or "usd melemah" in low or "rupiah menguat" in low:
            return "naik"
    negative = sum(1 for word in (
        "jual", "keluar", "tekanan", "tertekan", "anjlok", "merosot", "melemah",
        "turun", "outflow", "sell-off", "selloff", "net sell", "dihapus",
        "dikeluarkan", "exclusion", "terjun", "rontok", "asing jual",
    ) if word in low)
    positive = sum(1 for word in (
        "masuk", "inflow", "menguat", "naik", "net buy", "inclusion",
        "ditambahkan", "dukungan", "asing beli", "beli",
    ) if word in low)
    if "tidak turun" in low or "tidak melemah" in low:
        negative = max(0, negative - 1)
    if negative > positive:
        return "turun"
    if positive > negative:
        return "naik"
    return "netral"


def _themes_for(item: dict, macro: bool) -> list[tuple[str, str]]:
    """Tema hanya dari judul. Ringkasan sering menyisipkan kata pasar yang tidak
    menjadi pokok berita, jadi tidak boleh menciptakan driver sendiri."""
    title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip().lower()
    if not title:
        return []
    found: list[tuple[str, str]] = []
    for theme_id, label, needles in _THEMES:
        use = needles if macro else _TICKER_NEEDLES.get(theme_id, ())
        if use and any(needle in title for needle in use):
            found.append((theme_id, label))
    return found


def _news_drivers(items: list[dict], macro: bool) -> list[dict]:
    buckets: dict[str, dict] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = _blob(item)
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        if not text or not title:
            continue
        for theme_id, label in _themes_for(item, macro):
            bucket = buckets.setdefault(theme_id, {"label": label, "hits": []})
            bucket["hits"].append((title[:160], _direction(text, theme_id)))
    drivers: list[dict] = []
    for theme_id, _label, _needles in _THEMES:
        bucket = buckets.get(theme_id)
        if not bucket:
            continue
        dirs = [direction for _title, direction in bucket["hits"]]
        down = dirs.count("turun")
        up = dirs.count("naik")
        if down > up:
            direction = "turun"
        elif up > down:
            direction = "naik"
        else:
            direction = "netral"
        evidence = [title for title, hit_dir in bucket["hits"] if hit_dir == direction]
        if not evidence:
            evidence = [title for title, _hit_dir in bucket["hits"]]
        drivers.append({
            "id": theme_id,
            "label": bucket["label"],
            "direction": direction,
            "source": "berita",
            "detail": None,
            "evidence": evidence[:2],
        })
    return drivers


def _merge_drivers(news_rows: list[dict], proxy_rows: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for row in news_rows:
        current = by_id.get(row["id"])
        if current is None:
            copied = dict(row)
            copied["evidence"] = list(row.get("evidence") or [])
            by_id[row["id"]] = copied
            continue
        if current.get("direction") == "netral" and row.get("direction") in ("naik", "turun"):
            current["direction"] = row["direction"]
        for title in row.get("evidence") or []:
            if title not in current["evidence"] and len(current["evidence"]) < 2:
                current["evidence"].append(title)
    for row in proxy_rows:
        current = by_id.get(row["id"])
        if current is None:
            by_id[row["id"]] = dict(row)
            continue
        if current.get("direction") == "netral":
            current["direction"] = row["direction"]
        if row.get("detail") and not current.get("detail"):
            current["detail"] = row["detail"]
        current["source"] = "berita+harga"
    ordered = []
    for theme_id, _label, _needles in _THEMES:
        if theme_id in by_id:
            ordered.append(by_id.pop(theme_id))
    ordered.extend(by_id.values())
    return ordered


def _shock(ret_1d: float | None, ret_5d: float | None) -> str | None:
    if ret_1d is not None and ret_1d <= -IHSG_SHOCK_1D:
        return "down"
    if ret_1d is not None and ret_1d >= IHSG_SHOCK_1D:
        return "up"
    if ret_5d is not None and ret_5d <= -IHSG_SHOCK_5D:
        return "down"
    if ret_5d is not None and ret_5d >= IHSG_SHOCK_5D:
        return "up"
    return None


def _effective(driver: dict, shock: str | None) -> str:
    direction = driver.get("direction") or "netral"
    if direction in ("naik", "turun"):
        return direction
    if driver.get("id") in _FLOW_THEMES and shock == "down":
        return "turun"
    if driver.get("id") in _FLOW_THEMES and shock == "up":
        return "naik"
    return direction


def _coupling(stock_ret_1d: float | None, ihsg_ret_1d: float | None) -> str | None:
    if stock_ret_1d is None or ihsg_ret_1d is None:
        return None
    gap = stock_ret_1d - ihsg_ret_1d
    if gap >= STOCK_DIVERGE:
        return "Saham lebih tahan daripada IHSG."
    if gap <= -STOCK_DIVERGE:
        return "Saham jatuh lebih dalam daripada IHSG."
    return "Saham bergerak bersama IHSG."


def _names(drivers: list[dict], direction: str | None = None) -> str:
    picked = []
    for driver in drivers:
        if direction is not None and driver.get("_effective") != direction:
            continue
        label = driver.get("label") or driver.get("id")
        if driver.get("detail"):
            label = f"{label} — {driver['detail']}"
        picked.append(str(label))
    if not picked:
        picked = [str(driver.get("label") or driver.get("id")) for driver in drivers]
    return ", ".join(picked[:4])


def _intensity(ret_1d, ret_5d, named: int, proxies: int) -> int:
    score = 0.0
    if ret_1d is not None:
        score += min(36.0, abs(ret_1d) * 12.0)
    if ret_5d is not None:
        score += min(24.0, abs(ret_5d) * 3.0)
    score += 16.0 * min(named, 3) + 12.0 * min(proxies, 2)
    return int(min(100, round(score)))


def assess(
    *,
    macro_items: list[dict] | None = None,
    ticker_items: list[dict] | None = None,
    ihsg: dict | None = None,
    usdidr_ret_5d: float | None = None,
    usdidr_ok: bool = False,
    global_ret_5d: float | None = None,
    global_ok: bool = False,
    news_ok: bool = True,
    stock_ret_1d: float | None = None,
    rs_change: float | None = None,
) -> dict:
    """Klasifikasi tekanan luar dari judul berita dan proksi harga.

    Murni: tidak mengambil jaringan. ``for_stock`` yang mengisi masukannya.
    """
    ihsg = ihsg or {}
    ret_1d = _num(ihsg.get("ret_1d")) if "ret_1d" in ihsg else None
    ret_5d = _num(ihsg.get("ret_5d")) if "ret_5d" in ihsg else None
    regime = ihsg.get("regime") if isinstance(ihsg.get("regime"), str) else None
    usdidr_ret_5d = _num(usdidr_ret_5d)
    global_ret_5d = _num(global_ret_5d)
    stock_ret_1d = _num(stock_ret_1d)
    rs_change = _num(rs_change)

    news_rows = _news_drivers(list(macro_items or []), True)
    news_rows.extend(_news_drivers(list(ticker_items or []), False))
    # Emiten bisa mengulang tema yang sudah ada di berita makro.
    news_rows = _merge_drivers(news_rows, [])

    proxy_rows: list[dict] = []
    if usdidr_ok and usdidr_ret_5d is not None and usdidr_ret_5d >= USDIDR_STRESS_5D:
        proxy_rows.append({
            "id": "kurs",
            "label": "Kurs rupiah",
            "direction": "turun",
            "source": "harga",
            "detail": f"USD/IDR {usdidr_ret_5d:+.2f}% (5 hari)",
            "evidence": [],
        })
    elif usdidr_ok and usdidr_ret_5d is not None and usdidr_ret_5d <= -USDIDR_STRESS_5D:
        proxy_rows.append({
            "id": "kurs",
            "label": "Kurs rupiah",
            "direction": "naik",
            "source": "harga",
            "detail": f"USD/IDR {usdidr_ret_5d:+.2f}% (5 hari)",
            "evidence": [],
        })
    if global_ok and global_ret_5d is not None and global_ret_5d <= -GLOBAL_SHOCK_5D:
        proxy_rows.append({
            "id": "global",
            "label": "Pasar global",
            "direction": "turun",
            "source": "harga",
            "detail": f"S&P 500 {global_ret_5d:+.2f}% (5 hari)",
            "evidence": [],
        })
    elif global_ok and global_ret_5d is not None and global_ret_5d >= GLOBAL_SHOCK_5D:
        proxy_rows.append({
            "id": "global",
            "label": "Pasar global",
            "direction": "naik",
            "source": "harga",
            "detail": f"S&P 500 {global_ret_5d:+.2f}% (5 hari)",
            "evidence": [],
        })

    drivers = _merge_drivers(news_rows, proxy_rows)
    shock = _shock(ret_1d, ret_5d)
    for driver in drivers:
        driver["_effective"] = _effective(driver, shock)
        # Judul hanya menyebut MSCI/rebalancing tanpa kata jual/beli. Status
        # tetap mengikatnya ke gejolak IHSG, dan detail menjelaskan inferensi itu.
        if (
            driver["_effective"] != driver.get("direction")
            and not driver.get("detail")
        ):
            driver["detail"] = "arah judul tidak eksplisit; mengikuti gejolak IHSG"

    down_named = [d for d in drivers if d["_effective"] == "turun" and d.get("source") != "harga"]
    up_named = [d for d in drivers if d["_effective"] == "naik" and d.get("source") != "harga"]
    down_proxy = [d for d in drivers if d["_effective"] == "turun" and d.get("source") == "harga"]
    up_proxy = [d for d in drivers if d["_effective"] == "naik" and d.get("source") == "harga"]
    # source berita+harga ikut terhitung sebagai bernama (ada judul).
    down_cause = [d for d in drivers if d["_effective"] == "turun"]
    up_cause = [d for d in drivers if d["_effective"] == "naik"]

    observed = ret_1d is not None or bool(drivers) or news_ok or usdidr_ok or global_ok
    if not observed:
        status = "tidak_tersedia"
    elif shock == "down" and down_cause:
        status = "tekanan_luar"
    elif shock == "down":
        status = "pelemahan_pasar"
    elif shock == "up" and up_cause:
        status = "dukungan_luar"
    elif shock == "up":
        status = "penguatan_pasar"
    elif down_cause:
        status = "waspada_luar"
    elif up_cause:
        status = "peluang_luar"
    elif (
        stock_ret_1d is not None
        and stock_ret_1d <= -STOCK_IDIO_1D
        and (ret_1d is None or stock_ret_1d <= ret_1d - STOCK_DIVERGE)
    ):
        status = "tekanan_emiten"
    elif (
        stock_ret_1d is not None
        and stock_ret_1d >= STOCK_IDIO_1D
        and (ret_1d is None or stock_ret_1d >= ret_1d + STOCK_DIVERGE)
    ):
        status = "kekuatan_emiten"
    else:
        status = "netral"

    coupling = None
    if status in (
        "tekanan_luar", "dukungan_luar", "pelemahan_pasar", "penguatan_pasar",
        "waspada_luar", "peluang_luar",
    ):
        coupling = _coupling(stock_ret_1d, ret_1d)

    ihsg_bit = f"IHSG {_fmt_pct(ret_1d)} (1 hari), {_fmt_pct(ret_5d)} (5 hari)"
    if status == "tidak_tersedia":
        summary = ("Sumber harga pasar dan berita makro tidak tersedia, "
                   "jadi tekanan luar belum bisa dinilai.")
    elif status == "tekanan_luar":
        summary = (f"{ihsg_bit} bersama tekanan luar: {_names(down_cause, 'turun')}. "
                   "Ini di luar teknikal dan fundamental emiten.")
    elif status == "dukungan_luar":
        summary = (f"{ihsg_bit} bersama dukungan luar: {_names(up_cause, 'naik')}. "
                   "Ini di luar teknikal dan fundamental emiten.")
    elif status == "pelemahan_pasar":
        summary = (f"{ihsg_bit}, pelemahan luas. Penyebab spesifik (MSCI, arus asing, "
                   "kurs, suku bunga, atau bursa global) belum terbaca dari berita maupun proksi harga.")
    elif status == "penguatan_pasar":
        summary = (f"{ihsg_bit}, penguatan luas. Penyebab spesifik dari luar "
                   "belum terbaca dari berita maupun proksi harga.")
    elif status == "waspada_luar":
        summary = (f"IHSG belum bergerak tajam ({_fmt_pct(ret_1d)} 1 hari), tetapi ada "
                   f"tekanan luar yang terpantau: {_names(down_cause, 'turun')}.")
    elif status == "peluang_luar":
        summary = (f"IHSG belum bergerak tajam ({_fmt_pct(ret_1d)} 1 hari), tetapi ada "
                   f"dukungan luar yang terpantau: {_names(up_cause, 'naik')}.")
    elif status == "tekanan_emiten":
        summary = (f"Pelemahan harga lebih khas emiten ({_fmt_pct(stock_ret_1d)} 1 hari) "
                   f"dibanding IHSG ({_fmt_pct(ret_1d)}). Bukan tekanan pasar yang teridentifikasi.")
    elif status == "kekuatan_emiten":
        summary = (f"Kekuatan harga lebih khas emiten ({_fmt_pct(stock_ret_1d)} 1 hari) "
                   f"dibanding IHSG ({_fmt_pct(ret_1d)}). Bukan semata dorongan pasar.")
    else:
        regime_bit = f", regime {regime}" if regime else ""
        summary = f"Tidak ada tekanan luar yang teridentifikasi. {ihsg_bit}{regime_bit}."

    # "MSCI" hanya boleh muncul di ringkasan pelemahan sebagai contoh hal yang
    # TIDAK ditemukan, atau bila driver benar-benar indeks pasif.
    named_n = len(down_named) if status in ("tekanan_luar", "waspada_luar") else (
        len(up_named) if status in ("dukungan_luar", "peluang_luar") else 0)
    proxy_n = len(down_proxy) if status in ("tekanan_luar", "waspada_luar") else (
        len(up_proxy) if status in ("dukungan_luar", "peluang_luar") else 0)
    if status in ("pelemahan_pasar", "penguatan_pasar", "tekanan_emiten", "kekuatan_emiten"):
        intensity = _intensity(ret_1d, ret_5d, 0, 0)
    elif status in ("netral", "tidak_tersedia"):
        intensity = 0
    else:
        intensity = _intensity(ret_1d, ret_5d, named_n, proxy_n)

    watched = []
    missing = []
    if ret_1d is not None:
        watched.append("IHSG")
    else:
        missing.append("IHSG")
    if usdidr_ok:
        watched.append("USD/IDR")
    else:
        missing.append("USD/IDR")
    if global_ok:
        watched.append("S&P 500")
    else:
        missing.append("S&P 500")
    if news_ok:
        watched.append("berita makro")
    else:
        missing.append("berita makro")

    public_drivers = []
    for driver in drivers:
        public_drivers.append({
            "id": driver["id"],
            "label": driver["label"],
            "direction": driver["direction"],
            "source": driver["source"],
            "detail": driver.get("detail"),
            "evidence": list(driver.get("evidence") or []),
        })

    return {
        "status": status,
        "label": _LABELS[status],
        "intensity": intensity,
        "summary": summary,
        "coupling": coupling,
        "drivers": public_drivers,
        "proxies": {
            "ihsg_1d": None if ret_1d is None else round(ret_1d, 2),
            "ihsg_5d": None if ret_5d is None else round(ret_5d, 2),
            "ihsg_regime": regime,
            "usdidr_5d": None if usdidr_ret_5d is None else round(usdidr_ret_5d, 2),
            "global_5d": None if global_ret_5d is None else round(global_ret_5d, 2),
            "stock_1d": None if stock_ret_1d is None else round(stock_ret_1d, 2),
            "rs_20d": None if rs_change is None else round(rs_change, 2),
        },
        "watched": watched,
        "missing": missing,
    }


def _proxy(symbol: str) -> dict:
    try:
        frame = data.get_ohlcv(symbol, suffix="", period="6mo")
        close = frame["Close"].astype(float)
    except Exception:
        return {"ret_1d": None, "ret_5d": None, "ok": False}

    def _ret(n: int) -> float | None:
        if len(close) <= n:
            return None
        return float(close.iloc[-1] / close.iloc[-1 - n] - 1.0) * 100.0

    return {"ret_1d": _ret(1), "ret_5d": _ret(5), "ok": True}


def _macro_headlines() -> tuple[list[dict], bool]:
    found: list[dict] = []
    any_ok = False

    def _one(query: str) -> tuple[list[dict], bool]:
        try:
            return news.headlines_for_query(query, limit=8)
        except Exception:
            return [], False

    with ThreadPoolExecutor(max_workers=len(MACRO_QUERIES)) as pool:
        for items, ok in pool.map(_one, MACRO_QUERIES):
            if ok:
                any_ok = True
            found.extend(items)
    seen: set[str] = set()
    unique: list[dict] = []
    for item in found:
        key = re.sub(r"\W+", "", str(item.get("title") or "").lower())[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique, any_ok


def _build_bundle() -> dict:
    try:
        headlines, news_ok = _macro_headlines()
    except Exception:
        headlines, news_ok = [], False
    try:
        ihsg = market.ihsg()
    except Exception as exc:
        ihsg = {"error": type(exc).__name__}
    return {
        "headlines": headlines,
        "news_ok": news_ok,
        "ihsg": ihsg if isinstance(ihsg, dict) else {},
        "usdidr": _proxy("USDIDR=X"),
        "global": _proxy("^GSPC"),
    }


def _bundle() -> dict:
    now = time.time()
    cached = _bundle_cache.get("data")
    if cached is not None and now - float(_bundle_cache.get("ts") or 0.0) < _BUNDLE_TTL:
        return cached
    with _bundle_lock:
        cached = _bundle_cache.get("data")
        if cached is not None and time.time() - float(_bundle_cache.get("ts") or 0.0) < _BUNDLE_TTL:
            return cached
        built = _build_bundle()
        _bundle_cache["ts"] = time.time()
        _bundle_cache["data"] = built
        return built


def for_stock(
    ticker: str = "",
    change_1d: float | None = None,
    rs_change: float | None = None,
    extra_items: list[dict] | None = None,
) -> dict:
    """Tekanan luar untuk satu saham. Tidak melempar; gagal jadi status jujur.

    ``extra_items`` (berita emiten yang sudah diambil) menghindari unduhan ganda.
    ``None`` artinya ambil berita emiten di sini bila ticker ada.
    """
    try:
        bundle = _bundle()
        if extra_items is None and ticker:
            try:
                extra_items = (news.get_news(ticker).get("items") or [])
            except Exception:
                extra_items = []
        usdidr = bundle.get("usdidr") or {}
        glob = bundle.get("global") or {}
        return assess(
            macro_items=bundle.get("headlines") or [],
            ticker_items=extra_items or [],
            ihsg=bundle.get("ihsg") or {},
            usdidr_ret_5d=usdidr.get("ret_5d"),
            usdidr_ok=bool(usdidr.get("ok")),
            global_ret_5d=glob.get("ret_5d"),
            global_ok=bool(glob.get("ok")),
            news_ok=bool(bundle.get("news_ok")),
            stock_ret_1d=change_1d,
            rs_change=rs_change,
        )
    except Exception:
        return assess(news_ok=False, usdidr_ok=False, global_ok=False)


def for_market() -> dict:
    """Tekanan luar tingkat pasar, tanpa membandingkan satu emiten."""
    return for_stock("", extra_items=[])
