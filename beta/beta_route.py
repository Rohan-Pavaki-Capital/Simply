"""
beta_route.py — standalone "beta value" feature.

Exposes an APIRouter that app.py mounts on the SAME origin / uvicorn server as
the Simply Wall St forecast:

  GET  /api/beta   -> ticker -> company beta (JSON)

It pulls beta straight from yfinance. The ticker is pre-filtered with the same
logic as the Simply feature: if the input carries an exchange prefix like
"XPAR:CAP", the prefix is dropped and the bare symbol ("CAP") is sent to
yfinance (Approach A — bare-symbol lookup).

Output shape:
  {"ticker": "AAPL", "source": "yfin", "beta": 1.18}
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


def _prefilter(ticker: str) -> str:
    """Strip an optional exchange prefix and return the bare symbol.

    Mirrors the Simply feature's split: "XPAR:CAP" -> "CAP", "AAPL" -> "AAPL".
    Only the symbol part (after the first ':') is kept; the exchange hint is
    discarded because yfinance is queried with the bare symbol (Approach A).
    """
    ticker = (ticker or "").strip()
    if ":" in ticker:
        _, _, sym = ticker.partition(":")
        ticker = sym.strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="A ticker symbol is required.")
    return ticker


def _fetch_beta(symbol: str):
    """Return the beta value for `symbol` from yfinance, or raise 404."""
    import yfinance as yf

    try:
        info = yf.Ticker(symbol).info
    except Exception as e:  # network / yfinance internal errors
        raise HTTPException(status_code=502, detail=f"yfinance lookup failed: {e}")

    beta = info.get("beta")
    if beta is None:
        raise HTTPException(
            status_code=404,
            detail=f"No beta value available for {symbol.upper()}.",
        )
    return beta


@router.get("/api/beta")
def api_beta(
    ticker: str = Query(..., description="Ticker symbol, e.g. AAPL (exchange prefix like XPAR:CAP is stripped)"),
):
    """Ticker -> company beta from yfinance (JSON)."""
    symbol = _prefilter(ticker)
    beta = _fetch_beta(symbol)
    return {"ticker": symbol.upper(), "source": "yfin", "beta": beta}
