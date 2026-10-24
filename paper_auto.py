"""Paper trading otomatis dari sinyal engine (batch-34).

MURNI PENCATATAN hasil mengikuti sinyal engine apa adanya - tidak
mengubah skor, bobot, ambang, atau keputusan sinyal sedikit pun.

- settle_open_positions(): tutup posisi OPEN yang TP/SL tersentuh pada
  bar SETELAH hari sinyal (kausal; TP dan SL kena di bar yang sama
  dihitung SL dulu - konservatif, konsisten outcomes.evaluate_window).
- open_from_signals(): buka posisi paper dari sinyal actionable TERBARU
  per ticker (STRONG BUY/BUY/ACCUMULATE -> long, SELL -> short paper),
  hanya bila belum ada posisi terbuka ticker itu DAN sinyal lebih baru
  dari posisi terakhirnya (anti daur ulang sinyal basi).
- sync_paper(): settle dulu, lalu buka. Dipanggil pasca-scan
  (scheduler.run_once, best-effort) dan manual via POST /api/paper/sync.

Dedup: satu posisi terbuka maksimal per ticker - scan berjalan tiap
beberapa menit; tanpa dedup posisi akan menumpuk dari sinyal yang sama.
"""
from __future__ import annotations

import data
import store

LONG_SIGNALS = ("STRONG BUY", "BUY", "ACCUMULATE")
SHORT_SIGNALS = ("SELL",)
TARGET_VALUE = 10_000_000.0  # nilai posisi paper per saham: Rp 10 juta


def _side_of(signal: str | None) -> str | None:
    """Arah posisi dari sinyal; None bila sinyal tidak actionable (AVOID/HOLD)."""
    s = (signal or "").strip().upper()
    if s in SHORT_SIGNALS:
        return "SELL"
    if s in LONG_SIGNALS:
        return "BUY"
    return None


def _lots_for(price: float, target_value: float = TARGET_VALUE) -> int:
    """Lot paper (1 lot = 100 lembar) menukar nilai target; minimal 1 lot."""
    if not price or price <= 0:
        return 0
    return max(1, int(target_value / (price * 100.0)))


def _first_exit(row: dict, df):
    """(harga, alasan) keluar pertama posisi OPEN; None bila TP/SL belum kena.

    Kausal: hanya bar SETELAH hari sinyal (bar hari sinyal tidak ikut -
    sinyal bisa dibuat intraday). Konservatif: TP dan SL kena di bar yang
    sama dihitung SL dulu, konsisten outcomes.evaluate_window.
    """
    if df is None or len(df) == 0:
        return None
    side = str(row.get("side") or "BUY").strip().upper()
    try:
        stop = float(row.get("stop") or 0.0)
        tp = float(row.get("tp") or 0.0)
    except (TypeError, ValueError):
        return None
    if stop <= 0 and tp <= 0:
        return None
    opened_day = str(row.get("opened") or "")[:10]
    try:
        hi = df["High"]
        lo = df["Low"]
        for i, d in enumerate(df.index):
            day = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
            if day <= opened_day:
                continue
            if side == "SELL":
                if stop > 0 and float(hi.iloc[i]) >= stop:
                    return stop, "auto: SL"
                if tp > 0 and float(lo.iloc[i]) <= tp:
                    return tp, "auto: TP"
            else:
                if stop > 0 and float(lo.iloc[i]) <= stop:
                    return stop, "auto: SL"
                if tp > 0 and float(hi.iloc[i]) >= tp:
                    return tp, "auto: TP"
    except Exception:
        return None
    return None


def settle_open_positions(max_rows: int = 200) -> int:
    """Tutup posisi OPEN yang TP/SL tersentuh; return jumlah yang ditutup."""
    closed = 0
    for r in store.paper_rows(status="OPEN")[:max_rows]:
        exit_hit = None
        try:
            exit_hit = _first_exit(r, data.get_ohlcv(r.get("ticker")))
        except Exception:
            continue
        if exit_hit is None:
            continue
        price, reason = exit_hit
        side = str(r.get("side") or "BUY").strip().upper()
        sign = -1.0 if side == "SELL" else 1.0
        try:
            pnl = round((price - float(r["entry"])) * int(r["lots"]) * 100 * sign, 0)
        except (KeyError, TypeError, ValueError):
            continue
        store.paper_close(int(r["id"]), price, pnl, reason)
        closed += 1
    return closed


def open_from_signals(limit: int = 400, target_value: float = TARGET_VALUE) -> int:
    """Buka posisi paper dari sinyal actionable TERBARU per ticker.

    Jaga ganda: (1) satu posisi terbuka per ticker; (2) sinyal harus lebih
    BARU dari posisi terakhir ticker itu - posisi yang baru ditutup tidak
    dibuka ulang dari sinyal basi (anti daur ulang).
    """
    latest: dict = {}
    for s in store.recent_signals(limit=limit):
        tk = str(s.get("ticker") or "").upper()
        if tk and tk not in latest:
            latest[tk] = s  # recent_signals urut terbaru dulu
    open_tickers: set = set()
    last_opened: dict = {}
    for r in store.paper_rows():
        tk = str(r.get("ticker") or "").upper()
        if not tk:
            continue
        if r.get("status") == "OPEN":
            open_tickers.add(tk)
        ts = str(r.get("opened") or "")
        if ts > last_opened.get(tk, ""):
            last_opened[tk] = ts
    opened = 0
    for tk, s in latest.items():
        if tk in open_tickers:
            continue
        if str(s.get("ts") or "") <= last_opened.get(tk, ""):
            continue  # sinyal basi: posisi untuk sinyal ini sudah pernah dibuka
        side = _side_of(s.get("signal"))
        if side is None:
            continue
        try:
            price = float(s.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        try:
            stop = float(s.get("stop_loss") or 0.0)
            tp = float(s.get("tp1") or 0.0)
        except (TypeError, ValueError):
            stop, tp = 0.0, 0.0
        lots = _lots_for(price, target_value)
        if lots <= 0:
            continue
        store.paper_open(
            tk, side, price, lots, stop, tp,
            "auto: sinyal " + str(s.get("signal") or "") + " (" + str(s.get("ts") or "") + ")",
            opened=str(s.get("ts") or "") or None,
        )
        open_tickers.add(tk)
        opened += 1
    return opened


def sync_paper(limit: int = 400, target_value: float = TARGET_VALUE, max_rounds: int = 5) -> dict:
    """Sinkron paper trading SAMPAI MUTAKHIR: loop settle -> open hingga stabil.

    Satu putaran settle-then-open bisa meninggalkan pekerjaan: posisi yang
    baru dibuka dari sinyal LAMA bisa langsung layak ditutup (TP/SL sudah
    tersentuh pada bar antara hari sinyal dan sekarang). Loop berhenti saat
    satu putaran tidak mengubah apa pun (stabil / mutakhir), dibatasi
    max_rounds agar tidak bisa berputar selamanya.
    """
    settled = 0
    opened = 0
    rounds = 0
    for _ in range(max(1, int(max_rounds))):
        rounds += 1
        s = settle_open_positions()
        o = open_from_signals(limit=limit, target_value=target_value)
        settled += s
        opened += o
        if s == 0 and o == 0:
            break
    return {"settled": settled, "opened": opened, "rounds": rounds}
