"""Loop umpan balik akurasi sinyal (feedback loop).

Evaluasi sinyal yang sudah tercatat di DB (`signals`): forward return nyata
N hari perdagangan setelah sinyal, sentuh TP1/SL mana yang lebih dulu, dan
excess return vs IHSG pada jendela yang sama.

Murni pengukuran atas apa yang SUDAH terjadi:
- Kausal: hanya bar SETELAH hari sinyal yang dipakai; harga patokan adalah
  harga yang tercatat saat sinyal dibuat (bukan harga beli sempurna).
- Tanpa proyeksi: sinyal yang belum punya cukup bar tetap "pending" dan
  dicoba lagi belakangan; tidak pernah dihitung spekulatif.
- Tidak mengubah skor 0-100, bobot, ambang, atau sinyal sama sekali —
  angka ini justru bukti empiris untuk MEMUTUSKAN perubahan tersebut nanti
  (indikator mana yang layak masuk skoring, ambang berapa).

CLI:
    python outcomes.py --horizons 5,10 --lookback 90
"""
from __future__ import annotations

import argparse
import logging
import time

import store

_log = logging.getLogger("laumology.outcomes")

DEFAULT_HORIZON = 5
DEFAULT_LOOKBACK_DAYS = 90


def _day_keys(df) -> list[str]:
    """Kunci tanggal YYYY-MM-DD dari index DataFrame (tanggal saja, urut apa adanya)."""
    keys: list[str] = []
    for d in df.index:
        try:
            keys.append(d.strftime("%Y-%m-%d"))
        except AttributeError:
            keys.append(str(d)[:10])
    return keys


def _parse_date(ts: object) -> str | None:
    """Tanggal (YYYY-MM-DD) dari ts sinyal; None bila format tak dikenal."""
    raw = str(ts or "").strip()
    if len(raw) < 10:
        return None
    day = raw[:10]
    try:
        time.strptime(day, "%Y-%m-%d")
    except ValueError:
        return None
    return day


def evaluate_window(signal_price: float, window, tp1: float | None, sl: float | None,
                    horizon: int | None = None) -> dict:
    """Hasil sinyal dari `window`: bar SETELAH hari sinyal (sudah dipotong).

    - fwd_return_pct: return dari harga sinyal ke close bar terakhir jendela.
    - Konservatif: bila TP1 dan SL tersentuh di bar yang sama, dihitung SL dulu.
    - Bila `horizon` diisi dan jendela kurang dari itu, status "pending" (jujur,
      sinyal muda tidak dihitung spekulatif).
    """
    n = len(window)
    if n == 0 or not signal_price:
        return {"status": "pending", "n_bars": n}
    if horizon is not None and n < int(horizon):
        return {"status": "pending", "n_bars": n}
    close = float(window["Close"].iloc[-1])
    fwd = (close / signal_price - 1.0) * 100.0

    tp1_hit = sl_hit = False
    first_tp1 = first_sl = None
    if tp1:
        hits = (window["High"] >= float(tp1)).to_numpy()
        if hits.any():
            tp1_hit = True
            first_tp1 = int(hits.nonzero()[0][0])
    if sl:
        hits = (window["Low"] <= float(sl)).to_numpy()
        if hits.any():
            sl_hit = True
            first_sl = int(hits.nonzero()[0][0])

    if tp1_hit and sl_hit:
        outcome = "TP1" if first_tp1 < first_sl else "SL"  # bar sama -> SL (konservatif)
    elif tp1_hit:
        outcome = "TP1"
    elif sl_hit:
        outcome = "SL"
    else:
        outcome = "NONE"

    return {
        "status": "done",
        "n_bars": n,
        "fwd_return_pct": round(fwd, 4),
        "tp1_hit": tp1_hit,
        "sl_hit": sl_hit,
        "outcome": outcome,
    }


def _window_after(df, signal_date: str, horizon: int):
    """Bar `horizon` perdagangan pertama SETELAH hari sinyal (kausal).

    Bar hari sinyal TIDAK ikut: sinyal bisa dibuat intraday, close hari itu
    belum diketahui saat sinyal dibuat.
    """
    keys = _day_keys(df)
    start = None
    for i, day in enumerate(keys):
        if day > signal_date:
            start = i
            break
    if start is None:
        return None
    return df.iloc[start: start + horizon]


def _bench_fwd(bench_df, signal_date: str, horizon: int) -> float | None:
    """Forward return IHSG untuk jendela yang sama; None bila tak bisa dihitung."""
    if bench_df is None or len(bench_df) == 0:
        return None
    keys = _day_keys(bench_df)
    start = None
    for i, day in enumerate(keys):
        if day > signal_date:
            start = i
            break
    if start is None or start < 1 or len(bench_df) < start + horizon:
        return None
    base = float(bench_df["Close"].iloc[start - 1])
    end = float(bench_df["Close"].iloc[start + horizon - 1])
    if not base:
        return None
    return (end / base - 1.0) * 100.0


