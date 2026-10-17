from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

_data_dir = os.environ.get("DATA_DIR")
if _data_dir:
    DB_PATH = Path(_data_dir) / "laumology.db"
elif os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
    DB_PATH = Path("/tmp/laumology.db")
else:
    DB_PATH = Path(".cache") / "laumology.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS signals(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT, ticker TEXT, signal TEXT, action TEXT, score INTEGER,
              confidence INTEGER, grade TEXT, price REAL, entry REAL,
              stop_loss REAL, tp1 REAL, source TEXT
            );
            CREATE TABLE IF NOT EXISTS scans(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT, universe TEXT, n INTEGER, buys INTEGER, note TEXT
            );
            CREATE TABLE IF NOT EXISTS paper(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ticker TEXT, side TEXT, entry REAL, lots INTEGER, stop REAL, tp REAL,
              opened TEXT, closed TEXT, exit REAL, pnl REAL, status TEXT, note TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
            CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);
            CREATE TABLE IF NOT EXISTS signal_outcomes(
              signal_id INTEGER NOT NULL,
              horizon INTEGER NOT NULL,
              evaluated_at TEXT NOT NULL,
              n_bars INTEGER,
              fwd_return_pct REAL,
              bench_fwd_pct REAL,
              excess_pct REAL,
              tp1_hit INTEGER,
              sl_hit INTEGER,
              outcome TEXT,
              PRIMARY KEY(signal_id, horizon)
            );
            CREATE INDEX IF NOT EXISTS idx_outcomes_signal ON signal_outcomes(signal_id);
            CREATE TABLE IF NOT EXISTS fund_snap(
              day TEXT NOT NULL,
              ticker TEXT NOT NULL,
              pe REAL, pb REAL, roe REAL, der REAL, eps REAL, price REAL,
              PRIMARY KEY(day, ticker)
            );
            """
        )


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def save_fund_snap(ticker: str, fields: dict) -> dict:
    """Simpan satu cuplikan fundamental per emiten per hari. Tidak menimpa hari lain."""
    init()
    day = time.strftime("%Y-%m-%d")
    code = (ticker or "").upper().strip()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO fund_snap(day,ticker,pe,pb,roe,der,eps,price) VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(day,ticker) DO UPDATE SET pe=excluded.pe, pb=excluded.pb,"
            " roe=excluded.roe, der=excluded.der, eps=excluded.eps, price=excluded.price",
            (
                day, code,
                fields.get("pe"), fields.get("pb"), fields.get("roe"),
                fields.get("der"), fields.get("eps"), fields.get("price"),
            ),
        )
        row = c.execute(
            "SELECT COUNT(*) AS n, MIN(day) AS first, MAX(day) AS last FROM fund_snap WHERE ticker=?",
            (code,),
        ).fetchone()
    return {"days": int(row["n"] or 0), "first": row["first"], "last": row["last"]}


def fund_snap_history(ticker: str, limit: int = 30) -> list[dict]:
    """Cuplikan terbaru dulu. Kosong bila emiten belum pernah disimpan."""
    init()
    code = (ticker or "").upper().strip()
    try:
        limit = max(1, min(int(limit), 120))
    except (TypeError, ValueError):
        limit = 30
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT day, pe, pb, roe, der, eps, price FROM fund_snap"
            " WHERE ticker=? ORDER BY day DESC LIMIT ?",
            (code, limit),
        ).fetchall()
    return [
        {"day": r["day"], "pe": r["pe"], "pb": r["pb"], "roe": r["roe"],
         "der": r["der"], "eps": r["eps"], "price": r["price"]}
        for r in rows
    ]


def add_signal(payload: dict, source: str = "manual") -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO signals(ts,ticker,signal,action,score,confidence,grade,price,entry,stop_loss,tp1,source)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _now(),
                payload.get("ticker"),
                payload.get("signal"),
                payload.get("action"),
                payload.get("score"),
                payload.get("confidence"),
                payload.get("grade"),
                payload.get("price"),
                payload.get("entry"),
                payload.get("stop_loss"),
                payload.get("tp1"),
                source,
            ),
        )


def add_scan(universe: str, n: int, buys: int, note: str = "") -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO scans(ts,universe,n,buys,note) VALUES(?,?,?,?,?)",
            (_now(), universe, n, buys, note),
        )


def recent_signals(limit: int = 100, ticker: str | None = None) -> list[dict]:
    with _lock, _conn() as c:
        if ticker:
            rows = c.execute(
                "SELECT * FROM signals WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker.upper(), limit)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def recent_scans(limit: int = 30) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def paper_open(ticker: str, side: str, entry: float, lots: int, stop: float, tp: float, note: str = "") -> int:
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO paper(ticker,side,entry,lots,stop,tp,opened,status,note) VALUES(?,?,?,?,?,?,?,?,?)",
            (ticker.upper(), side, entry, lots, stop, tp, _now(), "OPEN", note),
        )
        return int(cur.lastrowid)


def paper_rows(status: str | None = None) -> list[dict]:
    with _lock, _conn() as c:
        if status:
            rows = c.execute("SELECT * FROM paper WHERE status=? ORDER BY id DESC", (status,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM paper ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def pending_signals(horizon: int, lookback_days: int, limit: int = 500) -> list[dict]:
    """Sinyal cukup tua untuk dievaluasi pada `horizon` tapi belum punya hasil.

    Usia minimum = horizon*2+2 hari kalender (buffer akhir pekan/libur);
    sinyal yang belum cukup tua tidak dikembalikan — dievaluasi nanti, bukan
    spekulatif. Sinyal tanpa ticker/harga dilewati (tak bisa dievaluasi).
    """
    init()
    try:
        horizon = int(horizon)
        lookback_days = int(lookback_days)
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        return []
    now = time.time()
    oldest = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - lookback_days * 86400))
    youngest = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - (horizon * 2 + 2) * 86400))
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT s.* FROM signals s"
            " LEFT JOIN signal_outcomes o ON o.signal_id=s.id AND o.horizon=?"
            " WHERE o.signal_id IS NULL AND s.ts BETWEEN ? AND ?"
            "   AND s.ticker IS NOT NULL AND s.price IS NOT NULL"
            " ORDER BY s.id DESC LIMIT ?",
            (horizon, oldest, youngest, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def outcome_upsert(signal_id: int, horizon: int, n_bars: int,
                   fwd_return_pct: float, bench_fwd_pct: float | None,
                   excess_pct: float | None, tp1_hit: bool, sl_hit: bool,
                   outcome: str) -> None:
    """Simpan hasil evaluasi sinyal. Evaluasi pertama bersifat final (DO NOTHING):
    jendela waktu sudah fix, tidak pernah ditimpa ulang."""
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO signal_outcomes(signal_id,horizon,evaluated_at,n_bars,fwd_return_pct,"
            "bench_fwd_pct,excess_pct,tp1_hit,sl_hit,outcome) VALUES(?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(signal_id,horizon) DO NOTHING",
            (signal_id, horizon, _now(), n_bars, fwd_return_pct, bench_fwd_pct, excess_pct,
             1 if tp1_hit else 0, 1 if sl_hit else 0, outcome),
        )


def outcomes_summary(horizon: int = 5) -> dict:
    """Rekap hasil evaluasi (feedback loop). n=0 bila belum ada yang dievaluasi."""
    init()
    try:
        horizon = int(horizon)
    except (TypeError, ValueError):
        horizon = 5
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT o.*, s.ticker, s.signal, s.action, s.score, s.ts AS signal_ts"
            " FROM signal_outcomes o JOIN signals s ON s.id=o.signal_id"
            " WHERE o.horizon=? ORDER BY o.signal_id DESC",
            (horizon,),
        ).fetchall()
    rows = [dict(r) for r in rows]
    n = len(rows)
    if not n:
        return {"horizon": horizon, "n": 0}
    rets = [float(r["fwd_return_pct"]) for r in rows if r.get("fwd_return_pct") is not None]
    exc = [float(r["excess_pct"]) for r in rows if r.get("excess_pct") is not None]
    n_tp1 = sum(1 for r in rows if r.get("outcome") == "TP1")
    n_sl = sum(1 for r in rows if r.get("outcome") == "SL")
    n_none = sum(1 for r in rows if r.get("outcome") == "NONE")
    return {
        "horizon": horizon,
        "n": n,
        "win_rate": round(100.0 * sum(1 for x in rets if x > 0) / len(rets), 2) if rets else 0.0,
        "avg_fwd_pct": round(sum(rets) / len(rets), 3) if rets else 0.0,
        "avg_excess_pct": round(sum(exc) / len(exc), 3) if exc else 0.0,
        "n_tp1": n_tp1,
        "n_sl": n_sl,
        "n_none": n_none,
        "tp1_first_rate": round(100.0 * n_tp1 / n, 2),
        "sl_first_rate": round(100.0 * n_sl / n, 2),
        "none_rate": round(100.0 * n_none / n, 2),
        "rows": rows[:60],
    }


def paper_close(pid: int, exit_price: float, pnl: float, note: str = "") -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE paper SET status='CLOSED', closed=?, exit=?, pnl=?, note=COALESCE(NULLIF(?,''),note) WHERE id=?",
            (_now(), exit_price, pnl, note, pid),
        )
