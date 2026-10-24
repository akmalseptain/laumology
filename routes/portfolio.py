"""Endpoint portofolio: paper trading, risiko, korelasi, notifikasi, log DB."""
from __future__ import annotations

import math

from flask import Blueprint, jsonify, request

import data
import notify
import paper_auto
import risk
import store
from routes._util import json_object

bp = Blueprint("portfolio", __name__)


def _side_sign(side: str | None) -> float:
    """Arah posisi: BUY untung saat harga naik, SELL (short) untung saat turun."""
    return -1.0 if (side or "BUY").strip().upper() == "SELL" else 1.0


def _pnl(entry: float, price: float, lots: int, side: str | None) -> float:
    """Laba/rugi rupiah posisi paper, memperhitungkan arah (BUY/SELL)."""
    return round((price - entry) * int(lots) * 100 * _side_sign(side), 0)


def _pnl_pct(entry: float, price: float, side: str | None) -> float:
    """Persentase laba/rugi terhadap harga masuk, memperhitungkan arah posisi."""
    if not entry:
        return 0.0
    return round((price / entry - 1.0) * 100.0 * _side_sign(side), 2)


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
                r["pnl"] = _pnl(r["entry"], price, r["lots"], r.get("side"))
                r["pnl_pct"] = _pnl_pct(r["entry"], price, r.get("side"))
    return jsonify(rows=rows)


@bp.route("/api/paper/open", methods=["POST"])
def api_paper_open():
    b = json_object()
    if b is None:
        return jsonify(error="Body harus berupa objek JSON"), 400
    raw_ticker = b.get("ticker")
    if not isinstance(raw_ticker, str) or not raw_ticker.strip():
        return jsonify(error="Kode saham kosong"), 400
    ticker = raw_ticker.strip().upper()
    try:
        entry = float(b.get("entry") or 0)
        lots = int(b.get("lots") or 0)
    except (TypeError, ValueError, OverflowError):
        return jsonify(error="Entry/lot tidak valid"), 400
    # Entry/lot wajib bilangan berhingga & positif. Nilai 0/negatif/NaN/inf
    # (mis. kolom Entry dikosongkan di UI lalu dikirim null -> 0) membuat P/L
    # paper dihitung dari harga tak wajar dan menampilkan seluruh notional
    # sebagai laba. Tolak sebelum menyentuh DB.
    if not math.isfinite(entry) or entry <= 0 or lots <= 0:
        return jsonify(error="Entry/lot harus lebih dari 0"), 400
    try:
        stop = float(b.get("stop") or 0)
        tp = float(b.get("tp") or 0)
    except (TypeError, ValueError):
        return jsonify(error="Stop/TP tidak valid"), 400
    side = b.get("side") or "BUY"
    if side not in ("BUY", "SELL"):
        return jsonify(error="Side tidak valid"), 400
    note = b.get("note")
    if note is None:
        note = ""
    if not isinstance(note, str):
        return jsonify(error="note tidak valid"), 400
    pid = store.paper_open(ticker, side, entry, lots,
                           stop, tp, note)
    return jsonify(ok=True, id=pid)


@bp.route("/api/paper/close", methods=["POST"])
def api_paper_close():
    b = json_object()
    if b is None:
        return jsonify(error="Body harus berupa objek JSON"), 400
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
    try:
        exit_price = float(exit_price)
    except (TypeError, ValueError):
        return jsonify(error="exit tidak valid"), 400
    # Harga close eksekusi selalu > 0. Nilai 0/negatif/NaN/inf (mis. fallback
    # quote yang mengembalikan 0.0) membuat P/L dihitung dari harga tak wajar.
    # Tolak sebelum menyentuh DB, simetris dengan guard di api_paper_open.
    if not math.isfinite(exit_price) or exit_price <= 0:
        return jsonify(error="exit harus lebih dari 0"), 400
    note = b.get("note")
    if note is None:
        note = ""
    if not isinstance(note, str):
        return jsonify(error="note tidak valid"), 400
    pnl = _pnl(row["entry"], exit_price, row["lots"], row.get("side"))
    store.paper_close(pid, exit_price, pnl, note)
    return jsonify(ok=True, exit=exit_price, pnl=pnl)


@bp.route("/api/paper/sync", methods=["POST"])
def api_paper_sync():
    """Sinkron paper trading otomatis SEKARANG (pola batch-32 /api/outcomes/evaluate).

    (1) Tutup posisi OPEN yang TP/SL tersentuh pada bar SETELAH hari sinyal;
    (2) buka posisi paper dari sinyal actionable terbaru per ticker. Best-effort,
    hanya menulis tabel paper - TIDAK menulis sinyal (aman di akhir pekan, beda
    dengan scan), tidak mengubah skor/ambang.
    """
    try:
        limit = max(50, min(int(request.args.get("limit", 400)), 1000))
    except ValueError:
        limit = 400
    try:
        res = paper_auto.sync_paper(limit=limit)
    except Exception as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(ok=True, **res)


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
    body = json_object()
    if body is None:
        return jsonify(error="Body harus berupa objek JSON"), 400
    positions = body.get("positions") or []
    if not isinstance(positions, list) or not all(isinstance(p, dict) for p in positions):
        return jsonify(error="positions harus berupa list objek"), 400
    try:
        capital = float(body.get("capital") or 100000000)
    except (TypeError, ValueError):
        return jsonify(error="capital tidak valid"), 400
    tickers = [p["ticker"] for p in positions if isinstance(p.get("ticker"), str) and p["ticker"]]
    quotes = {}
    for t in set(tickers):
        q = data.get_quote(t)
        if q and q.get("last") is not None:
            quotes[t] = q["last"]
    try:
        result = risk.portfolio_risk(positions, quotes, capital)
    except (TypeError, ValueError, AttributeError):
        return jsonify(error="Input posisi tidak valid"), 400
    return jsonify(result)


@bp.route("/api/notify", methods=["POST"])
def api_notify():
    body = json_object()
    if body is None:
        return jsonify(error="Body harus berupa objek JSON"), 400
    text = str(body.get("text") or "").strip()
    if not text:
        return jsonify(error="Teks kosong"), 400
    result = notify.dispatch(text, {"text": text, "meta": body.get("meta")})
    return jsonify(ok=True, result=result)


@bp.route("/api/notify/status")
def api_notify_status():
    return jsonify(webhook=bool(notify.webhook_url()))
