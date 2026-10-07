"""Endpoint portofolio: paper trading, risiko, korelasi, notifikasi, log DB."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

import data
import notify
import risk
import store

bp = Blueprint("portfolio", __name__)


@bp.route("/api/db/signals")
def api_db_signals():
    ticker = (request.args.get("ticker") or "").strip().upper() or None
    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 500))
    except ValueError:
        limit = 100
    return jsonify(rows=store.recent_signals(limit=limit, ticker=ticker))


@bp.route("/api/db/scans")
def api_db_scans():
    return jsonify(rows=store.recent_scans(limit=30))


@bp.route("/api/paper")
def api_paper():
    rows = store.paper_rows()
    for r in rows:
        if r.get("status") == "OPEN" and r.get("ticker"):
            q = data.get_quote(r["ticker"])
            if q and q.get("last") is not None:
                price = float(q["last"])
                r["last"] = price
                r["pnl"] = round((price - r["entry"]) * int(r["lots"]) * 100, 0)
                r["pnl_pct"] = round((price / r["entry"] - 1.0) * 100.0, 2) if r["entry"] else 0.0
    return jsonify(rows=rows)


@bp.route("/api/paper/open", methods=["POST"])
def api_paper_open():
    b = request.get_json(silent=True) or {}
    ticker = (b.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        entry = float(b.get("entry") or 0)
        lots = int(b.get("lots") or 0)
    except (TypeError, ValueError):
        return jsonify(error="Entry/lot tidak valid"), 400
    if not entry and not lots:
        return jsonify(error="Entry/lot kosong"), 400
    pid = store.paper_open(ticker, b.get("side", "BUY"), entry, lots,
                           float(b.get("stop") or 0), float(b.get("tp") or 0), b.get("note", ""))
    return jsonify(ok=True, id=pid)


@bp.route("/api/paper/close", methods=["POST"])
def api_paper_close():
    b = request.get_json(silent=True) or {}
    try:
        pid = int(b.get("id"))
    except (TypeError, ValueError):
        return jsonify(error="id tidak valid"), 400
    rows = [r for r in store.paper_rows() if r["id"] == pid]
    if not rows:
        return jsonify(error="Posisi tidak ditemukan"), 404
    row = rows[0]
    exit_price = b.get("exit")
    if exit_price in (None, ""):
        q = data.get_quote(row["ticker"])
        exit_price = q["last"] if q and q.get("last") is not None else row["entry"]
    exit_price = float(exit_price)
    pnl = round((exit_price - row["entry"]) * int(row["lots"]) * 100, 0)
    store.paper_close(pid, exit_price, pnl, b.get("note", ""))
    return jsonify(ok=True, exit=exit_price, pnl=pnl)


@bp.route("/api/correlation")
def api_correlation():
    tickers = [t.strip().upper() for t in (request.args.get("tickers") or "").split(",") if t.strip()]
    if len(tickers) < 2:
        return jsonify(error="Butuh minimal 2 kode"), 400
    try:
        return jsonify(risk.correlation(tickers))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/portfolio-risk", methods=["POST"])
def api_portfolio_risk():
    body = request.get_json(silent=True) or {}
    positions = body.get("positions") or []
    capital = float(body.get("capital") or 100000000)
    tickers = [p.get("ticker") for p in positions if p.get("ticker")]
    quotes = {}
    for t in set(tickers):
        q = data.get_quote(t)
        if q and q.get("last") is not None:
            quotes[t] = q["last"]
    return jsonify(risk.portfolio_risk(positions, quotes, capital))


@bp.route("/api/notify", methods=["POST"])
def api_notify():
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or "").strip()
    if not text:
        return jsonify(error="Teks kosong"), 400
    result = notify.dispatch(text, {"text": text, "meta": body.get("meta")})
    return jsonify(ok=True, result=result)


@bp.route("/api/notify/status")
def api_notify_status():
    return jsonify(webhook=bool(notify.webhook_url()))
