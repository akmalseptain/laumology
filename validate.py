from __future__ import annotations

import numpy as np
import pandas as pd

import data


def check_df(df: pd.DataFrame, max_stale_days: int = 7) -> dict:
    hard: list[str] = []
    soft: list[str] = []
    if df is None or df.empty:
        return {"ok": False, "rows": 0, "issues": ["Data kosong"]}

    need = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        hard.append("Kolom hilang: " + ", ".join(missing))

    if not missing:
        o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
        if (df[["Open", "High", "Low", "Close"]] <= 0).any().any():
            hard.append("Ada harga <= 0")
        zero_vol = int((df["Volume"] <= 0).sum())
        if zero_vol:
            soft.append(f"{zero_vol} bar volume 0 (hari tanpa transaksi)")
        bad_hl = int((h < l).sum())
        if bad_hl:
            hard.append(f"High<Low pada {bad_hl} bar")
        bad_range = int(((h < np.maximum(o, c)) | (l > np.minimum(o, c))).sum())
        if bad_range:
            hard.append(f"High/Low tidak konsisten pada {bad_range} bar")

    if df.index.duplicated().any():
        hard.append("Index tanggal duplikat")
    if not df.index.is_monotonic_increasing:
        hard.append("Index tidak terurut")

    stale = 0
    try:
        stale = int((pd.Timestamp.now().normalize() - pd.Timestamp(df.index[-1]).normalize()).days)
    except Exception:
        stale = 0
    if stale > max_stale_days:
        soft.append(f"Data basi {stale} hari")

    rows = len(df)
    if rows < 200:
        soft.append(f"Riwayat pendek ({rows} bar)")

    return {"ok": not hard, "rows": int(rows), "last": str(df.index[-1])[:10],
            "stale_days": stale, "issues": hard + soft, "errors": hard, "warnings": soft}


def quality_score(df: pd.DataFrame, max_stale_days: int = 7) -> dict:
    """Skor kualitas data 0-100 + status, dari check_df (additive, tidak mengubah legacy)."""
    r = check_df(df, max_stale_days=max_stale_days)
    score = 100.0
    score -= 30.0 * len(r.get("errors", []))
    score -= 6.0 * len(r.get("warnings", []))
    rows = int(r.get("rows", 0))
    if rows < 60:
        score -= 34.0
    elif rows < 120:
        score -= 12.0
    score = max(0.0, min(100.0, score))
    if not r.get("ok") or score < 50:
        status = "INSUFFICIENT"
    elif score < 80:
        status = "WARNING"
    else:
        status = "GOOD"
    return {"score": int(round(score)), "status": status, "rows": rows,
            "issues": r.get("issues", []), "errors": r.get("errors", []),
            "warnings": r.get("warnings", [])}


def data_quality(tickers: list[str]) -> dict:
    items = []
    for t in tickers:
        try:
            r = check_df(data.get_ohlcv(t))
            r["ticker"] = t.upper()
            items.append(r)
        except Exception as exc:
            items.append({"ticker": t.upper(), "ok": False, "rows": 0, "issues": [str(exc)]})
    ok = sum(1 for x in items if x["ok"])
    return {"total": len(items), "ok": ok, "bad": len(items) - ok, "items": items}
