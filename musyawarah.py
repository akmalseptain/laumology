from __future__ import annotations

import json

import numpy as np

import data
import external
import fundamentals
import llm
import market
import ml
import news
from config import settings
from indicators import add_indicators
from signals import analyze


def _fmt(n) -> str:
    try:
        return f"{float(n):,.0f}"
    except (TypeError, ValueError):
        return "-"


def _bandarmologi(d, last) -> dict:
    close = d["Close"].to_numpy(dtype=float)
    vol = d["Volume"].to_numpy(dtype=float)
    obv = d["obv"].to_numpy(dtype=float)
    obv_ma = d["obv_ma20"].to_numpy(dtype=float)

    cmf = float(last.get("cmf") or 0.0)
    mfi = float(last.get("mfi") or 50.0)

    up_vol = dn_vol = 0.0
    if len(close) > 21:
        ret = np.diff(close[-21:])
        v = vol[-20:]
        up_vol = float(v[ret > 0].sum())
        dn_vol = float(v[ret < 0].sum())
    ratio = up_vol / (up_vol + dn_vol) if (up_vol + dn_vol) > 0 else 0.5
    obv_up = obv[-1] > obv_ma[-1]

    score = 0
    if cmf > 0.03:
        score += 1
    elif cmf < -0.03:
        score -= 1
    if mfi > 55:
        score += 1
    elif mfi < 45:
        score -= 1
    score += 1 if obv_up else -1
    if ratio > 0.55:
        score += 1
    elif ratio < 0.45:
        score -= 1

    if score >= 3:
        status = "AKUMULASI"
    elif score >= 1:
        status = "Akumulasi ringan"
    elif score <= -3:
        status = "DISTRIBUSI MASIF"
    elif score <= -1:
        status = "Distribusi"
    else:
        status = "Netral"

    return {
        "status": status,
        "score": score,
        "cmf": round(cmf, 3),
        "mfi": round(mfi, 1),
        "updown_ratio": round(ratio, 2),
        "obv_up": bool(obv_up),
        "note": "Proxy volume/OBV/CMF/MFI (tanpa data broker summary).",
    }


def _fundamental(f: dict) -> dict:
    roe = f.get("roe")
    der = f.get("der")
    pe = f.get("pe")
    pb = f.get("pb")
    mc = f.get("market_cap")

    if mc and mc >= 5e13:
        cap = "Big Cap"
    elif mc and mc >= 1e13:
        cap = "Mid Cap"
    else:
        cap = "Small Cap"

    if f.get("valuation_code") and f.get("quality_code"):
        labels = {
            "valuation_code": f.get("valuation_code"),
            "valuation_label": f.get("valuation_label"),
            "valuation_note": f.get("valuation_note"),
            "quality_code": f.get("quality_code"),
            "quality_label": f.get("quality_label"),
            "quality_note": f.get("quality_note"),
        }
    else:
        labels = fundamentals.classify_ratios(
            pe, roe, der, sector=f.get("sector_band") or None)

    return {
        "category": f"{cap} · {labels['quality_label']}",
        "valuation": labels["valuation_label"],
        "pe": pe, "pb": pb, "roe": roe, "der": der,
        "dividend_yield": f.get("dividend_yield"),
        "name": f.get("name"),
        **labels,
    }


def _fund_tech_alignment(tech_bias: str, fund: dict, available: bool) -> dict:
    """Penilaian konfluensi deterministik teknikal x fundamental (additive).

    Murni metadata transparansi: TIDAK mengubah bobot/voting/konsensus/
    conviction maupun keputusan. Penalti DIVERGEN sempat dikaji (W-0024) namun
    ditahan karena fundamental belum point-in-time (lihat catatan di
    ``consensus_backtest.py``) dan klasifikasi valuasi masih absolut
    (sector-blind) -> berisiko double-count dengan ``fund_vote``.
    """
    if not available:
        return {"status": "n/a", "note": "Data fundamental tidak tersedia."}
    category = fund.get("category") or ""
    valuation = fund.get("valuation") or ""
    strong = (
        fund.get("quality_code") == "baik"
        or fund.get("valuation_code") == "rendah"
        or "Kualitas Baik" in category
        or "Kualitas baik" in category
        or "Murah" in valuation
        or "rendah" in valuation.lower()
    )
    weak = (
        fund.get("quality_code") == "rugi"
        or fund.get("valuation_code") == "tinggi"
        or "Rugi" in category
        or "Mahal" in valuation
        or "tinggi" in valuation.lower()
    )
    if tech_bias == "BULLISH" and strong:
        status, note = "SEARAH", "Teknikal bullish didukung fundamental kuat/murah."
    elif tech_bias == "BEARISH" and weak:
        status, note = "SEARAH", "Teknikal bearish sejalan fundamental lemah/mahal."
    elif (tech_bias == "BULLISH" and weak) or (tech_bias == "BEARISH" and strong):
        status, note = "DIVERGEN", "Sinyal teknikal dan fundamental bertentangan (informasional; tidak mengubah konsensus)."
    else:
        status, note = "NETRAL", "Tidak ada konfirmasi/pertentangan berarti."
    return {"status": status, "note": note}


