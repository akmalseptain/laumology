"""Track record publik: riwayat sinyal, hasil paper trading, dan hit-rate.

Semua angka diambil langsung dari DB lokal (store) — tidak ada proyeksi
atau angka yang tidak bisa dibuktikan. Kalau datanya kosong, halaman
jujur menampilkan "belum ada data".

Endpoint:
- GET /track-record        halaman publik (server-rendered, tanpa JS)
- GET /api/trackrecord      JSON ringkasan yang sama
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template

import metrics
import store

bp = Blueprint("trackrecord", __name__)


def _trade_return_pct(row: dict) -> float | None:
    """Return % per posisi. Kausal: hanya entry & exit yang sudah terjadi."""
    try:
        entry = float(row.get("entry") or 0.0)
        exit_raw = row.get("exit")
        if not entry or exit_raw is None:
            return None
        exit_f = float(exit_raw)
        raw = (exit_f - entry) / entry * 100.0
        side = str(row.get("side") or "BUY").upper()
        return -raw if side.startswith("SELL") else raw
    except (TypeError, ValueError):
        return None


def _equity_curve(returns_pct: list[float], start: float = 100.0) -> list[float]:
    """Kurva ekuitas ternormalisasi (100 = awal), compounded per trade."""
    curve = [start]
    eq = start
    for r in returns_pct:
        eq *= 1.0 + r / 100.0
        curve.append(round(eq, 4))
    return curve


def summary() -> dict:
    closed = store.paper_rows(status="CLOSED")
    open_trades = store.paper_rows(status="OPEN")
    signals = store.recent_signals(limit=200)
    scans = store.recent_scans(limit=30)

    # Urut waktu (tertua dulu) supaya kurva ekuitas tidak terbalik.
    closed_chrono = list(reversed(closed))
    returns = [r for r in (_trade_return_pct(t) for t in closed_chrono) if r is not None]
    equity = _equity_curve(returns)

    rm = metrics.risk_metrics(equity, trade_returns_pct=returns or None)

    n_wins = sum(1 for r in returns if r > 0)
    n_losses = sum(1 for r in returns if r <= 0)
    total_pnl = 0.0
    for t in closed:
        try:
            total_pnl += float(t.get("pnl") or 0.0)
        except (TypeError, ValueError):
            pass

    per_ticker: dict[str, dict] = {}
    for t in closed:
        tick = str(t.get("ticker") or "?").upper()
        r = _trade_return_pct(t)
        if r is None:
            continue
        s = per_ticker.setdefault(tick, {"ticker": tick, "n": 0, "wins": 0, "ret": 0.0})
        s["n"] += 1
        s["wins"] += 1 if r > 0 else 0
        s["ret"] = round(s["ret"] + r, 2)
    rows_ticker = sorted(per_ticker.values(), key=lambda s: s["ret"], reverse=True)

    outcomes = store.outcomes_summary(5)
    attribution = store.outcomes_by_bucket(5)
    verdicts = store.outcome_verdicts(5)

    signals_by_action: dict[str, int] = {}
    for s in signals:
        a = str(s.get("action") or s.get("signal") or "?")
        signals_by_action[a] = signals_by_action.get(a, 0) + 1

    return {
        "closed_trades": closed,
        "open_trades": open_trades,
        "signals": signals[:60],
        "scans": scans,
        "n_signals": len(signals),
        "win_rate": rm.get("win_rate", 0.0),
        "payoff": rm.get("payoff", 0.0),
        "kelly": rm.get("kelly", 0.0),
        "expectancy_pct": rm.get("expectancy_pct", 0.0),
        "sharpe": rm.get("sharpe", 0.0),
        "n_closed": len(closed),
        "n_open": len(open_trades),
        "n_wins": n_wins,
        "n_losses": n_losses,
        "total_pnl": total_pnl,
        "equity_curve": equity,
        "per_ticker": rows_ticker,
        "signals_by_action": signals_by_action,
        "outcomes": outcomes,
        "attribution": attribution,
        "verdicts": verdicts,
    }


@bp.get("/track-record")
def page():
    return render_template("trackrecord.html", **summary())


@bp.get("/api/trackrecord")
def api():
    return jsonify(summary())
