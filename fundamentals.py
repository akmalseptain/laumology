from __future__ import annotations

import time

import yfinance as yf

from data import to_yahoo

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 21600.0


def _clean(v):
    try:
        f = float(v)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return v


def get_fundamentals(ticker: str) -> dict:
    yt = to_yahoo(ticker)
    now = time.time()
    cached = _cache.get(yt)
    if cached and now - cached[0] < _TTL:
        return cached[1]

    out: dict = {"ticker": ticker.upper()}
    info: dict = {}
    try:
        info = yf.Ticker(yt).info or {}
    except Exception:
        info = {}

    def g(*keys):
        for k in keys:
            v = info.get(k)
            if v is not None:
                return v
        return None

    out.update({
        "name": g("longName", "shortName"),
        "sector": g("sector"),
        "industry": g("industry"),
        "market_cap": _clean(g("marketCap")),
        "pe": _clean(g("trailingPE", "forwardPE")),
        "pb": _clean(g("priceToBook")),
        "roe": _clean(g("returnOnEquity")),
        "der": _clean(g("debtToEquity")),
        "eps": _clean(g("trailingEps")),
        "dividend_yield": _clean(g("dividendYield")),
        "profit_margin": _clean(g("profitMargins")),
        "revenue_growth": _clean(g("revenueGrowth")),
        "earnings_growth": _clean(g("earningsGrowth")),
        "beta": _clean(g("beta")),
        "high_52w": _clean(g("fiftyTwoWeekHigh")),
        "low_52w": _clean(g("fiftyTwoWeekLow")),
        "price": _clean(g("currentPrice", "regularMarketPrice")),
        "pe_forward": _clean(g("forwardPE")),
        "peg": _clean(g("pegRatio", "trailingPegRatio")),
        "ps": _clean(g("priceToSalesTrailing12Months")),
        "gross_margin": _clean(g("grossMargins")),
        "operating_margin": _clean(g("operatingMargins")),
        "current_ratio": _clean(g("currentRatio")),
        "book_value": _clean(g("bookValue")),
        "revenue": _clean(g("totalRevenue")),
        "net_income": _clean(g("netIncomeToCommon")),
        "ebitda": _clean(g("ebitda")),
        "free_cashflow": _clean(g("freeCashflow")),
        "cash": _clean(g("totalCash")),
        "debt": _clean(g("totalDebt")),
        "shares": _clean(g("sharesOutstanding")),
    })
    _cache[yt] = (now, out)
    return out
