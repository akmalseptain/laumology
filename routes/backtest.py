"""Endpoint backtest, walk-forward, dan optimasi parameter/bobot."""
from __future__ import annotations

import math

import pandas as pd
from flask import Blueprint, jsonify, request

import backtest as backtest_mod
import consensus_backtest as consensus_mod
import data
import metrics
import screener
import ttlcache
from payloads import INTERVAL_PERIOD

bp = Blueprint("backtest", __name__)

TTL_COMPARE = 900.0  # 15 menit; agregat backtest harian


@bp.route("/api/backtest")
def api_backtest():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    interval = request.args.get("interval", "1d")
    if interval not in INTERVAL_PERIOD:
        interval = "1d"
    period = INTERVAL_PERIOD.get(interval, "1y")
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        min_score = int(request.args.get("min_score", 65))
        max_hold = max(2, min(int(request.args.get("max_hold", 20)), 120))
        tp_rr = float(request.args.get("tp_rr", 3.0))
        sl_mult = float(request.args.get("sl_mult", 2.0))
        fee_buy = float(request.args.get("fee_b", 0.15)) / 100.0
        fee_sell = float(request.args.get("fee_s", 0.25)) / 100.0
        slip = float(request.args.get("slip", 0.10)) / 100.0
    except ValueError:
        min_score, max_hold, tp_rr, sl_mult = 65, 20, 3.0, 2.0
        fee_buy, fee_sell, slip = 0.0015, 0.0025, 0.001
    try:
        df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
        res = backtest_mod.backtest(
            df, ticker, min_score=min_score, max_hold=max_hold, tp_rr=tp_rr, sl_mult=sl_mult,
            fee_buy=fee_buy, fee_sell=fee_sell, slip=slip,
        )
        trades = []
        if not res.trades.empty:
            for rec in res.trades.to_dict("records"):
                trades.append({
                    k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in rec.items()
                })
        return jsonify(
            ticker=res.ticker,
            total_return=res.total_return,
            buy_hold_return=res.buy_hold_return,
            n_trades=res.n_trades,
            win_rate=res.win_rate,
            avg_win=res.avg_win,
            avg_loss=res.avg_loss,
            profit_factor=(res.profit_factor if math.isfinite(res.profit_factor) else None),
            max_drawdown=res.max_drawdown,
            expectancy=res.expectancy,
            trades=trades,
            equity_curve=res.equity_curve,
            dates=res.dates,
            risk=metrics.risk_metrics(res.equity_curve, [t.get("return_pct") for t in trades]),
        )
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/walkforward")
def api_walkforward():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    interval = request.args.get("interval", "1d")
    if interval not in INTERVAL_PERIOD:
        interval = "1d"
    period = INTERVAL_PERIOD.get(interval, "1y")
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        folds = max(2, min(int(request.args.get("folds", 4)), 8))
        min_score = int(request.args.get("min_score", 65))
        max_hold = max(2, min(int(request.args.get("max_hold", 20)), 120))
        tp_rr = float(request.args.get("tp_rr", 3.0))
        sl_mult = float(request.args.get("sl_mult", 2.0))
    except ValueError:
        folds, min_score, max_hold, tp_rr, sl_mult = 4, 65, 20, 3.0, 2.0
    try:
        df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
        rows = backtest_mod.walkforward(
            df, ticker, folds=folds, min_score=min_score, max_hold=max_hold, tp_rr=tp_rr, sl_mult=sl_mult
        )
        return jsonify(ticker=ticker, folds=rows)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/compare-backtest")
def api_compare_backtest():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    interval = request.args.get("interval", "1d")
    if interval not in INTERVAL_PERIOD:
        interval = "1d"
    period = INTERVAL_PERIOD.get(interval, "1y")
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        max_hold = max(2, min(int(request.args.get("max_hold", 20)), 120))
        tp_rr = float(request.args.get("tp_rr", 3.0))
        sl_mult = float(request.args.get("sl_mult", 2.0))
    except ValueError:
        max_hold, tp_rr, sl_mult = 20, 3.0, 2.0
    try:
        df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
        return jsonify(backtest_mod.compare_backtest(df, ticker, max_hold=max_hold, tp_rr=tp_rr, sl_mult=sl_mult))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/compare-universe")
def api_compare_universe():
    name = (request.args.get("list") or "idx30").strip()
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        max_hold = max(2, min(int(request.args.get("max_hold", 20)), 120))
        tp_rr = float(request.args.get("tp_rr", 3.0))
        sl_mult = float(request.args.get("sl_mult", 2.0))
    except ValueError:
        max_hold, tp_rr, sl_mult = 20, 3.0, 2.0
    key = f"cmpuni:{name}:{tp_rr}:{sl_mult}:{max_hold}"
    if not refresh:
        hit = ttlcache.get(key)
        if hit is not None:
            return jsonify(hit)
    try:
        tickers = screener.resolve_watchlist(name)
        payload = backtest_mod.compare_universe(tickers, max_hold=max_hold, tp_rr=tp_rr, sl_mult=sl_mult)
        ttlcache.set(key, payload, TTL_COMPARE)
        return jsonify(payload)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/optimize")
def api_optimize():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    interval = request.args.get("interval", "1d")
    if interval not in INTERVAL_PERIOD:
        interval = "1d"
    period = INTERVAL_PERIOD.get(interval, "1y")
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        result = backtest_mod.optimize(
            data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh), ticker
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/optimize-weights")
def api_optimize_weights():
    universe_name = (request.args.get("list") or "idx30").strip()
    try:
        tp_rr = float(request.args.get("tp_rr", 3.0))
        sl_mult = float(request.args.get("sl_mult", 2.0))
        max_hold = max(2, min(int(request.args.get("max_hold", 20)), 120))
    except ValueError:
        tp_rr, sl_mult, max_hold = 3.0, 2.0, 20
    try:
        return jsonify(consensus_mod.optimize_weights(universe_name, tp_rr, sl_mult, max_hold))
    except Exception as exc:
        return jsonify(error=str(exc)), 502
