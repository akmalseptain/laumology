"""Stock Intelligence Layer (additive di atas core engine).

Fitur khusus equity: kualitas data, likuiditas/execution quality, gap, price-limit (ARB),
session awareness, konteks sektor, dan dekomposisi skor (market/sector/technical/RS/liquidity/risk).

Tidak mengubah indikator/decision core; hanya memperkaya & memberi konteks.
Semua dari data yang tersedia. Yang tidak tersedia -> "UNKNOWN" (tidak dikarang).
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

# Cache peta kekuatan sektor (diisi oleh market.sector_strength / endpoint).
_SECTOR_CACHE: dict = {"ts": 0.0, "map": {}}
_SECTOR_TTL = 1800.0


def set_sector_map(m: dict) -> None:
    _SECTOR_CACHE.update(ts=time.time(), map=m or {})


def sector_context(sector: str | None) -> dict:
    if not sector:
        return {"name": None, "regime": "UNKNOWN", "chg_20d": None, "breadth": None}
    m = _SECTOR_CACHE["map"].get(sector)
    if not m:
        return {"name": sector, "regime": "UNKNOWN", "chg_20d": None, "breadth": None}
    chg = m.get("chg_20d")
    regime = "Bullish" if (chg or 0) > 2.0 else ("Bearish" if (chg or 0) < -2.0 else "Neutral")
    return {"name": sector, "regime": regime, "chg_20d": chg, "breadth": m.get("breadth")}


# --- Data quality ---
def data_quality(d: pd.DataFrame) -> dict:
    import validate

    q = validate.quality_score(d)
    n = len(d)
    dup = int(d.index.duplicated().sum())
    bad_hl = int((d["High"] < d["Low"]).sum())
    last = pd.Timestamp(d.index[-1])
    try:
        lag_days = int((pd.Timestamp.now().normalize() - last.normalize()).days)
    except Exception:
        lag_days = 0
    return {"score": q["score"], "status": q["status"], "n_bars": int(n),
            "duplicates": dup, "hl_violations": bad_hl, "lag_days": lag_days,
            "issues": q.get("issues", [])}


# --- Liquidity / execution quality (IDX: nilai transaksi Rp) ---
def liquidity(d: pd.DataFrame) -> dict:
    val = (d["Close"] * d["Volume"]).rolling(20, min_periods=5).mean()
    avg_value = float(val.iloc[-1]) if len(val) and np.isfinite(val.iloc[-1]) else 0.0
    avg_vol = float(d["Volume"].tail(20).mean()) if len(d) else 0.0
    recent = val.tail(20).dropna()
    consistency = float((recent > 0).mean()) if len(recent) else 0.0
    if avg_value >= 10e9:
        status = "GOOD"
    elif avg_value >= 1e9:
        status = "OK"
    else:
        status = "LOW"
    return {"avg_value_20d": round(avg_value, 0), "avg_volume_20d": round(avg_vol, 0),
            "consistency": round(consistency, 2), "status": status}


# --- Gap ---
def gap(d: pd.DataFrame) -> dict:
    if len(d) < 2:
        return {"gap_pct": 0.0, "type": "none", "extreme": False}
    o = float(d["Open"].iloc[-1])
    pc = float(d["Close"].iloc[-2])
    g = (o - pc) / pc * 100.0 if pc else 0.0
    typ = "none"
    if g >= 0.5:
        typ = "up"
    elif g <= -0.5:
        typ = "down"
    return {"gap_pct": round(g, 2), "type": typ, "extreme": abs(g) >= 7.0}


# --- Price limit (ARB) awareness — aproksimasi IDX ---
def price_limit_pct(price: float) -> float:
    if price <= 0:
        return 7.0
    if price < 200:
        return 35.0
    if price <= 5000:
        return 7.0
    return 13.0


def tp_realism(price: float, tp: float, adr_pct: float) -> dict:
    """Perkiraan berapa hari & apakah TP terjangkau mengingat ARB + ADR."""
    if not price or not tp or tp <= price:
        return {"ok": True, "days_arb": None, "note": None}
    need_pct = (tp - price) / price * 100.0
    arb = price_limit_pct(price)
    days_arb = need_pct / arb if arb else None
    days_adr = (need_pct / adr_pct) if adr_pct else None
    note = None
    ok = True
    if days_arb and days_arb > 5:
        ok = False
        note = f"TP butuh ~{days_arb:.0f} hari di batas ARB (agresif)"
    elif days_adr and days_adr > 4:
        note = f"TP ~{days_adr:.0f}x ADR (butuh waktu)"
    return {"ok": ok, "days_arb": (round(days_arb, 1) if days_arb else None),
            "days_adr": (round(days_adr, 1) if days_adr else None), "note": note}


# --- Session awareness (WIB) ---
def market_session(now: time.struct_time | None = None) -> str:
    import datetime as _dt
    try:
        wib = _dt.datetime.now(_dt.timezone.utc).astimezone(_dt.timezone(_dt.timedelta(hours=7)))
    except Exception:
        return "UNKNOWN"
    if wib.weekday() >= 5:
        return "CLOSED"
    minutes = wib.hour * 60 + wib.minute
    if minutes < 9 * 60:
        return "PRE_OPEN"
    if 9 * 60 <= minutes < 9 * 60 + 30:
        return "OPENING"
    if minutes < 12 * 60:
        return "MORNING"
    if minutes < 13 * 60 + 30:
        return "BREAK"
    if minutes < 15 * 60 + 50:
        return "AFTERNOON"
    return "CLOSED"


# --- Score decomposition ---
def _band(v: float, lo: float, hi: float) -> int:
    x = max(lo, min(hi, v))
    return int(round((x - lo) / (hi - lo) * 100.0))


def build_scores(decision: dict, sector: dict, liq: dict, dataq: dict,
                 rs_change: float | None, rs_strong: bool | None) -> dict:
    tech = int(decision.get("signal_score", 50))
    market = {"uptrend": 90, "ranging": 55, "downtrend": 25, "unknown": 50}.get(
        decision.get("market", "unknown"), 50)
    sec = {"Bullish": 85, "Neutral": 55, "Bearish": 25, "UNKNOWN": 50}.get(sector.get("regime"), 50)
    if rs_change is None:
        rs = 50
    else:
        rs = _band(rs_change, -15.0, 15.0)
        if rs_strong:
            rs = min(100, rs + 8)
    liq_score = {"GOOD": 90, "OK": 65, "LOW": 30}.get(liq.get("status"), 50)
    conf = int(decision.get("confidence", 50))
    risk = 100 - conf if decision.get("no_trade") else max(20, 100 - conf // 2)
    return {"market": market, "sector": sec, "technical": tech,
            "relative_strength": rs, "liquidity": liq_score, "risk": risk,
            "data_quality": dataq.get("status", "UNKNOWN")}


def evaluate_stock(d: pd.DataFrame, ticker: str, decision: dict, sector_name: str | None = None,
                   rs_change: float | None = None, rs_strong: bool | None = None) -> dict:
    """Rangkum -> STOCK DECISION (context + skor + risk factors). Tanpa mengubah decision core."""
    dataq = data_quality(d)
    liq = liquidity(d)
    gp = gap(d)
    sec = sector_context(sector_name)
    last = float(d["Close"].iloc[-1])
    adr = 0.0
    try:
        adr = float(d["adr_pct"].iloc[-1])
    except Exception:
        pass
    tpr = tp_realism(last, decision.get("tp3"), adr) if decision.get("tp3") else {"ok": True, "note": None}

    scores = build_scores(decision, sec, liq, dataq, rs_change, rs_strong)

    risk_factors: list[str] = []
    if dataq["status"] != "GOOD":
        risk_factors.append("Kualitas data: " + dataq["status"])
    if liq["status"] == "LOW":
        risk_factors.append("Likuiditas rendah (execution risk)")
    if gp["extreme"]:
        risk_factors.append(f"Gap ekstrem {gp['gap_pct']}%")
    if tpr.get("note"):
        risk_factors.append(tpr["note"])
    if sec.get("regime") == "Bearish":
        risk_factors.append("Sektor bearish (counter-sector)")
    if (rs_change is not None) and rs_change < 0:
        risk_factors.append("Relative strength negatif vs IHSG")

    strength = "Strong" if scores["technical"] >= 70 else ("Moderate" if scores["technical"] >= 50 else "Weak")

    return {
        "ticker": ticker.upper(),
        "data_quality": dataq,
        "liquidity": liq,
        "gap": gp,
        "sector": sec,
        "tp_realism": tpr,
        "session": market_session(),
        "scores": scores,
        "signal_strength": strength,
        "risk_factors": risk_factors,
    }