# Geser vote sentimen hanya bila tekanan/dukungan luar sudah terkonfirmasi
# (IHSG ikut bergerak dan intensitas cukup). Judul tanpa gejolak tidak dihitung.
_LUAR_SELL = 0.4
_LUAR_BUY = 0.3
_LUAR_MIN_INTENSITY = 40.0


def _external_sentiment_delta(luar: dict | None) -> float:
    if not isinstance(luar, dict):
        return 0.0
    try:
        intensity = float(luar.get("intensity") or 0)
    except (TypeError, ValueError):
        return 0.0
    if intensity < _LUAR_MIN_INTENSITY:
        return 0.0
    status = luar.get("status")
    if status == "tekanan_luar":
        return -_LUAR_SELL
    if status == "dukungan_luar":
        return _LUAR_BUY
    return 0.0


def reconcile_vetoes(base: str, decision_engine: dict, market_regime: str | None) -> list[str]:
    """Veto Risk Moderator agar Musyawarah konsisten dengan Decision Engine & regime IHSG."""
    out: list[str] = []
    if base != "BUY" or not decision_engine:
        return out
    if decision_engine.get("no_trade"):
        why = "; ".join((decision_engine.get("no_trade_reasons") or [])[:2]) or "filter risiko"
        out.append(f"Decision Engine: NO TRADE ({why}).")
    elif decision_engine.get("direction") in ("SELL", "HOLD (REDUCE)"):
        out.append(f"Decision Engine menilai {decision_engine['direction']} (konflik dengan BUY).")
    if market_regime == "downtrend":
        out.append("Regime IHSG downtrend -> tahan BUY.")
    return out


def _agent_weights(fund_has_financials: bool) -> dict:
    """Bobot konsensus Musyawarah, dengan agen fundamental dinormalisasi ulang.

    Saat rasio fundamental benar-benar absen (``has_financials=False``),
    ``fund_vote`` selalu 0 sehingga bobot 15% fundamental hanya mendilusi
    konsensus ke arah netral tanpa informasi. Agen itu dikeluarkan lalu bobot
    tersisa direnormalisasi agar total tetap 1 (deterministik, urutan tetap).
    Agen fundamental dengan data ada (meski verdict Wajar/Sedang -> vote 0)
    TIDAK dikeluarkan. Ini tidak menyentuh rumus skor/vote apa pun.
    """
    weights = {"technical": 0.40, "bandarmologi": 0.30, "fundamental": 0.15, "sentiment": 0.15}
    if not fund_has_financials:
        weights.pop("fundamental", None)
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
    return weights


