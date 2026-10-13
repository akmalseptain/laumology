"""Endpoint analisis: OHLC, analyze, quote, history, ML, akurasi, kalibrasi, seasonality."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

import data
import ml
import state
import ttlcache
import validation
from config import settings
from payloads import INTERVAL_PERIOD, analysis_payload, ohlc_payload
from screener import resolve_watchlist

import calibration

TTL_CALIB = 1800.0  # 30 menit; studi statistik berubah hanya bila data/parameter berubah

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
        horizon = max(1, min(int(request.args.get("horizon", settings.swing_horizon_days)), 60))
    except ValueError:
        horizon = settings.swing_horizon_days
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
        horizon = max(1, min(int(request.args.get("horizon", settings.swing_horizon_days)), 60))
    except ValueError:
        horizon = settings.swing_horizon_days
    horizons = None
    raw = request.args.get("horizons")
    if raw is not None:
        try:
            horizons = tuple(int(x) for x in raw.split(",") if x.strip())
        except ValueError:
            return jsonify(error="Parameter horizons tidak valid"), 400
        if not horizons:
            return jsonify(error="Parameter horizons kosong"), 400
        horizons = tuple(max(1, min(h, 60)) for h in horizons)
    try:
        df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
        if horizons is not None:
            result = validation.accuracy_by_horizon(df, horizons=horizons)
        else:
            # Hitung indikator SEKALI dan pakai ulang untuk jalur tunggal maupun
            # pengambilan `reliability` (hindari komputasi ganda; lihat W-0021).
            d = validation.add_indicators(df)
            result = validation.analyze_accuracy(df, horizon=horizon, d=d)
            # Lampirkan verdict keandalan (additive) TANPA mengubah bentuk payload
            # lama. Dibungkus try/except sendiri agar kegagalan `backtest`/sampel
            # tipis tak menjatuhkan seluruh mode tunggal (fail-soft, bukan 502).
            try:
                band = validation.accuracy_by_horizon(df, horizons=(horizon,), d=d)
                result["reliability"] = band["rows"][0]["reliability"]
            except Exception:
                result["reliability"] = None
        result["ticker"] = ticker
        return jsonify(result)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/calibrate")
def api_calibrate():
    name = (request.args.get("list") or "lq45").strip()
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        horizon = max(1, min(int(request.args.get("horizon", settings.swing_horizon_days)), 60))
    except ValueError:
        horizon = settings.swing_horizon_days
    try:
        min_edge = float(request.args.get("min_edge", validation.MIN_EDGE))
    except ValueError:
        min_edge = validation.MIN_EDGE
    key = f"calibrate:{name}:{horizon}:{min_edge}"
    if not refresh:
        hit = ttlcache.get(key)
        if hit is not None:
            return jsonify(hit)
    try:
        tickers = resolve_watchlist(name)
        payload = validation.calibrate(tickers, horizon=horizon, min_edge=min_edge)
        ttlcache.set(key, payload, TTL_CALIB)
        return jsonify(payload)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/model")
def api_model():
    return jsonify(calibration.status())


@bp.route("/api/regime-edge")
def api_regime_edge():
    name = (request.args.get("list") or "lq45").strip()
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        horizon = max(1, min(int(request.args.get("horizon", settings.swing_horizon_days)), 60))
    except ValueError:
        horizon = settings.swing_horizon_days
    key = f"regime-edge:{name}:{horizon}"
    if not refresh:
        hit = ttlcache.get(key)
        if hit is not None:
            return jsonify(hit)
    try:
        tickers = resolve_watchlist(name)
        payload = validation.calibrate_regime(tickers, horizon=horizon)
        ttlcache.set(key, payload, TTL_CALIB)
        return jsonify(payload)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/train")
def api_train():
    name = (request.args.get("list") or "idx30").strip()
    try:
        horizon = max(1, min(int(request.args.get("horizon", settings.swing_horizon_days)), 60))
        folds = max(2, min(int(request.args.get("folds", 5)), 8))
    except ValueError:
        horizon, folds = settings.swing_horizon_days, 5
    try:
        alpha = min(max(float(request.args.get("alpha", 0.5)), 0.0), 1.0)
    except ValueError:
        alpha = 0.5
    try:
        tickers = resolve_watchlist(name)
        res = calibration.train(tickers, horizon=horizon, folds=folds, alpha=alpha)
        return jsonify(ok=True, model=res["model"], universe=res["universe"], errors=res["errors"])
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
