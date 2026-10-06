from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, request

import backtest as backtest_mod
import consensus_backtest as consensus_mod
import data
import fundamentals
import indicators
import llm
import market
import metrics
import ml
import musyawarah as musyawarah_mod
import news
import notify
import risk
import screener
import store
import universe
import validate
import validation
from config import SECTORS, WATCHLIST_PRESETS, sector_of
from signals import analyze

app = Flask(__name__)
store.init()


def _load_dotenv(path: str = ".env") -> None:
    try:
        p = Path(path)
        if not p.exists():
            return
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except Exception:
        pass


_load_dotenv()

_history: list[dict] = []
_history_lock = threading.Lock()
_HISTORY_MAX = 300

VERSION = "1.0.0"
_START = time.time()
_metrics = {"requests": 0, "errors": 0, "by_path": {}}
_metrics_lock = threading.Lock()
_rl: dict[str, list[float]] = {}
_rl_lock = threading.Lock()
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "600"))
API_KEY = os.environ.get("API_KEY", "")
_PROTECTED = {"/api/paper/open", "/api/paper/close", "/api/notify"}

# --- Background scan jobs (server-side) ---
_scan_jobs: dict[str, dict] = {}
_scan_lock = threading.Lock()
_SCAN_JOBS_MAX = 6


def _scan_worker(job_id: str, params: dict) -> None:
    try:
        tickers = screener.resolve_watchlist(params.get("list") or "auto")
    except Exception as exc:
        with _scan_lock:
            _scan_jobs[job_id].update(state="error", error=str(exc))
        return
    total = len(tickers)
    with _scan_lock:
        _scan_jobs[job_id].update(state="running", total=total)
    rows: list = []
    chunk = 60
    for i in range(0, total, chunk):
        with _scan_lock:
            if _scan_jobs[job_id].get("cancel"):
                _scan_jobs[job_id]["state"] = "cancelled"
                return
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
            )
            rows.extend(r.to_dict("records"))
        except Exception:
            pass
        with _scan_lock:
            _scan_jobs[job_id]["scanned"] = min(i + chunk, total)
            _scan_jobs[job_id]["rows"] = rows
    with _scan_lock:
        _scan_jobs[job_id].update(state="done", scanned=total, rows=rows)


@app.before_request
def _guard():
    if request.path.startswith("/api"):
        ip = request.remote_addr or "?"
        now = time.time()
        with _rl_lock:
            win = _rl.setdefault(ip, [])
            win[:] = [t for t in win if now - t < 60]
            if len(win) >= RATE_LIMIT_PER_MIN:
                return jsonify(error="Rate limit terlampaui"), 429
            win.append(now)
    if API_KEY and request.method == "POST" and request.path in _PROTECTED:
        if request.headers.get("X-API-Key") != API_KEY:
            return jsonify(error="Unauthorized"), 401
    return None


@app.after_request
def _track(resp):
    with _metrics_lock:
        _metrics["requests"] += 1
        if resp.status_code >= 400:
            _metrics["errors"] += 1
        _metrics["by_path"][request.path] = _metrics["by_path"].get(request.path, 0) + 1
    if not request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(Exception)
def _json_errors(e):
    """Pastikan semua error di /api/* SELALU dibalas JSON (bukan HTML)."""
    from werkzeug.exceptions import HTTPException
    code = e.code if isinstance(e, HTTPException) else 500
    if request.path.startswith("/api/"):
        return jsonify(error=str(e) or "error", code=code), code
    if isinstance(e, HTTPException):
        return e
    return "Internal Server Error", 500


INTERVAL_PERIOD = {
    "1d": "1y",
    "1wk": "5y",
    "1h": "60d",
    "30m": "30d",
    "15m": "20d",
    "5m": "10d",
}


