from __future__ import annotations

import json

import numpy as np

import data
import fundamentals
import llm
import market
import ml
import news
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

    if roe is not None and roe >= 0.15 and (der is None or der < 100):
        quality = "Kualitas Baik"
    elif roe is not None and roe < 0:
        quality = "Rugi"
    else:
        quality = "Kualitas Sedang"

    if pe is None:
        val = "Valuasi n/a"
    elif pe < 12:
        val = "Valuasi Murah"
    elif pe < 22:
        val = "Valuasi Wajar"
    else:
        val = "Valuasi Mahal"

    return {
        "category": f"{cap} · {quality}",
        "valuation": val,
        "pe": pe, "pb": pb, "roe": roe, "der": der,
        "dividend_yield": f.get("dividend_yield"),
        "name": f.get("name"),
    }


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
    fund_summary = (f"{fund['category']}. {fund['valuation']} "
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

    # --- ML probability (quant input) ---
    ml_prob = None
    try:
        ml_prob = float(ml.predict(df, ticker, horizon=10)["current_prob_up"])
    except Exception:
        ml_prob = None

    # --- Agent votes (-1..+1) + weighted consensus ---
    sig_vote = 1.0 if a.signal in ("BUY", "STRONG BUY") else (
        -1.0 if a.signal in ("SELL", "AVOID") else 0.0)
    tech_vote = sig_vote * 0.6 + ((2.0 * ml_prob - 1.0) * 0.4 if ml_prob is not None else 0.0)

    bandar_vote = {"AKUMULASI": 1.0, "Akumulasi ringan": 0.5, "Netral": 0.0,
                   "Distribusi": -0.5, "DISTRIBUSI MASIF": -1.0}.get(bandar["status"], 0.0)

    fund_vote = 0.0
    if "Kualitas Baik" in fund["category"]:
        fund_vote += 0.5
    if "Rugi" in fund["category"]:
        fund_vote -= 0.7
    if "Murah" in fund["valuation"]:
        fund_vote += 0.5
    elif "Mahal" in fund["valuation"]:
        fund_vote -= 0.3
    fund_vote = max(-1.0, min(1.0, fund_vote))

    sent_vote = {"Positif": 1.0, "Negatif": -1.0, "Netral": 0.0}.get(sent.get("label"), 0.0)
    if sent.get("ihsg_regime") == "Bullish":
        sent_vote = min(1.0, sent_vote + 0.3)
    elif sent.get("ihsg_regime") == "Bearish":
        sent_vote = max(-1.0, sent_vote - 0.3)

    weights = {"technical": 0.40, "bandarmologi": 0.30, "fundamental": 0.15, "sentiment": 0.15}
    votes = {
        "technical": round(tech_vote, 2),
        "bandarmologi": round(bandar_vote, 2),
        "fundamental": round(fund_vote, 2),
        "sentiment": round(sent_vote, 2),
    }
    consensus = round(sum(weights[k] * votes[k] for k in votes), 3)
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

    text = (
        "===================================================\n"
        f"      HASIL MUSYAWARAH AGENT SAHAM: {ticker}\n"
        "===================================================\n\n"
        "[1. PERDEBATAN & PANDANGAN PARALEL]\n"
        f"• @technical    : {technical['summary']}\n"
        f"• @bandarmologi : {bandar_summary}\n"
        f"• @fundamental  : {fund_summary}\n"
        f"• @sentiment    : {sentiment_summary}\n"
        + ml_line +
        "\n[2. CATATAN VETO & SINTESIS MODERATOR]\n"
        f"• {synthesis}\n"
        f"• Voting: technical {votes['technical']:+.2f} | bandarmologi {votes['bandarmologi']:+.2f} | "
        f"fundamental {votes['fundamental']:+.2f} | sentiment {votes['sentiment']:+.2f} "
        f"(bobot 40/30/15/15) -> konsensus {consensus:+.3f}\n\n"
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
        "sentiment": sent,
        "ml_prob_up": ml_prob,
        "votes": votes,
        "consensus": consensus,
        "conviction": conviction,
        "vetoes": vetoes,
        "decision": decision,
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
        "ml_prob_up": ml_prob,
        "vetoes": vetoes,
        "engine": engine,
        "perspectives": {
            "technical": {"bias": tech_bias, "text": technical["summary"]},
            "bandarmologi": {"status": bandar["status"], "text": bandar_summary},
            "fundamental": {"category": fund["category"], "text": fund_summary},
            "sentiment": {"label": sent.get("label"), "text": sentiment_summary},
        },
        "synthesis": synthesis,
        "reason": reason,
        "text": text,
    }
