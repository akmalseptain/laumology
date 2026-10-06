from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
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
            """
        )


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


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
