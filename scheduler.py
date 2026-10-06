from __future__ import annotations

import argparse
import time
import traceback

import data
import notify
import screener
import store
from signals import analyze


def run_once(universe: str = "lq45", min_score: int = 65) -> int:
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
        except Exception as exc:
            print(f"  ! {t}: {exc}")
    store.add_scan(universe, n, len(buys))
    for a in buys:
        text = (f"[{a.signal}] {a.ticker} | skor {a.score} conf {a.confidence}% "
                f"| harga {a.price:,.0f} | SL {a.stop_loss:,.0f} TP1 {a.tp1:,.0f}")
        notify.dispatch(text, {"ticker": a.ticker, "signal": a.signal, "score": a.score})
        print(f"ALERT {text}")
    return len(buys)


def warm(universe: str = "auto") -> int:
    """Hangatkan cache (unduh data) tanpa analisis — agar scan manual berikutnya cepat."""
    try:
        tickers = screener.resolve_watchlist(universe)
        return data.prefetch(tickers)
    except Exception as exc:
        print(f"  ! warm {universe}: {exc}")
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
