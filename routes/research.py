"""Endpoint riset: berita, fundamental, kondisi pasar, musyawarah, LLM."""
from __future__ import annotations

import time

from flask import Blueprint, jsonify, request

import fundamentals
import llm
import market
import musyawarah as musyawarah_mod
import news
import screener
import store

bp = Blueprint("research", __name__)


@bp.route("/api/news")
def api_news():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        return jsonify(news.get_news(ticker))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/news/market")
def api_news_market():
    try:
        return jsonify(news.get_market_news())
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/fundamental")
def api_fundamental():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        return jsonify(fundamentals.get_fundamentals(ticker))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/market")
def api_market():
    name = (request.args.get("list") or "lq45").strip()
    try:
        tickers = screener.resolve_watchlist(name)
        return jsonify(market.overview(tickers))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/sector-strength")
def api_sector_strength():
    name = (request.args.get("list") or "lq45").strip()
    try:
        import stock
        tickers = screener.resolve_watchlist(name)
        m = market.sector_strength(tickers)
        stock.set_sector_map(m)
        return jsonify(sectors=m)
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/musyawarah")
def api_musyawarah():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    use_llm = request.args.get("llm") in ("1", "true", "yes")
    try:
        return jsonify(musyawarah_mod.musyawarah(ticker, use_llm=use_llm))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/llm/status")
def api_llm_status():
    return jsonify(configured=llm.configured(), model=llm._model(), prompt=llm.PROMPT_PATH.exists())


@bp.route("/api/summary")
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
