"""
beta_route.py — standalone "beta value" feature.

Exposes an APIRouter that app.py mounts on the SAME origin / uvicorn server as
the Simply Wall St forecast:

  GET  /api/beta   -> ticker -> company beta (JSON)

Beta is read from Yahoo Finance. The ticker is pre-filtered with the same
logic as the Simply feature: if the input carries an exchange prefix like
"XPAR:CAP", the prefix is dropped and the bare symbol ("CAP") is used
(Approach A — bare-symbol lookup).

Datacenter-IP note (mirrors Simply_wlst/data.py):
  Yahoo rate-limits cloud/datacenter IPs (Render, AWS, GCP ...) and returns
  HTTP 429 "Too Many Requests" — even though the same code works from a
  residential IP locally. So:
    * FIRECRAWL_API_KEY set  -> fetch the Yahoo quote page through Firecrawl's
      residential-IP proxy and parse beta out of it (works on any cloud host).
    * FIRECRAWL_API_KEY unset -> direct yfinance lookup (local, no credits).

Output shape:
  {"ticker": "AAPL", "source": "yfin", "beta": 1.18}
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

# When set (e.g. on Render/AWS), route the Yahoo fetch through Firecrawl so the
# request comes from a residential IP and dodges Yahoo's datacenter rate-limit.
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "").strip()

# "Beta (5Y Monthly) 1.09" as it appears on the Yahoo quote page (markdown).
_BETA_PAT = re.compile(r"Beta\s*\(5Y Monthly\)\s*(-?\d+(?:\.\d+)?)", re.I)


def _prefilter(ticker: str) -> str:
    """Strip an optional exchange prefix and return the bare symbol.

    Mirrors the Simply feature's split: "XPAR:CAP" -> "CAP", "AAPL" -> "AAPL".
    Only the symbol part (after the first ':') is kept; the exchange hint is
    discarded because Yahoo is queried with the bare symbol (Approach A).
    """
    ticker = (ticker or "").strip()
    if ":" in ticker:
        _, _, sym = ticker.partition(":")
        ticker = sym.strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="A ticker symbol is required.")
    return ticker


def _beta_via_firecrawl(symbol: str):
    """Scrape the Yahoo quote page through Firecrawl and parse out beta.

    Returns the beta as a float, or None if the page carries no beta value
    (e.g. funds / very new listings show "Beta (5Y Monthly) --")."""
    import requests

    r = requests.post(
        "https://api.firecrawl.dev/v1/scrape",
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                 "Content-Type": "application/json"},
        json={"url": f"https://finance.yahoo.com/quote/{symbol}/",
              "formats": ["markdown"]},
        timeout=120,
    )
    try:
        d = r.json()
    except Exception:
        raise HTTPException(status_code=502,
                            detail=f"Firecrawl returned non-JSON (HTTP {r.status_code}).")
    if not d.get("success"):
        # 402 = out of Firecrawl credits; surface a clear message.
        raise HTTPException(status_code=502,
                            detail=f"Firecrawl error (HTTP {r.status_code}): "
                                   f"{d.get('error') or d.get('details') or 'unknown'}")
    md = (d.get("data") or {}).get("markdown", "") or ""
    m = _BETA_PAT.search(md)
    return float(m.group(1)) if m else None


def _beta_via_yfinance(symbol: str):
    """Direct yfinance lookup (used locally when no Firecrawl key is set)."""
    import yfinance as yf

    try:
        info = yf.Ticker(symbol).info
    except Exception as e:  # network / yfinance internal errors (incl. 429)
        raise HTTPException(status_code=502, detail=f"yfinance lookup failed: {e}")
    return info.get("beta")


def _fetch_beta(symbol: str):
    """Return beta for `symbol`, via Firecrawl if a key is set else yfinance."""
    beta = _beta_via_firecrawl(symbol) if FIRECRAWL_API_KEY else _beta_via_yfinance(symbol)
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
    """Ticker -> company beta from Yahoo Finance (JSON)."""
    symbol = _prefilter(ticker)
    beta = _fetch_beta(symbol)
    return {"ticker": symbol.upper(), "source": "yfin", "beta": beta}
