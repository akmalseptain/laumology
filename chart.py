from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from indicators import add_indicators
from signals import Analysis

UP = "#26a69a"
DOWN = "#ef5350"


def _candles(ax, d: pd.DataFrame, width: float = 0.6) -> None:
    for i, (_, row) in enumerate(d.iterrows()):
        up = row["Close"] >= row["Open"]
        color = UP if up else DOWN
        ax.vlines(i, row["Low"], row["High"], color=color, linewidth=0.7, zorder=3)
        bottom = min(row["Open"], row["Close"])
        height = abs(row["Close"] - row["Open"])
        if height == 0:
            height = (row["High"] - row["Low"]) * 0.02 or 1e-9
        ax.add_patch(
            Rectangle((i - width / 2, bottom), width, height, facecolor=color, edgecolor=color, zorder=4)
        )


def _build_figure(df: pd.DataFrame, analysis: Analysis, bars: int = 150):
    d = add_indicators(df).tail(bars).reset_index(drop=False)
    d = d.rename(columns={d.columns[0]: "Date"})
    x = np.arange(len(d))

    fig, axes = plt.subplots(
        5, 1, figsize=(16, 15), sharex=True,
        gridspec_kw={"height_ratios": [4.2, 1, 1, 1, 1], "hspace": 0.06},
    )
    ax, axv, axr, axm, axa = axes

    cloud_a = d["senkou_a"].to_numpy(dtype=float)
    cloud_b = d["senkou_b"].to_numpy(dtype=float)
    ax.fill_between(x, cloud_a, cloud_b, where=cloud_a >= cloud_b, color="#26a69a", alpha=0.12, zorder=1, label="Cloud")
    ax.fill_between(x, cloud_a, cloud_b, where=cloud_a < cloud_b, color="#ef5350", alpha=0.12, zorder=1)

    _candles(ax, d)
    ax.plot(x, d["ma20"], color="#f39c12", lw=1.0, label="MA20")
    ax.plot(x, d["ma50"], color="#42a5f5", lw=1.0, label="MA50")
    ax.plot(x, d["ma200"], color="#ab47bc", lw=1.4, label="MA200")
    ax.plot(x, d["ema21"], color="#26c6da", lw=0.9, ls="--", label="EMA21")

    st = d["st_dir"].to_numpy(dtype=int)
    stl = d["supertrend"].to_numpy(dtype=float)
    ax.plot(x, np.where(st == 1, stl, np.nan), color=UP, lw=1.6, label="Supertrend")
    ax.plot(x, np.where(st == -1, stl, np.nan), color=DOWN, lw=1.6)

    for level, color, label in [
        (analysis.entry, "#2962ff", "ENTRY"),
        (analysis.stop_loss, "#d50000", "SL"),
        (analysis.tp1, "#00c853", "TP1"),
        (analysis.tp2, "#00a03a", "TP2"),
        (analysis.tp3, "#00701f", "TP3"),
    ]:
        ax.axhline(level, color=color, lw=1.1, ls=":", alpha=0.95)
        ax.text(len(d) - 0.5, level, f" {label} {level:,.0f}", fontsize=8, color=color, va="center")

    ax.scatter([len(d) - 1], [analysis.price], marker="o", s=55, color="#2962ff", zorder=6)
    ax.annotate(
        f"{analysis.signal}\n{analysis.action}",
        xy=(len(d) - 1, analysis.price),
        xytext=(len(d) - 1, analysis.price * 1.04),
        fontsize=9, fontweight="bold", color="white", ha="right",
        bbox=dict(boxstyle="round,pad=0.4", fc="#111111", ec=color_for(analysis.signal), lw=1.4),
        arrowprops=dict(arrowstyle="->", color=color_for(analysis.signal)),
    )

    ax.set_title(
        f"{analysis.ticker}   {analysis.signal} / {analysis.action}   |   "
        f"Score {analysis.score}  Conf {analysis.confidence}%  Grade {analysis.grade}   |   "
        f"{analysis.trend}  Regime {analysis.regime}   |   RSI {analysis.rsi:.0f}  ADX {analysis.adx:.0f}",
        fontsize=12, fontweight="bold",
    )
    ax.legend(loc="upper left", fontsize=7.5, ncol=6)
    ax.grid(alpha=0.18)
    ax.set_ylabel("Harga")

    colors = [UP if c >= o else DOWN for o, c in zip(d["Open"], d["Close"])]
    axv.bar(x, d["Volume"], color=colors, width=0.6)
    axv.plot(x, d["vol_ma20"], color="#888", lw=0.9, label="VolMA20")
    axv.legend(loc="upper left", fontsize=7)
    axv.grid(alpha=0.18)
    axv.set_ylabel("Vol")

    axr.plot(x, d["rsi"], color="#ab47bc", lw=1.2, label="RSI")
    axr.plot(x, d["stoch_k"], color="#26c6da", lw=0.8, alpha=0.7, label="Stoch")
    axr.axhline(70, color=DOWN, ls="--", lw=0.7)
    axr.axhline(30, color=UP, ls="--", lw=0.7)
    axr.axhline(50, color="#666", ls=":", lw=0.6)
    axr.fill_between(x, 30, 70, color="#ab47bc", alpha=0.05)
    axr.set_ylim(0, 100)
    axr.legend(loc="upper left", fontsize=7, ncol=2)
    axr.grid(alpha=0.18)
    axr.set_ylabel("RSI")

    axm.bar(x, d["macd_hist"], color=np.where(d["macd_hist"] >= 0, UP, DOWN), width=0.6, alpha=0.6)
    axm.plot(x, d["macd"], color="#2962ff", lw=1.0, label="MACD")
    axm.plot(x, d["macd_signal"], color="#f39c12", lw=1.0, label="Signal")
    axm.axhline(0, color="#666", lw=0.6)
    axm.legend(loc="upper left", fontsize=7, ncol=2)
    axm.grid(alpha=0.18)
    axm.set_ylabel("MACD")

    axa.plot(x, d["adx"], color="#ffffff", lw=1.3, label="ADX")
    axa.plot(x, d["plus_di"], color=UP, lw=0.9, label="+DI")
    axa.plot(x, d["minus_di"], color=DOWN, lw=0.9, label="-DI")
    axa.axhline(25, color="#f39c12", ls="--", lw=0.7)
    axa.axhline(20, color="#666", ls=":", lw=0.6)
    axa.legend(loc="upper left", fontsize=7, ncol=3)
    axa.grid(alpha=0.18)
    axa.set_ylabel("ADX")

    step = max(len(d) // 10, 1)
    ticks = list(range(0, len(d), step))
    axa.set_xticks(ticks)
    axa.set_xticklabels(
        [pd.Timestamp(d["Date"].iloc[i]).strftime("%d-%b") for i in ticks],
        rotation=45, ha="right", fontsize=8,
    )

    fig.subplots_adjust(left=0.05, right=0.985, top=0.955, bottom=0.055, hspace=0.06)
    return fig


def color_for(signal: str) -> str:
    if signal in ("STRONG BUY", "BUY"):
        return UP
    if signal in ("SELL", "AVOID"):
        return DOWN
    return "#f39c12"


def plot_analysis(
    df: pd.DataFrame, analysis: Analysis, bars: int = 150, out_dir: str | Path = "output"
) -> str:
    fig = _build_figure(df, analysis, bars)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{analysis.ticker}_analysis.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return str(path)


def render_png_b64(df: pd.DataFrame, analysis: Analysis, bars: int = 150) -> str:
    import base64
    from io import BytesIO

    fig = _build_figure(df, analysis, bars)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