def _analysis_payload(ticker: str, refresh: bool, bars: int, interval: str) -> dict:
    period = INTERVAL_PERIOD.get(interval, "1y")
    df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
    quote = data.get_quote(ticker)
    df, live = data.apply_live_quote(df, quote, interval)
    a = analyze(df, ticker)
    if live:
        a.price = live["price"]
        if live.get("prev_close"):
            a.change_1d = (live["price"] / live["prev_close"] - 1.0) * 100.0
    return {
        "ticker": a.ticker,
        "last_date": df.index[-1].strftime("%d %b %Y %H:%M"),
        "bars": len(df),
        "interval": interval,
        "tv_symbol": "IDX:" + a.ticker,
        "price": a.price,
        "change_1d": a.change_1d,
        "change_20d": a.ret_20d,
        "live": bool(live),
        "quote_source": live.get("source") if live else None,
        "quote_time": live.get("quote_time") if live else None,
        "day_high": live.get("day_high") if live else None,
        "day_low": live.get("day_low") if live else None,
        "signal": a.signal,
        "action": a.action,
        "score": a.score,
        "confidence": a.confidence,
        "grade": a.grade,
        "trend": a.trend,
        "weekly_trend": a.weekly_trend,
        "regime": a.regime,
        "entry": a.entry,
        "entry_pullback": a.entry_pullback,
        "entry_breakout": a.entry_breakout,
        "buy_zone_low": a.buy_zone_low,
        "buy_zone_high": a.buy_zone_high,
        "stop_loss": a.stop_loss,
        "stop_trail": a.stop_trail,
        "tp1": a.tp1,
        "tp2": a.tp2,
        "tp3": a.tp3,
        "rr1": a.rr1,
        "rr2": a.rr2,
        "rr3": a.rr3,
        "risk_pct": (a.entry - a.stop_loss) / a.entry * 100.0 if a.entry else 0.0,
        "atr_pct": a.atr_pct,
        "rsi": a.rsi,
        "stoch_k": a.stoch_k,
        "macd_hist": a.macd_hist,
        "adx": a.adx,
        "plus_di": a.plus_di,
        "minus_di": a.minus_di,
        "cci": a.cci,
        "mfi": a.mfi,
        "cmf": a.cmf,
        "vol_ratio": a.vol_ratio,
        "support": a.support,
        "resistance": a.resistance,
        "pivot": a.pivot,
        "fib": a.fib,
        "rs_change": a.rs_change,
        "rs_strong": a.rs_strong,
        "st_dir_up": a.st_dir_up,
        "lots": a.lots,
        "position_value": a.position_value,
        "max_loss": a.max_loss,
        "risk_amount": a.risk_amount,
        "patterns": a.patterns,
        "divergences": a.divergences,
        "checklist": [{"label": k, "pass": v} for k, v in a.checklist],
        "components": a.components,
        "reasons": a.reasons,
        "warnings": a.warnings,
        "squeeze_on": a.squeeze_on,
        "squeeze_mom": a.squeeze_mom,
        "chop": a.chop,
        "adr_pct": a.adr_pct,
        "atr_pctl": a.atr_pctl,
        "vol_regime": a.vol_regime,
        "avwap": a.avwap,
        "monthly_trend": a.monthly_trend,
        "mtf": a.mtf,
        "vp": a.vp,
        "zones": a.zones,
    }


