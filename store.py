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


def paper_close(pid: int, exit_price: float, pnl: float, note: str = "") -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE paper SET status='CLOSED', closed=?, exit=?, pnl=?, note=COALESCE(NULLIF(?,''),note) WHERE id=?",
            (_now(), exit_price, pnl, note, pid),
        )
