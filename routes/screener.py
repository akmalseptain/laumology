"""Endpoint screener, universe, preset, dan scan latar (server-side)."""
from __future__ import annotations

import threading

from flask import Blueprint, jsonify, request

import screener
import state
import universe
import validate
from config import SECTORS, WATCHLIST_PRESETS

bp = Blueprint("screener", __name__)


def _scan_worker(job_id: str, params: dict) -> None:
    try:
        tickers = screener.resolve_watchlist(params.get("list") or "auto")
    except Exception as exc:
        state.update_scan_job(job_id, state="error", error=str(exc))
        return
    total = len(tickers)
    state.update_scan_job(job_id, state="running", total=total)
    rows: list = []
    i = 0
    first = True
    while i < total:
        if state.scan_cancelled(job_id):
            state.update_scan_job(job_id, state="cancelled")
            return
        chunk = 15 if first else 60  # chunk pertama kecil -> hasil awal cepat
        part = tickers[i:i + chunk]
        try:
            r = screener.screen(
                part,
                min_score=int(params.get("min_score") or 0),
                top=1000,
                refresh=bool(params.get("refresh")),
                min_confidence=int(params.get("min_conf") or 0),
                only_bullish=bool(params.get("only_bullish")),
                sector=(params.get("sector") or None),
                min_value=float(params.get("min_value") or 0),
                decision=(params.get("decision") or None),
            )
            rows.extend(r.to_dict("records"))
        except Exception:
            pass
        i += chunk
        first = False
        state.update_scan_job(job_id, scanned=min(i, total), rows=rows)
    state.update_scan_job(job_id, state="done", scanned=total, rows=rows)


@bp.route("/api/screen")
def api_screen():
    name = (request.args.get("list") or "lq45").strip()
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    only_bullish = request.args.get("only_bullish") in ("1", "true", "yes")
    sector = (request.args.get("sector") or "").strip()
    decision = (request.args.get("decision") or "").strip() or None
    try:
        top = int(request.args.get("top", 20))
        min_score = int(request.args.get("min_score", 0))
        min_conf = int(request.args.get("min_conf", 0))
        min_value = float(request.args.get("min_value", 0) or 0)
    except ValueError:
        top, min_score, min_conf, min_value = 20, 0, 0, 0.0
    try:
        tickers = screener.resolve_watchlist(name)
        result = screener.screen(
            tickers, min_score=min_score, top=top, refresh=refresh,
            min_confidence=min_conf, only_bullish=only_bullish,
            sector=sector or None, min_value=min_value, decision=decision,
        )
    except Exception as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(rows=result.to_dict("records"), count=len(result), scanned=len(tickers))


@bp.route("/api/sectors")
def api_sectors():
    return jsonify(sectors=SECTORS, presets=list(WATCHLIST_PRESETS.keys()))


@bp.route("/api/presets")
def api_presets():
    return jsonify(presets=list(WATCHLIST_PRESETS.keys()))


@bp.route("/api/universe")
def api_universe():
    full = request.args.get("full") in ("1", "true", "yes")
    try:
        limit = max(20, min(int(request.args.get("limit", 180)), 1200))
    except ValueError:
        limit = 180
    try:
        data = universe.full_universe(limit) if full else universe.auto_universe(limit)
        return jsonify(count=len(data), full=full, tickers=data)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/tickers")
def api_tickers():
    name = (request.args.get("list") or "lq45").strip()
    try:
        t = screener.resolve_watchlist(name)
        return jsonify(count=len(t), tickers=t)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/data/quality")
def api_data_quality():
    name = (request.args.get("list") or "lq45").strip()
    try:
        tickers = screener.resolve_watchlist(name)[:60]
        return jsonify(validate.data_quality(tickers))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    b = request.get_json(silent=True) or {}
    jid = state.create_scan_job(b)
    threading.Thread(target=_scan_worker, args=(jid, b), daemon=True, name="scan-" + jid).start()
    return jsonify(job=jid)


@bp.route("/api/scan/status")
def api_scan_status():
    jid = (request.args.get("id") or "").strip()
    payload = state.get_scan_job(jid)
    if payload is None:
        return jsonify(error="job tidak ditemukan"), 404
    rows = payload.get("rows") or []
    top = request.args.get("top")
    if top:
        try:
            t = int(top)
            if t > 0:
                payload["rows"] = sorted(rows, key=lambda x: (x.get("Score", 0), x.get("Conf", 0)),
                                         reverse=True)[:t]
        except ValueError:
            pass
    return jsonify(payload)


@bp.route("/api/scan/cancel", methods=["POST"])
def api_scan_cancel():
    b = request.get_json(silent=True) or {}
    jid = str(b.get("id") or "")
    if state.cancel_scan_job(jid):
        return jsonify(ok=True)
    return jsonify(error="job tidak ditemukan"), 404