def _num_or_none(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _time_formatter(interval: str):
    daily = interval in ("1d", "1wk", "1mo", "3mo")

    def fmt(ts):
        ts = pd.Timestamp(ts)
        if daily:
            return {"year": int(ts.year), "month": int(ts.month), "day": int(ts.day)}
        return int(ts.timestamp())

    return fmt


def _ohlc_payload(ticker: str, interval: str, bars: int, refresh: bool = False) -> dict:
    period = INTERVAL_PERIOD.get(interval, "1y")
    df = data.get_ohlcv(ticker, period=period, interval=interval, use_cache=not refresh)
    quote = data.get_quote(ticker)
    df, live = data.apply_live_quote(df, quote, interval)
    a = analyze(df, ticker)
    if live:
        a.price = live["price"]
        if live.get("prev_close"):
            a.change_1d = (live["price"] / live["prev_close"] - 1.0) * 100.0

    d = indicators.add_indicators(df).tail(bars)
    fmt_time = _time_formatter(interval)

    candles: list[dict] = []
    volume: list[dict] = []
    for ts, row in d.iterrows():
        o = _num_or_none(row.get("Open"))
        h = _num_or_none(row.get("High"))
        low = _num_or_none(row.get("Low"))
        c = _num_or_none(row.get("Close"))
        if None in (o, h, low, c):
            continue
        t = fmt_time(ts)
        candles.append({"time": t, "open": o, "high": h, "low": low, "close": c})
        vol = _num_or_none(row.get("Volume")) or 0.0
        volume.append({"time": t, "value": vol, "color": "#26a69a" if c >= o else "#ef5350"})

    def line(col: str) -> list[dict]:
        out: list[dict] = []
        if col not in d.columns:
            return out
        for ts, v in d[col].items():
            fv = _num_or_none(v)
            if fv is None:
                continue
            out.append({"time": fmt_time(ts), "value": round(fv, 4)})
        return out

    st_up: list[dict] = []
    st_down: list[dict] = []
    for ts, row in d.iterrows():
        sv = _num_or_none(row.get("supertrend"))
        if sv is None:
            continue
        point = {"time": fmt_time(ts), "value": round(sv, 4)}
        if _num_or_none(row.get("st_dir")) == 1.0:
            st_up.append(point)
        else:
            st_down.append(point)

    levels = [
        {"price": a.entry, "color": "#2962ff", "title": "ENTRY"},
        {"price": a.stop_loss, "color": "#d50000", "title": "SL"},
        {"price": a.tp1, "color": "#00c853", "title": "TP1"},
        {"price": a.tp2, "color": "#00a03a", "title": "TP2"},
        {"price": a.tp3, "color": "#00701f", "title": "TP3"},
        {"price": a.vp.get("poc"), "color": "#f5c518", "title": "POC"},
        {"price": a.vp.get("vah"), "color": "#ff8f00", "title": "VAH"},
        {"price": a.vp.get("val"), "color": "#ff8f00", "title": "VAL"},
    ]

    benchmark: list[dict] = []
    try:
        bdf = data.get_ohlcv("^JKSE", suffix="", period=period, interval=interval, use_cache=not refresh)
        b = bdf["Close"].reindex(d.index).ffill()
        c0 = _num_or_none(d["Close"].iloc[0])
        b0 = _num_or_none(b.iloc[0])
        if c0 and b0:
            scale = c0 / b0
            for ts, v in b.items():
                fv = _num_or_none(v)
                if fv is not None:
                    benchmark.append({"time": fmt_time(ts), "value": round(fv * scale, 4)})
    except Exception:
        benchmark = []

    return {
        "ticker": a.ticker,
        "interval": interval,
        "bars": len(candles),
        "live": bool(live),
        "quote_source": live.get("source") if live else None,
        "last_date": df.index[-1].strftime("%d %b %Y %H:%M"),
        "price": a.price,
        "change_1d": a.change_1d,
        "candles": candles,
        "volume": volume,
        "overlays": {
            "ma20": line("ma20"),
            "ma50": line("ma50"),
            "ma200": line("ma200"),
            "ema21": line("ema21"),
            "avwap": line("avwap"),
            "supertrend_up": st_up,
            "supertrend_down": st_down,
        },
        "rsi": line("rsi"),
        "macd": line("macd"),
        "macd_signal": line("macd_signal"),
        "macd_hist": line("macd_hist"),
        "levels": [lv for lv in levels if lv["price"]],
        "benchmark": benchmark,
        "signal": a.signal,
        "action": a.action,
        "score": a.score,
        "confidence": a.confidence,
        "grade": a.grade,
    }


@app.route("/api/ohlc")
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
        return jsonify(_ohlc_payload(ticker, interval, bars, refresh))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/")
def index():
    return render_template("index.html", presets=list(WATCHLIST_PRESETS.keys()))


@app.route("/api/analyze")
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
        payload = _analysis_payload(ticker, refresh, bars, interval)
    except Exception as exc:
        return jsonify(error=str(exc)), 502
    if request.args.get("log") in ("1", "true", "yes"):
        _record_history(payload)
    return jsonify(payload)


def _record_history(payload: dict) -> None:
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ticker": payload.get("ticker"),
        "signal": payload.get("signal"),
        "action": payload.get("action"),
        "score": payload.get("score"),
        "confidence": payload.get("confidence"),
        "grade": payload.get("grade"),
        "price": payload.get("price"),
        "entry": payload.get("entry"),
        "stop_loss": payload.get("stop_loss"),
        "tp1": payload.get("tp1"),
    }
    with _history_lock:
        _history.append(entry)
        if len(_history) > _HISTORY_MAX:
            del _history[: len(_history) - _HISTORY_MAX]