def musyawarah(ticker: str, use_llm: bool = False) -> dict:
    ticker = ticker.upper().strip()
    df = data.get_ohlcv(ticker)
    quote = data.get_quote(ticker)
    df, live = data.apply_live_quote(df, quote, "1d")
    a = analyze(df, ticker)
    if live:
        a.price = live["price"]
    d = add_indicators(df)
    last = d.iloc[-1]

    # --- Perspective 1: Technical ---
    breakout = a.entry_breakout and a.price >= a.entry_breakout * 0.997
    tech_bias = "BULLISH" if a.signal in ("BUY", "STRONG BUY") else (
        "BEARISH" if a.signal in ("SELL", "AVOID") else "NETRAL")
    technical = {
        "trend": a.trend,
        "bias": tech_bias,
        "summary": (f"Tren {a.trend} (W:{a.weekly_trend}, M:{a.monthly_trend}), regime {a.regime}. "
                    f"RSI {a.rsi:.0f}, ADX {a.adx:.0f}, MACD hist {a.macd_hist:.2f}. "
                    f"Support {_fmt(a.support)} / Resistance {_fmt(a.resistance)}. "
                    f"Skor {a.score} (grade {a.grade}); sinyal {a.signal}."),
    }

    # --- Perspective 2: Bandarmologi ---
    bandar = _bandarmologi(d, last)
    bandar_summary = (f"Status {bandar['status']} (skor {bandar['score']}): CMF {bandar['cmf']}, "
                      f"MFI {bandar['mfi']}, rasio volume naik/turun {bandar['updown_ratio']}, "
                      f"OBV {'di atas' if bandar['obv_up'] else 'di bawah'} MA20. {bandar['note']}")

    # --- Perspective 3: Fundamental ---
    try:
        f = fundamentals.get_fundamentals(ticker)
    except Exception:
        f = {}
    fund = _fundamental(f)
    fund_available = bool(f.get("available"))
    fund_has_financials = bool(f.get("has_financials"))
    tech_fund_alignment = _fund_tech_alignment(tech_bias, fund, fund_available)
    fund_summary = (f"{fund['category']}. {fund['valuation']}. {fund.get('valuation_note') or ''} "
                    f"(PER {f.get('pe') if f.get('pe') is not None else '-'}, "
                    f"PBV {f.get('pb') if f.get('pb') is not None else '-'}, "
                    f"ROE {round((f.get('roe') or 0)*100,1)}%, DER {f.get('der') if f.get('der') is not None else '-'}).")

    # --- Perspective 4: Macro & Sentiment ---
    try:
        nw = news.get_news(ticker)
    except Exception:
        nw = {"label": "Netral", "avg_sentiment": 0, "count": 0}
    try:
        mk = market.ihsg()
    except Exception:
        mk = {}
    sent = {
        "label": nw.get("label"),
        "avg": nw.get("avg_sentiment"),
        "count": nw.get("count", 0),
        "ihsg_regime": mk.get("regime"),
    }
    sentiment_summary = (f"Sentimen berita {nw.get('label')} (skor {nw.get('avg_sentiment')}, "
                         f"{nw.get('count', 0)} berita). IHSG {mk.get('regime', 'n/a')} "
                         f"(1D {round(mk.get('ret_1d', 0), 2)}%, 20D {round(mk.get('ret_20d', 0), 2)}%).")
    # Tekanan luar yang terkonfirmasi menggeser vote sentimen dan menahan BUY.
    # Waspada tanpa gejolak IHSG tetap penjelasan saja.
    try:
        luar = external.for_stock(
            ticker,
            change_1d=getattr(a, "change_1d", None),
            rs_change=getattr(a, "rs_change", None),
            extra_items=list(nw.get("items") or []),
            our_signal=getattr(a, "signal", None),
        )
    except Exception:
        luar = {"status": "tidak_tersedia", "label": "Belum bisa dinilai",
                "summary": "Tekanan luar belum bisa dinilai.", "drivers": []}
    cmp = luar.get("x_compare") if isinstance(luar.get("x_compare"), dict) else {}
    luar_bits = []
    if cmp.get("note"):
        luar_bits.append(f"Komparasi X: {cmp.get('alignment')}. {cmp.get('note')}")
    luar_bits.append(luar.get("summary") or "Tekanan luar belum bisa dinilai.")
    luar_summary = " ".join(luar_bits)

    # --- ML probability (quant input) ---
    ml_prob = None
    ml_base = None
    ml_acc = None
    ml_error = None
    try:
        pred = ml.predict(df, ticker, horizon=settings.swing_horizon_days)
        ml_prob = float(pred["current_prob_up"])
        ml_base = pred.get("base_rate")
        ml_acc = pred.get("test_accuracy")
    except Exception as exc:
        ml_error = str(exc)[:160]

    # --- Agent votes (-1..+1) + weighted consensus ---
    sig_vote = 1.0 if a.signal in ("BUY", "STRONG BUY") else (
        -1.0 if a.signal in ("SELL", "AVOID") else 0.0)
    tech_vote = sig_vote * 0.6 + ((2.0 * ml_prob - 1.0) * 0.4 if ml_prob is not None else 0.0)

    bandar_vote = {"AKUMULASI": 1.0, "Akumulasi ringan": 0.5, "Netral": 0.0,
                   "Distribusi": -0.5, "DISTRIBUSI MASIF": -1.0}.get(bandar["status"], 0.0)

    fund_vote = 0.0
    if fund.get("quality_code") == "baik":
        fund_vote += 0.5
    if fund.get("quality_code") == "rugi":
        fund_vote -= 0.7
    if fund.get("valuation_code") == "rendah":
        fund_vote += 0.5
    elif fund.get("valuation_code") == "tinggi":
        fund_vote -= 0.3
    fund_vote = max(-1.0, min(1.0, fund_vote))

    sent_vote = {"Positif": 1.0, "Negatif": -1.0, "Netral": 0.0}.get(sent.get("label"), 0.0)
    if sent.get("ihsg_regime") == "Bullish":
        sent_vote = min(1.0, sent_vote + 0.3)
    elif sent.get("ihsg_regime") == "Bearish":
        sent_vote = max(-1.0, sent_vote - 0.3)
    luar_delta = _external_sentiment_delta(luar)
    sent_vote = max(-1.0, min(1.0, sent_vote + luar_delta))

    weights = _agent_weights(fund_has_financials)
    votes = {
        "technical": round(tech_vote, 2),
        "bandarmologi": round(bandar_vote, 2),
        "fundamental": round(fund_vote, 2),
        "sentiment": round(sent_vote, 2),
    }
    consensus = round(sum(weights[k] * votes[k] for k in weights), 3)
    conviction = int(round(abs(consensus) * 100))

    # --- Perspective 5: Risk Manager & Moderator ---
    rr = float(a.rr2) if a.rr2 else 0.0
    vetoes: list[str] = []
    if tech_vote > 0.3 and bandar["status"] == "DISTRIBUSI MASIF":
        vetoes.append("Teknikal BUY namun bandarmologi DISTRIBUSI MASIF -> wajib VETO.")
    if rr < 2.0:
        vetoes.append(f"RRR 1:{rr:.1f} < 1:2 -> wajib VETO (ubah ke WAIT).")

    base = "BUY" if (consensus >= 0.35 and tech_vote > 0) else (
        "SKIP" if consensus <= -0.35 else "WAIT")

    # Rekonsiliasi dengan Decision Engine (Market Decision) & regime IHSG.
    dec = getattr(a, "decision", {}) or {}
    mkt_regime = getattr(a, "market_regime", None)
    vetoes.extend(reconcile_vetoes(base, dec, mkt_regime))
    if luar_delta < 0:
        vetoes.append(
            f"Tekanan luar terkonfirmasi ({luar.get('label') or 'tekanan luar'}) -> tahan BUY."
        )

    decision = ("SKIP" if base == "SKIP" else "WAIT") if vetoes else base

    entry = a.buy_zone_high or a.entry
    target = a.tp2
    sl = a.stop_loss

    if vetoes:
        synthesis = "Moderator VETO: " + " ".join(vetoes)
    else:
        synthesis = (f"Konsensus agen {consensus:+.2f} (conviction {conviction}%). "
                     f"Selaras, tanpa veto.")

    if decision == "BUY":
        reason = (f"Konsensus {consensus:+.2f} / conviction {conviction}% didukung tren {a.trend}, "
                  f"skor {a.score} (grade {a.grade}), dan {bandar['status'].lower()}. RRR 1:{rr:.1f}.")
    elif decision == "WAIT":
        reason = (("Menunggu konfirmasi: " + " ".join(vetoes)) if vetoes
                  else f"Konsensus moderat ({consensus:+.2f}); belum cukup kuat untuk entry.")
    else:
        reason = f"Konsensus negatif ({consensus:+.2f}); hindari hingga struktur membaik."

    ml_line = (f"• @ml_model    : Probabilitas naik {round(ml_prob * 100, 1)}% "
               f"(model logistic, out-of-sample).\n") if ml_prob is not None else ""

    order = ("technical", "bandarmologi", "fundamental", "sentiment")
    weights_used = {k: round(weights[k], 4) for k in order if k in weights}
    vote_line = " | ".join(f"{k} {votes[k]:+.2f}" for k in order if k in weights)
    weight_line = "/".join(str(int(round(weights[k] * 100))) for k in order if k in weights)
    fund_note = "" if fund_has_financials else " [fundamental dikecualikan: rasio tidak tersedia]"

    text = (
        "===================================================\n"
        f"      HASIL MUSYAWARAH AGENT SAHAM: {ticker}\n"
        "===================================================\n\n"
        "[1. PERDEBATAN & PANDANGAN PARALEL]\n"
        f"• @technical    : {technical['summary']}\n"
        f"• @bandarmologi : {bandar_summary}\n"
        f"• @fundamental  : {fund_summary}\n"
        f"• @sentiment    : {sentiment_summary}\n"
        f"• @luar         : {luar_summary}\n"
        + ml_line +
        "\n[2. CATATAN VETO & SINTESIS MODERATOR]\n"
        f"• {synthesis}\n"
        f"• Voting: {vote_line} "
        f"(bobot {weight_line}) -> konsensus {consensus:+.3f}{fund_note}\n\n"
        "[3. KEPUTUSAN FINAL]\n"
        f"• DECISION     : {decision}\n"
        f"• ENTRY AREA   : Rp {_fmt(entry)}\n"
        f"• TARGET PRICE : Rp {_fmt(target)}\n"
        f"• STOP LOSS    : Rp {_fmt(sl)}\n"
        f"• RISK/REWARD  : 1:{rr:.1f}\n"
        f"• CONVICTION   : {conviction}%\n\n"
        "[4. ALASAN UTAMA & MITIGASI RISIKO]\n"
        f"• {reason} Entry bertahap di area beli, disiplin stop loss, ukuran posisi sesuai risiko.\n"
        "==================================================="
    )

    context = {
        "ticker": ticker,
        "harga": a.price,
        "technical": {"tren": a.trend, "weekly": a.weekly_trend, "monthly": a.monthly_trend,
                      "signal": a.signal, "skor": a.score, "grade": a.grade, "rsi": a.rsi,
                      "adx": a.adx, "support": a.support, "resistance": a.resistance},
        "bandarmologi": bandar,
        "fundamental": fund,
        "fund_tech_alignment": tech_fund_alignment,
        "sentiment": sent,
        "external": luar,
        "ml_prob_up": ml_prob,
        "votes": votes,
        "weights_used": weights_used,
        "fundamental_available": fund_available,
        "has_financials": fund_has_financials,
        "consensus": consensus,
        "conviction": conviction,
        "vetoes": vetoes,
        "decision": decision,
        "decision_engine": {
            "direction": dec.get("direction"),
            "no_trade": dec.get("no_trade"),
            "reasons": (dec.get("no_trade_reasons") or []) + (dec.get("reasons") or [])[:3],
            "market_regime": mkt_regime,
        },
        "entry": entry, "target": target, "stop_loss": sl, "rr": rr,
    }

    engine = "deterministic"
    if use_llm:
        try:
            system = llm.load_prompt()
            user = ("Analisis saham berikut memakai data terstruktur ini apa adanya. "
                    "Balas dengan format HASIL MUSYAWARAH yang sudah ditentukan.\n\n"
                    + json.dumps(context, ensure_ascii=False, indent=2))
            text = llm.chat(system, user)
            engine = "llm (" + (llm._model()) + ")"
        except Exception as exc:
            engine = "deterministic (llm gagal: " + str(exc) + ")"

    return {
        "ticker": ticker,
        "price": a.price,
        "decision": decision,
        "entry": entry,
        "target": target,
        "stop_loss": sl,
        "rr": round(rr, 2),
        "conviction": conviction,
        "consensus": consensus,
        "votes": votes,
        "weights_used": weights_used,
        "fundamental_available": fund_available,
        "has_financials": fund_has_financials,
        "ml_prob_up": ml_prob,
        "ml_base_rate": ml_base,
        "ml_test_accuracy": ml_acc,
        "ml_error": ml_error,
        "vetoes": vetoes,
        "engine": engine,
        "decision_engine": {
            "direction": dec.get("direction"),
            "no_trade": dec.get("no_trade"),
            "reasons": (dec.get("no_trade_reasons") or []) + (dec.get("reasons") or [])[:3],
            "market_regime": mkt_regime,
        },
        "perspectives": {
            "technical": {"bias": tech_bias, "text": technical["summary"]},
            "bandarmologi": {"status": bandar["status"], "text": bandar_summary},
            "fundamental": {"category": fund["category"], "text": fund_summary},
            "sentiment": {"label": sent.get("label"), "text": sentiment_summary},
            "external": {"status": luar.get("status"), "label": luar.get("label"),
                         "text": luar_summary},
        },
        "external": luar,
        "fund_tech_alignment": tech_fund_alignment,
        "synthesis": synthesis,
        "reason": reason,
        "text": text,
    }
