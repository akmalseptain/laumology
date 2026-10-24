from __future__ import annotations

import argparse
import time
import traceback

import logging

import data
import notify
import screener
import store
from signals import analyze

_log = logging.getLogger("laumology.scheduler")

EVAL_HORIZONS = (1, 5, 10)
"""Horizon evaluasi feedback loop (hari bursa SETELAH hari sinyal).

H+1 = puls cepat arah 1 hari (bukan patokan; TP/SL dalam 1 bar praktis
selalu TIMEOUT - konsisten temuan validasi). H+5 tetap patokan resmi."""


def run_once(universe: str = "lq45") -> int:
    tickers = screener.resolve_watchlist(universe)
    data.prefetch(tickers)  # batch: percepat + hangatkan cache
    prev = {r["ticker"]: r["signal"] for r in store.recent_signals(limit=800)}
    buys = []
    n = 0
    for t in tickers:
        try:
            df = data.get_ohlcv(t)
            if len(df) < 80:
                continue
            a = analyze(df, t)
            n += 1
            store.add_signal(
                {
                    "ticker": a.ticker, "signal": a.signal, "action": a.action,
                    "score": a.score, "confidence": a.confidence, "grade": a.grade,
                    "price": a.price, "entry": a.entry, "stop_loss": a.stop_loss, "tp1": a.tp1,
                },
                source="scan",
            )
            if a.signal in ("STRONG BUY", "BUY") and prev.get(a.ticker) != a.signal:
                buys.append(a)
        except Exception:
            # Best-effort (ticker lain tetap dipindai), tapi TIDAK senyap:
            # print tanpa traceback sulit diaudit - warning + exc_info.
            _log.warning("ticker %s gagal dipindai - dilewati", t, exc_info=True)
    store.add_scan(universe, n, len(buys))

    # Feedback loop akurasi: evaluasi sinyal lama (best-effort, jangan ganggu scan).
    try:
        import outcomes as outcomes_mod

        # Multi-horizon: ukur H+1, H+5, dan H+10 agar track record tidak
        # menyetir satu horizon saja; semuanya best-effort, jangan ganggu
        # scan. H+1 hanya puls cepat arah - patokan resmi tetap H+5.
        for horizon in EVAL_HORIZONS:
            outcomes_mod.evaluate_signals(horizon=horizon, limit=25)
    except Exception:  # noqa: BLE001
        _log.warning("evaluasi outcomes best-effort gagal", exc_info=True)

    # Paper trading otomatis (batch-34): buka/tutup posisi paper mengikuti
    # sinyal engine yang sudah tercatat. Murni pencatatan (tabel paper);
    # best-effort, jangan ganggu scan; skor/ambang/sinyal tidak disentuh.
    try:
        import paper_auto
        paper_auto.sync_paper()
    except Exception:  # noqa: BLE001
        _log.warning("sync paper best-effort gagal", exc_info=True)
    for a in buys:
        try:
            notify.signal_alert({
                "ticker": a.ticker, "signal": a.signal, "action": a.action,
                "score": a.score, "confidence": a.confidence, "grade": a.grade,
                "price": a.price, "entry": a.entry, "stop_loss": a.stop_loss, "tp1": a.tp1,
                "source": "scan",
            })
        except Exception:
            # best-effort: satu alert gagal tidak boleh memutus sisa alert,
            # tapi TIDAK senyap - warning tercatat (pola batch-41).
            _log.warning("alert %s gagal dikirim - best-effort", a.ticker, exc_info=True)
        print(f"ALERT {a.ticker} {a.signal} skor {a.score} conf {a.confidence}%")
    return len(buys)


def warm(universe: str = "auto") -> int:
    """Hangatkan cache (unduh data + hitung baris screener) agar scan manual berikutnya cepat."""
    try:
        tickers = screener.resolve_watchlist(universe)
        n = data.prefetch(tickers)
        try:
            screener.screen(tickers, top=0)  # isi cache baris persisten (tanpa ubah hasil)
        except Exception:
            # best-effort: warm baris gagal tidak boleh memutus prefetch,
            # tapi TIDAK senyap (pola batch-41/42).
            _log.warning("screen warm %s gagal - best-effort", universe, exc_info=True)
        return n
    except Exception:
        _log.warning("warm %s gagal - dilewati", universe, exc_info=True)
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="LAUMOLOGY auto-scanner")
    ap.add_argument("--list", default="lq45")
    ap.add_argument("--interval", type=int, default=900, help="detik antar pemindaian")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    store.init()
    print(f"Auto-scanner jalan: universe={args.list}, interval={args.interval}s")
    while True:
        try:
            n = run_once(args.list)
            print(f"{time.strftime('%H:%M:%S')} scan selesai, {n} sinyal beli baru")
        except Exception:
            traceback.print_exc()
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