@app.route("/api/history")
def api_history():
    with _history_lock:
        items = list(reversed(_history))
    limit = request.args.get("limit")
    if limit:
        try:
            items = items[: max(1, int(limit))]
        except ValueError:
            pass
    return jsonify(rows=items)


@app.route("/api/sectors")
def api_sectors():
    return jsonify(sectors=SECTORS, presets=list(WATCHLIST_PRESETS.keys()))


@app.route("/api/backtest")
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


@app.route("/api/optimize")
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


@app.route("/api/ml")
def api_ml():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        horizon = max(1, min(int(request.args.get("horizon", 10)), 60))
    except ValueError:
        horizon = 10
    try:
        return jsonify(ml.predict(data.get_ohlcv(ticker), ticker, horizon=horizon))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/api/news")
def api_news():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        return jsonify(news.get_news(ticker))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/api/db/signals")
def api_db_signals():
    ticker = (request.args.get("ticker") or "").strip().upper() or None
    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 500))
    except ValueError:
        limit = 100
    return jsonify(rows=store.recent_signals(limit=limit, ticker=ticker))


@app.route("/api/db/scans")
def api_db_scans():
    return jsonify(rows=store.recent_scans(limit=30))


@app.route("/api/paper")
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


@app.route("/api/paper/open", methods=["POST"])
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


@app.route("/api/paper/close", methods=["POST"])
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


@app.route("/api/walkforward")
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


@app.route("/api/market")
def api_market():
    name = (request.args.get("list") or "lq45").strip()
    try:
        tickers = screener.resolve_watchlist(name)
        return jsonify(market.overview(tickers))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/api/fundamental")
def api_fundamental():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        return jsonify(fundamentals.get_fundamentals(ticker))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/api/correlation")
def api_correlation():
    tickers = [t.strip().upper() for t in (request.args.get("tickers") or "").split(",") if t.strip()]
    if len(tickers) < 2:
        return jsonify(error="Butuh minimal 2 kode"), 400
    try:
        return jsonify(risk.correlation(tickers))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/api/portfolio-risk", methods=["POST"])
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


@app.route("/api/notify", methods=["POST"])
def api_notify():
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or "").strip()
    if not text:
        return jsonify(error="Teks kosong"), 400
    result = notify.dispatch(text, {"text": text, "meta": body.get("meta")})
    return jsonify(ok=True, result=result)


@app.route("/api/notify/status")
def api_notify_status():
    return jsonify(webhook=bool(notify.webhook_url()))


@app.route("/api/accuracy")
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


@app.route("/api/quote")
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


@app.route("/api/screen")
def api_screen():
    name = (request.args.get("list") or "lq45").strip()
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    only_bullish = request.args.get("only_bullish") in ("1", "true", "yes")
    sector = (request.args.get("sector") or "").strip()
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
            sector=sector or None, min_value=min_value,
        )
    except Exception as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(rows=result.to_dict("records"), count=len(result), scanned=len(tickers))


@app.route("/api/presets")
def api_presets():
    return jsonify(presets=list(WATCHLIST_PRESETS.keys()))


@app.route("/api/universe")
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


@app.route("/api/tickers")
def api_tickers():
    name = (request.args.get("list") or "lq45").strip()
    try:
        t = screener.resolve_watchlist(name)
        return jsonify(count=len(t), tickers=t)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/api/musyawarah")
def api_musyawarah():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    use_llm = request.args.get("llm") in ("1", "true", "yes")
    try:
        return jsonify(musyawarah_mod.musyawarah(ticker, use_llm=use_llm))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/api/llm/status")
def api_llm_status():
    return jsonify(configured=llm.configured(), model=llm._model(), prompt=llm.PROMPT_PATH.exists())


@app.route("/api/optimize-weights")
def api_optimize_weights():
    universe = (request.args.get("list") or "idx30").strip()
    try:
        tp_rr = float(request.args.get("tp_rr", 3.0))
        sl_mult = float(request.args.get("sl_mult", 2.0))
        max_hold = max(2, min(int(request.args.get("max_hold", 20)), 120))
    except ValueError:
        tp_rr, sl_mult, max_hold = 3.0, 2.0, 20
    try:
        return jsonify(consensus_mod.optimize_weights(universe, tp_rr, sl_mult, max_hold))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/health")
