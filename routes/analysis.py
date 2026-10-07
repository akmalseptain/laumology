"""Endpoint analisis: OHLC, analyze, quote, history, ML, akurasi, kalibrasi, seasonality."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

import data
import ml
import state
import validation
from payloads import INTERVAL_PERIOD, analysis_payload, ohlc_payload
from screener import resolve_watchlist

bp = Blueprint("analysis", __name__)


@bp.route("/api/ohlc")
def api_ohlc():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    interval = request.args.get("interval", "1d")
    if interval not in INTERVAL_PERIOD:
        interval = "1d"
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        bars = max(60, min(int(request.args.get("bars", 180)), 400))
    except ValueError:
        bars = 180
    try:
        return jsonify(ohlc_payload(ticker, interval, bars, refresh))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/analyze")
def api_analyze():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    interval = request.args.get("interval", "1d")
    if interval not in INTERVAL_PERIOD:
        interval = "1d"
    try:
        bars = max(60, min(int(request.args.get("bars", 150)), 400))
    except ValueError:
        bars = 150
    try:
        payload = analysis_payload(ticker, refresh, bars, interval)
    except Exception as exc:
        return jsonify(error=str(exc)), 502
    if request.args.get("log") in ("1", "true", "yes"):
        state.record_history(payload)
    return jsonify(payload)


@bp.route("/api/history")
def api_history():
    limit = request.args.get("limit")
    lim = None
    if limit:
        try:
            lim = max(1, int(limit))
        except ValueError:
            lim = None
    return jsonify(rows=state.recent_history(lim))


@bp.route("/api/quote")
def api_quote():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    q = data.get_quote(ticker)
    if not q:
        return jsonify(error="Quote tidak tersedia"), 502
    ref = q.get("prev_close")
    q["change_1d"] = (q["last"] / ref - 1.0) * 100.0 if ref else 0.0
    q.setdefault("source", "yfinance")
    return jsonify(q)


@bp.route("/api/ml")
def api_ml():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        horizon = max(1, min(int(request.args.get("horizon", 10)), 60))
    except ValueError:
        horizon = 10
    include_candidates = request.args.get("candidates") in ("1", "true", "yes")
    try:
        return jsonify(ml.predict(data.get_ohlcv(ticker), ticker, horizon=horizon,
                                  include_candidates=include_candidates))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/accuracy")
def api_accuracy():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    interval = request.args.get("interval", "1d")
    if interval not in INTERVAL_PERIOD:
        interval = "1d"
    period = INTERVAL_PERIOD.get(interval, "1y")
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        horizon = max(1, min(int(request.args.get("horizon", 10)), 60))
    except ValueError:
        horizon = 10
    try:
        df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
        result = validation.analyze_accuracy(df, horizon=horizon)
        result["ticker"] = ticker
        return jsonify(result)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/calibrate")
def api_calibrate():
    name = (request.args.get("list") or "lq45").strip()
    try:
        horizon = max(1, min(int(request.args.get("horizon", 10)), 60))
    except ValueError:
        horizon = 10
    try:
        min_edge = float(request.args.get("min_edge", validation.MIN_EDGE))
    except ValueError:
        min_edge = validation.MIN_EDGE
    try:
        tickers = resolve_watchlist(name)
        return jsonify(validation.calibrate(tickers, horizon=horizon, min_edge=min_edge))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/seasonality")
def api_seasonality():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        df = data.get_ohlcv(ticker, period="5y")
        try:
            monthly = df["Close"].resample("ME").last().pct_change().dropna() * 100.0
        except (ValueError, KeyError):
            monthly = df["Close"].resample("M").last().pct_change().dropna() * 100.0
        by = {}
        for m, g in monthly.groupby(monthly.index.month):
            by[int(m)] = {"mean": round(float(g.mean()), 2),
                          "win": round(float((g > 0).mean()) * 100.0, 1), "n": int(len(g))}
        return jsonify(ticker=ticker, months=by)
    except Exception as exc:
        return jsonify(error=str(exc)), 502