def evaluate_signals(
    horizon: int = DEFAULT_HORIZON,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    limit: int = 500,
    fetch_ohlcv=None,
    bench_df=None,
) -> dict:
    """Evaluasi semua sinyal layak yang belum punya hasil untuk `horizon`.

    `fetch_ohlcv` / `bench_df` bisa disuntik untuk pengujian; default memakai
    `data.get_ohlcv` dan benchmark dari `config.settings`.
    """
    if fetch_ohlcv is None:
        import data

        fetch_ohlcv = data.get_ohlcv
    if bench_df is None:
        try:
            from config import settings

            bench_df = fetch_ohlcv(
                settings.benchmark, suffix=settings.benchmark_suffix, period=settings.period
            )
        except Exception:
            bench_df = None
            _log.warning("Benchmark IHSG tidak tersedia; excess return dilewati.", exc_info=True)

    pending = store.pending_signals(horizon, lookback_days, limit)
    done = skipped = failed = 0
    for s in pending:
        day = _parse_date(s.get("ts"))
        ticker = str(s.get("ticker") or "").upper()
        price = s.get("price")
        if not day or not ticker or price is None:
            skipped += 1
            continue
        try:
            df = fetch_ohlcv(ticker)
        except Exception:
            failed += 1
            continue
        if df is None or len(df) == 0:
            skipped += 1
            continue
        window = _window_after(df, day, horizon)
        if window is None or len(window) < horizon:
            skipped += 1  # belum cukup bar setelah sinyal -> tetap pending
            continue
        res = evaluate_window(float(price), window, s.get("tp1"), s.get("stop_loss"), horizon)
        if res.get("status") != "done":
            skipped += 1
            continue
        bench = _bench_fwd(bench_df, day, horizon)
        excess = round(res["fwd_return_pct"] - bench, 4) if bench is not None else None
        store.outcome_upsert(
            s["id"], horizon, res["n_bars"], res["fwd_return_pct"], bench, excess,
            res["tp1_hit"], res["sl_hit"], res["outcome"],
        )
        done += 1

    return {
        "horizon": horizon,
        "eligible": len(pending),
        "evaluated": done,
        "still_pending": skipped,
        "failed": failed,
    }


def print_attribution(horizon: int) -> None:
    """Cetak win rate per kelompok (atribusi) — bukti empiris untuk keputusan ambang."""
    rep = store.outcomes_by_bucket(horizon)
    if not rep["buckets"] or not any(rep["buckets"].values()):
        print("  Atribusi: belum ada kelompok dengan sampel cukup (jujur, tanpa proyeksi).")
        return
    print(f"  Atribusi win rate per kelompok (n>={rep['min_n']}):")
    for dim, entries in rep["buckets"].items():
        if not entries:
            continue
        print(f"    {dim}:")
        for e in entries:
            exc = "n/a" if e["avg_excess_pct"] is None else f"{e['avg_excess_pct']:+.2f}%"
            print(f"      {e['bucket']:>8s}  n={e['n']:<4d}  win={e['win_rate']:5.1f}%  "
                  f"avg={e['avg_fwd_pct']:+.2f}%  excess={exc}  "
                  f"TP1={e['tp1_rate']:.0f}%  SL={e['sl_rate']:.0f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description="LAUMOLOGY evaluasi hasil sinyal (feedback loop)")
    ap.add_argument("--horizons", default="5",
                    help="daftar horizon hari perdagangan, dipisah koma (mis. 5,10)")
    ap.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS,
                    help="batas usia sinyal dalam hari kalender (default 90)")
    ap.add_argument("--limit", type=int, default=500, help="maksimum sinyal per eksekusi")
    ap.add_argument("--attribution", action="store_true",
                    help="cetak win rate per kelompok (skor/confidence/grade/sinyal) — bukti untuk keputusan ambang")
    args = ap.parse_args()

    try:
        horizons = sorted({int(h) for h in str(args.horizons).replace(" ", "").split(",") if h})
    except ValueError:
        raise SystemExit("--horizons harus daftar angka dipisah koma, mis. 5,10")
    if not horizons:
        raise SystemExit("--horizons kosong; isi minimal satu horizon, mis. 5")

    store.init()
    for horizon in horizons:
        r = evaluate_signals(horizon, args.lookback, args.limit)
        print(
            f"H+{r['horizon']}: dievaluasi {r['evaluated']}/{r['eligible']} "
            f"(pending {r['still_pending']}, gagal fetch {r['failed']})"
        )
        s = store.outcomes_summary(horizon)
        if s.get("n"):
            print(
                f"  Benar (return +): {s['win_rate']:.1f}%  |  "
                f"rata-rata {s['avg_fwd_pct']:+.2f}%  |  excess vs IHSG {s['avg_excess_pct']:+.2f}%"
            )
            print(
                f"  TP1 sebelum SL: {s['tp1_first_rate']:.1f}%  |  SL dulu: {s['sl_first_rate']:.1f}%"
                f"  |  netral: {s['none_rate']:.1f}%"
            )
        else:
            print("  Belum ada sinyal yang cukup tua untuk dievaluasi (jujur, tanpa proyeksi).")
        if args.attribution:
            print_attribution(horizon)


if __name__ == "__main__":
    main()
