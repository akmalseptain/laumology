"""Endpoint riset: berita, fundamental, kondisi pasar, musyawarah, LLM."""
from __future__ import annotations

import logging
import time

from flask import Blueprint, jsonify, request

import external
import fundamentals
import llm
import market
import musyawarah as musyawarah_mod
import news
import reach
import screener
import store
import ttlcache

bp = Blueprint("research", __name__)

_log = logging.getLogger("laumology.routes.research")

TTL_MARKET = 300.0  # 5 menit; data harian, mengubah hasil hanya bila data baru


@bp.route("/api/news")
def api_news():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        return jsonify(news.get_news(ticker))
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/reach")
def api_reach():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify(error="Kode saham kosong"), 400
    try:
        payload = reach.for_ticker(ticker)
    except Exception as exc:
        return jsonify(error=str(exc)), 502
    if payload.get("error"):
        return jsonify(payload), 400
    return jsonify(payload)


@bp.route("/api/news/market")
def api_news_market():
    try:
        return jsonify(news.get_market_news())
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@bp.route("/api/external")
def api_external():
    ticker = (request.args.get("ticker") or "").strip().upper()
    try:
        if ticker:
            return jsonify(external.for_stock(ticker))
        return jsonify(external.for_market())
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
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    key = f"market:{name}"
    if not refresh:
        hit = ttlcache.get(key)
        if hit is not None:
            return jsonify(hit)
    try:
        tickers = screener.resolve_watchlist(name)
        payload = market.overview(tickers)
        ttlcache.set(key, payload, TTL_MARKET)
        return jsonify(payload)
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
    info = llm.prompt_info()
    return jsonify(
        configured=llm.configured(),
        model=llm._model(),
        prompt=info["source"] == "file",
        prompt_file=info["file"],
        prompt_source=info["source"],
    )


@bp.route("/api/summary")
def api_summary():
    out: dict = {}
    try:
        out["ihsg"] = market.ihsg()
    except Exception as exc:
        _log.warning(
            "ihsg gagal dimuat untuk ringkasan (%s: %s) - tampilkan kosong",
            type(exc).__name__, exc,
        )
        out["ihsg"] = {}
    try:
        rows = store.recent_signals(limit=300)
        today = time.strftime("%Y-%m-%d")
        buys = [r for r in rows if str(r.get("ts", "")).startswith(today)
                and r.get("signal") in ("BUY", "STRONG BUY")]
        out["signals_today"] = len(buys)
        out["latest_signals"] = rows[:8]
    except Exception as exc:
        _log.warning(
            "riwayat sinyal gagal dimuat untuk ringkasan (%s: %s) - hitungan hari ini 0",
            type(exc).__name__, exc,
        )
        out["signals_today"] = 0
        out["latest_signals"] = []
    try:
        out["scans"] = store.recent_scans(limit=3)
    except Exception as exc:
        _log.warning(
            "riwayat scan gagal dimuat untuk ringkasan (%s: %s) - tampilkan kosong",
            type(exc).__name__, exc,
        )
        out["scans"] = []
    return jsonify(out)
