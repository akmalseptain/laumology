"""Endpoint meta: UI root, health, versi, metrik, skema, disclaimer."""
from __future__ import annotations

import sys
import time

from flask import Blueprint, jsonify, render_template

import state
import store
from config import WATCHLIST_PRESETS

bp = Blueprint("meta", __name__)


@bp.route("/")
def index():
    return render_template("index.html", presets=list(WATCHLIST_PRESETS.keys()))


@bp.route("/health")
def health():
    return jsonify(status="ok", version=state.VERSION,
                   uptime_s=int(time.time() - state.START),
                   db=str(store.DB_PATH),
                   time=time.strftime("%Y-%m-%d %H:%M:%S"))


@bp.route("/api/version")
def api_version():
    return jsonify(version=state.VERSION, engine="laumology", python=sys.version.split()[0])


@bp.route("/api/metrics")
def api_metrics():
    return jsonify(**state.metrics_snapshot())


@bp.route("/api/disclaimer")
def api_disclaimer():
    return jsonify(
        text=("LAUMOLOGY adalah alat bantu analisis dan edukasi, BUKAN nasihat keuangan/investasi. "
              "Data dapat tertunda dan akurasi tidak dijamin. Keputusan investasi sepenuhnya tanggung "
              "jawab pengguna. Selalu kelola risiko dan konsultasikan dengan penasihat berlisensi.")
    )


@bp.route("/api/schema")
def api_schema():
    return jsonify(version=state.VERSION, endpoints=[
        {"method": "GET", "path": "/api/analyze", "params": ["ticker", "interval", "refresh", "bars", "log"]},
        {"method": "GET", "path": "/api/ohlc", "params": ["ticker", "interval", "bars", "refresh"]},
        {"method": "GET", "path": "/api/quote", "params": ["ticker"]},
        {"method": "GET", "path": "/api/screen", "params": ["list", "top", "min_score", "min_conf", "sector", "min_value", "only_bullish"]},
        {"method": "GET", "path": "/api/backtest", "params": ["ticker", "interval", "min_score", "tp_rr", "sl_mult", "max_hold"]},
        {"method": "GET", "path": "/api/walkforward", "params": ["ticker", "folds"]},
        {"method": "GET", "path": "/api/optimize", "params": ["ticker"]},
        {"method": "GET", "path": "/api/optimize-weights", "params": ["list"]},
        {"method": "GET", "path": "/api/accuracy", "params": ["ticker", "horizon"]},
        {"method": "GET", "path": "/api/calibrate", "params": ["list", "horizon", "min_edge"]},
        {"method": "GET", "path": "/api/train", "params": ["list", "horizon", "folds"]},
        {"method": "GET", "path": "/api/model", "params": []},
        {"method": "GET", "path": "/api/ml", "params": ["ticker", "horizon", "candidates"]},
        {"method": "GET", "path": "/api/news", "params": ["ticker"]},
        {"method": "GET", "path": "/api/news/market", "params": []},
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
