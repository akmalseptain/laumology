from __future__ import annotations

import argparse
import sys

import pandas as pd

import data
import screener
from backtest import backtest
from chart import plot_analysis
from config import settings
from signals import analyze


def _fmt(x: float, dec: int = 0) -> str:
    return f"{x:,.{dec}f}"


def cmd_analyze(args: argparse.Namespace) -> None:
    df = data.get_ohlcv(args.ticker, period=args.period)
    quote = data.get_quote(args.ticker)
    df, live = data.apply_live_quote(df, quote, "1d")
    a = analyze(df, args.ticker)
    if live and live.get("price"):
        a.price = live["price"]
        if live.get("prev_close"):
            a.change_1d = (live["price"] / live["prev_close"] - 1.0) * 100.0

    print("=" * 70)
    print(f"  ANALISIS {a.ticker}   ({len(df)} hari data{', LIVE' if live else ''})")
    print("=" * 70)
    print(f"  Harga          : {_fmt(a.price)}  ({a.change_1d:+.2f}%)")
    print(f"  Sinyal         : {a.signal}  ->  {a.action}")
    print(f"  Skor / Conf    : {a.score}/100   Keyakinan {a.confidence}%   Grade {a.grade}")
    print(f"  Tren / Weekly  : {a.trend}  |  {a.weekly_trend}")
    print(f"  Regime         : {a.regime}   (ADX {a.adx:.0f}, +DI {a.plus_di:.0f}, -DI {a.minus_di:.0f})")
    print(f"  RSI / ATR      : {a.rsi:.1f} / {a.atr_pct:.2f}%   (SuperTrend {'UP' if a.st_dir_up else 'DOWN'})")
    print("-" * 70)
    print(f"  BELI SEKARANG    : {_fmt(a.entry)}")
    print(f"  Zona beli        : {_fmt(a.buy_zone_low)} - {_fmt(a.buy_zone_high)}   (pullback {_fmt(a.entry_pullback)})")
    print(f"  Beli breakout    : {_fmt(a.entry_breakout)}")
    print(f"  Stop Loss        : {_fmt(a.stop_loss)}   (trail: {_fmt(a.stop_trail)})")
    print(f"  Take Profit 1    : {_fmt(a.tp1)}   (RR 1:{a.rr1:.1f})")
    print(f"  Take Profit 2    : {_fmt(a.tp2)}   (RR 1:{a.rr2:.1f})")
    print(f"  Take Profit 3    : {_fmt(a.tp3)}   (RR 1:{a.rr3:.1f})")
    print(f"  Support/Resist   : {_fmt(a.support)} / {_fmt(a.resistance)}")
    print(f"  Pivot (S1/PP/R1) : {_fmt(a.pivot['s1'])} / {_fmt(a.pivot['pp'])} / {_fmt(a.pivot['r1'])}")
    print(f"  Fibonacci 0.382-0.618: {_fmt(a.fib['0.382'])} - {_fmt(a.fib['0.618'])}")
    print("-" * 70)
    rp = f"{a.rs_change:+.1f}%" if a.rs_change is not None else "n/a"
    print(f"  Rel. Strength vs IHSG: {rp}   {'outperform' if a.rs_strong else 'underperform'}")
    print(f"  Position sizing  : {a.lots} lot  ({_fmt(a.position_value)} IDR, max loss {_fmt(a.max_loss)})")
    if a.patterns:
        print(f"  Pola candle      : {', '.join(a.patterns)}")
    if a.divergences:
        print(f"  Divergence       : {', '.join(a.divergences)}")
    print("-" * 70)
    print("  Komponen skor:")
    for k, v in a.components.items():
        print(f"    {k:<10} {v:5.1f}  {'#' * int(v)}")
    print("-" * 70)
    passed = sum(1 for _, ok in a.checklist if ok)
    print(f"  Checklist confluence: {passed}/{len(a.checklist)} terpenuhi")
    if a.reasons:
        print("  Alasan BULLISH:")
        for r in a.reasons:
            print(f"    + {r}")
    if a.warnings:
        print("  Peringatan:")
        for w in a.warnings:
            print(f"    ! {w}")
    print("=" * 70)
    print("  Catatan: ini alat bantu analisis, bukan nasihat keuangan.")
    if args.chart:
        path = plot_analysis(df, a)
        print(f"  Chart disimpan: {path}")