def health():
    return jsonify(status="ok", version=VERSION, uptime_s=int(time.time() - _START),
                   db=str(store.DB_PATH), time=time.strftime("%Y-%m-%d %H:%M:%S"))


@app.route("/api/version")
def api_version():
    return jsonify(version=VERSION, engine="laumology", python=sys.version.split()[0])


@app.route("/api/metrics")
def api_metrics():
    with _metrics_lock:
        m = {"requests": _metrics["requests"], "errors": _metrics["errors"],
             "by_path": dict(_metrics["by_path"])}
    return jsonify(uptime_s=int(time.time() - _START), **m)


@app.route("/api/schema")
def api_schema():
    return jsonify(version=VERSION, endpoints=[
        {"method": "GET", "path": "/api/analyze", "params": ["ticker", "interval", "refresh", "bars", "log"]},
        {"method": "GET", "path": "/api/ohlc", "params": ["ticker", "interval", "bars", "refresh"]},
        {"method": "GET", "path": "/api/quote", "params": ["ticker"]},
        {"method": "GET", "path": "/api/screen", "params": ["list", "top", "min_score", "min_conf", "sector", "min_value", "only_bullish"]},
        {"method": "GET", "path": "/api/backtest", "params": ["ticker", "interval", "min_score", "tp_rr", "sl_mult", "max_hold"]},
        {"method": "GET", "path": "/api/walkforward", "params": ["ticker", "folds"]},
        {"method": "GET", "path": "/api/optimize", "params": ["ticker"]},
        {"method": "GET", "path": "/api/optimize-weights", "params": ["list"]},
        {"method": "GET", "path": "/api/accuracy", "params": ["ticker", "horizon"]},
        {"method": "GET", "path": "/api/ml", "params": ["ticker", "horizon"]},
        {"method": "GET", "path": "/api/news", "params": ["ticker"]},
        {"method": "GET", "path": "/api/fundamental", "params": ["ticker"]},
        {"method": "GET", "path": "/api/market", "params": ["list"]},
        {"method": "GET", "path": "/api/correlation", "params": ["tickers"]},
        {"method": "POST", "path": "/api/portfolio-risk", "params": ["positions", "capital"]},
        {"method": "GET", "path": "/api/musyawarah", "params": ["ticker", "llm"]},
        {"method": "GET", "path": "/api/paper", "params": []},
        {"method": "POST", "path": "/api/paper/open", "params": ["ticker", "entry", "lots", "stop", "tp"]},
        {"method": "POST", "path": "/api/paper/close", "params": ["id", "exit"]},
        {"method": "GET", "path": "/api/data/quality", "params": ["list"]},
        {"method": "GET", "path": "/api/seasonality", "params": ["ticker"]},
        {"method": "GET", "path": "/health", "params": []},
        {"method": "GET", "path": "/api/metrics", "params": []},
    ])


@app.route("/api/data/quality")
def api_data_quality():
    name = (request.args.get("list") or "lq45").strip()
    try:
        tickers = screener.resolve_watchlist(name)[:60]
        return jsonify(validate.data_quality(tickers))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/api/seasonality")
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


@app.route("/api/disclaimer")
def api_disclaimer():
    return jsonify(
        text=("LAUMOLOGY adalah alat bantu analisis dan edukasi, BUKAN nasihat keuangan/investasi. "
              "Data dapat tertunda dan akurasi tidak dijamin. Keputusan investasi sepenuhnya tanggung "
              "jawab pengguna. Selalu kelola risiko dan konsultasikan dengan penasihat berlisensi.")
    )


@app.route("/api/summary")
def api_summary():
    out: dict = {}
    try:
        out["ihsg"] = market.ihsg()
    except Exception:
        out["ihsg"] = {}
    try:
        rows = store.recent_signals(limit=300)
        today = time.strftime("%Y-%m-%d")
        buys = [r for r in rows if str(r.get("ts", "")).startswith(today)
                and r.get("signal") in ("BUY", "STRONG BUY")]
        out["signals_today"] = len(buys)
        out["latest_signals"] = rows[:8]
    except Exception:
        out["signals_today"] = 0
        out["latest_signals"] = []
    try:
        out["scans"] = store.recent_scans(limit=3)
    except Exception:
        out["scans"] = []
    return jsonify(out)


