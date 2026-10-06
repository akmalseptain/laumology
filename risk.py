from __future__ import annotations

import numpy as np
import pandas as pd

import data
from config import sector_of, settings


def position_size(capital: float, risk_pct: float, entry: float, stop: float, lot: int = 100) -> dict:
    risk_amount = capital * risk_pct / 100.0
    per_share = max(entry - stop, 0.0)
    per_lot = per_share * lot
    lots = int(risk_amount // per_lot) if per_lot > 0 else 0
    value = lots * lot * entry
    return {
        "risk_amount": risk_amount,
        "risk_per_share": per_share,
        "lots": lots,
        "shares": lots * lot,
        "position_value": value,
        "max_loss": lots * per_lot,
        "exposure_pct": (value / capital * 100.0) if capital else 0.0,
    }


def correlation(tickers: list[str], lookback: int = 120) -> dict:
    series = {}
    for t in tickers:
        try:
            df = data.get_ohlcv(t)
            series[t] = df["Close"].pct_change()
        except Exception:
            continue
    if len(series) < 2:
        return {"error": "Butuh minimal 2 saham dengan data cukup"}
    mat = pd.DataFrame(series).dropna().tail(lookback)
    if mat.empty:
        return {"error": "Data tidak cukup"}
    corr = mat.corr().round(2).fillna(0.0)
    return {
        "tickers": list(corr.columns),
        "matrix": corr.values.tolist(),
    }


def portfolio_risk(positions: list[dict], quotes: dict, capital: float) -> dict:
    total = 0.0
    rows = []
    for p in positions:
        q = quotes.get(p.get("ticker")) or p.get("entry") or 0.0
        val = float(q) * int(p.get("lots", 0)) * 100
        total += val
    sector_val: dict[str, float] = {}
    for p in positions:
        q = quotes.get(p.get("ticker")) or p.get("entry") or 0.0
        val = float(q) * int(p.get("lots", 0)) * 100
        entry = float(p.get("entry") or 0.0)
        pl = (float(q) - entry) * int(p.get("lots", 0)) * 100 if entry else 0.0
        rows.append({
            "ticker": p.get("ticker"),
            "value": round(val, 0),
            "weight_pct": round(val / total * 100.0, 1) if total else 0.0,
            "pl": round(pl, 0),
        })
        sec = sector_of(p.get("ticker") or "")
        sector_val[sec] = sector_val.get(sec, 0.0) + val

    sectors = []
    flags: list[str] = []
    for sec, v in sorted(sector_val.items(), key=lambda x: -x[1]):
        pct = v / total * 100.0 if total else 0.0
        sectors.append({"sector": sec, "value": round(v, 0), "weight_pct": round(pct, 1)})
        if pct > settings.max_sector_pct:
            flags.append(f"Konsentrasi sektor {sec} {pct:.0f}% > batas {settings.max_sector_pct:.0f}%")
    for r in rows:
        if r["weight_pct"] > settings.max_position_pct:
            flags.append(f"Posisi {r['ticker']} {r['weight_pct']}% > batas {settings.max_position_pct:.0f}%")
    if len(positions) > settings.max_positions:
        flags.append(f"Jumlah posisi {len(positions)} > batas {settings.max_positions}")

    return {
        "capital": capital,
        "total_value": round(total, 0),
        "exposure_pct": round(total / capital * 100.0, 1) if capital else 0.0,
        "cash_pct": round(max(capital - total, 0.0) / capital * 100.0, 1) if capital else 0.0,
        "rows": rows,
        "sectors": sectors,
        "flags": flags,
        "limits": {
            "max_positions": settings.max_positions,
            "max_sector_pct": settings.max_sector_pct,
            "max_position_pct": settings.max_position_pct,
        },
    }