def cmd_screen(args: argparse.Namespace) -> None:
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = screener.resolve_watchlist(args.list)

    print(f"Memindai {len(tickers)} saham (period={args.period or 'default'})...")
    res = screener.screen(tickers, period=args.period, min_score=args.min_score, top=args.top)
    if res.empty:
        print("Tidak ada hasil.")
        return

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    print(res.to_string(index=False))

    if args.save:
        from pathlib import Path

        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        res.to_csv(args.save, index=False)
        print(f"\nDisimpan ke {args.save}")


def cmd_backtest(args: argparse.Namespace) -> None:
    df = data.get_ohlcv(args.ticker, period=args.period)
    result = backtest(
        df,
        args.ticker,
        min_score=args.min_score,
        max_hold=args.max_hold,
        tp_rr=args.tp_rr,
        sl_mult=args.sl_mult,
    )
    print("=" * 66)
    print(f"  BACKTEST {result.ticker}")
    print("=" * 66)
    print(result.summary())
    print(f"  Avg win  : {result.avg_win*100:.2f}%")
    print(f"  Avg loss : {result.avg_loss*100:.2f}%")
    print(f"  Expectancy per trade: {result.expectancy*100:.2f}%")
    if args.trades and not result.trades.empty:
        print("-" * 66)
        print(result.trades.to_string(index=False))
    print("=" * 66)


def cmd_chart(args: argparse.Namespace) -> None:
    df = data.get_ohlcv(args.ticker, period=args.period)
    a = analyze(df, args.ticker)
    path = plot_analysis(df, a, bars=args.bars)
    print(f"Chart disimpan: {path}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="idx",
        description="Toolkit analisis & trading saham Indonesia (IDX).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("analyze", help="Analisis detail satu saham + sinyal entry/TP/SL")
    pa.add_argument("ticker")
    pa.add_argument("--period", default=None)
    pa.add_argument("--chart", action="store_true", help="Simpan chart PNG")
    pa.set_defaults(func=cmd_analyze)

    ps = sub.add_parser("screen", help="Pindai banyak saham, ranking skor terbaik")
    ps.add_argument("--list", default="lq45", help="lq45 | idx30 | atau daftar koma")
    ps.add_argument("--tickers", default=None, help="Daftar koma, mis. BBCA,BBRI,TLKM")
    ps.add_argument("--period", default=None)
    ps.add_argument("--top", type=int, default=20)
    ps.add_argument("--min-score", type=int, default=0)
    ps.add_argument("--save", default=None, help="Simpan hasil ke CSV")
    ps.set_defaults(func=cmd_screen)

    pb = sub.add_parser("backtest", help="Uji strategi pada data historis")
    pb.add_argument("ticker")
    pb.add_argument("--period", default=None)
    pb.add_argument("--min-score", type=int, default=None)
    pb.add_argument("--max-hold", type=int, default=20)
    pb.add_argument("--tp-rr", type=float, default=None)
    pb.add_argument("--sl-mult", type=float, default=None)
    pb.add_argument("--trades", action="store_true", help="Tampilkan rincian trade")
    pb.set_defaults(func=cmd_backtest)

    pc = sub.add_parser("chart", help="Simpan chart candlestick + sinyal")
    pc.add_argument("ticker")
    pc.add_argument("--period", default=None)
    pc.add_argument("--bars", type=int, default=120)
    pc.set_defaults(func=cmd_chart)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nDibatalkan.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