def _lan_ips() -> list[str]:
    import socket
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" not in ip and not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


@app.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    b = request.get_json(silent=True) or {}
    jid = uuid.uuid4().hex[:12]
    with _scan_lock:
        done = [k for k, v in _scan_jobs.items() if v.get("state") in ("done", "error", "cancelled")]
        while len(_scan_jobs) >= _SCAN_JOBS_MAX and done:
            _scan_jobs.pop(done.pop(0), None)
        _scan_jobs[jid] = {"state": "queued", "scanned": 0, "total": 0, "rows": [],
                           "created": time.time(), "cancel": False, "error": None}
    threading.Thread(target=_scan_worker, args=(jid, b), daemon=True, name="scan-" + jid).start()
    return jsonify(job=jid)


@app.route("/api/scan/status")
def api_scan_status():
    jid = (request.args.get("id") or "").strip()
    with _scan_lock:
        j = _scan_jobs.get(jid)
        if not j:
            return jsonify(error="job tidak ditemukan"), 404
        rows = list(j.get("rows") or [])
        payload = {"state": j.get("state"), "scanned": j.get("scanned", 0),
                   "total": j.get("total", 0), "error": j.get("error"), "rows": rows}
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


@app.route("/api/scan/cancel", methods=["POST"])
def api_scan_cancel():
    b = request.get_json(silent=True) or {}
    jid = str(b.get("id") or "")
    with _scan_lock:
        if jid in _scan_jobs:
            _scan_jobs[jid]["cancel"] = True
            return jsonify(ok=True)
    return jsonify(error="job tidak ditemukan"), 404


def _maybe_start_scheduler() -> None:
    """Jalankan auto-scanner in-process (untuk Render/VPS). Aktifkan via ENABLE_SCHEDULER=1.

    Aman untuk boot: ada jeda awal, single-flight, dan (default) hanya saat jam bursa.
    """
    if os.environ.get("ENABLE_SCHEDULER") not in ("1", "true", "yes"):
        return
    try:
        import scheduler as sched_mod
    except Exception:
        return
    import datetime as _dt

    interval = max(120, int(os.environ.get("SCAN_INTERVAL", "900")))
    universe = os.environ.get("SCAN_UNIVERSE", "lq45")
    window = os.environ.get("SCAN_WINDOW", "market").lower()
    start_delay = int(os.environ.get("SCAN_START_DELAY", "90"))
    warm_universe = os.environ.get("WARM_UNIVERSE", "auto")
    warm_interval = max(600, int(os.environ.get("WARM_INTERVAL", "1800")))

    def _in_window() -> bool:
        if window in ("24h", "all", "always"):
            return True
        try:
            now = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=7)  # WIB
            if now.weekday() >= 5:  # Sabtu/Minggu
                return False
            minutes = now.hour * 60 + now.minute
            return (8 * 60 + 45) <= minutes <= (16 * 60 + 20)
        except Exception:
            return True

    def loop() -> None:
        time.sleep(start_delay)  # beri waktu server siap sebelum kerja berat
        try:
            store.init()
        except Exception:
            pass
        running = False
        last_warm = 0.0
        while True:
            now = time.time()
            if _in_window() and (now - last_warm) >= warm_interval:
                last_warm = now
                try:
                    if warm_universe:
                        sched_mod.warm(warm_universe)
                except Exception:
                    pass
            if _in_window() and not running:
                running = True
                try:
                    sched_mod.run_once(universe)
                except Exception:
                    pass
                running = False
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="laumology-scanner").start()


_maybe_start_scheduler()


def main() -> None:
    parser = argparse.ArgumentParser(description="LAUMOLOGY IDX Trading Terminal (web)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser and args.host not in ("0.0.0.0", "::"):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"LAUMOLOGY jalan di {url}")
    if args.host in ("0.0.0.0", "::"):
        for ip in _lan_ips():
            print(f"  -> dari HP (WiFi sama): http://{ip}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
