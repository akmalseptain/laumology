"""Register seluruh blueprint API."""
from __future__ import annotations

from flask import Flask

from . import analysis, backtest, meta, portfolio, research, screener, trackrecord, warroom

BLUEPRINTS = [analysis.bp, screener.bp, backtest.bp, research.bp, portfolio.bp, meta.bp, warroom.bp, trackrecord.bp]


def register(app: Flask) -> None:
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
