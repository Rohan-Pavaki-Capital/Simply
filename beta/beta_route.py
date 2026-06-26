"""
beta_route.py — standalone "beta value" feature.

Exposes an APIRouter that app.py mounts on the SAME origin / uvicorn server as
the Simply Wall St forecast:

  GET  /api/beta   -> ticker -> company beta (JSON)

Beta is read from Yahoo Finance. The ticker is pre-filtered like the Simply
feature, but mapped into Yahoo's format: an exchange-prefixed input such as
"XPAR:CAP" is converted to Yahoo's suffix form ("CAP.PA") via _MIC_TO_YF_SUFFIX
(Approach B). US listings carry no suffix ("AAPL" stays "AAPL"). Tickers typed
in Yahoo-native form ("CAP.PA") or bare US symbols pass straight through.

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

# Exchange-prefix (MIC code) -> Yahoo Finance ticker suffix. US listings carry
# no suffix (""). Keys cover the prefixes the Simply feature accepts plus the
# full country/market table. An unknown prefix falls back to the bare symbol.
_MIC_TO_YF_SUFFIX = {
    # United States — no suffix
    "XNAS": "", "XNGS": "", "XNMS": "", "XNYS": "", "ARCX": "", "BATS": "",
    # Americas
    "XBUE": ".BA",                         # Argentina — Buenos Aires
    "BVMF": ".SA", "XBSP": ".SA",          # Brazil — B3 (Sao Paulo)
    "XTSE": ".TO",                         # Canada — Toronto
    "XTSX": ".V",                          # Canada — TSX Venture
    "XCNQ": ".CN",                         # Canada — Canadian Securities Exchange
    "NEOE": ".NE",                         # Canada — Cboe Canada (NEO)
    "XSGO": ".SN",                         # Chile — Santiago
    "XMEX": ".MX",                         # Mexico
    # Europe
    "XWBO": ".VI",                         # Austria — Vienna
    "XBRU": ".BR",                         # Belgium — Euronext Brussels
    "XPRA": ".PR",                         # Czech Republic — Prague
    "XCSE": ".CO",                         # Denmark — Nasdaq Copenhagen
    "XTAL": ".TL",                         # Estonia — Nasdaq Tallinn
    "XHEL": ".HE",                         # Finland — Nasdaq Helsinki
    "XPAR": ".PA",                         # France — Euronext Paris
    "XETR": ".DE",                         # Germany — Xetra
    "XFRA": ".F",                          # Germany — Frankfurt
    "XSTU": ".SG",                         # Germany — Stuttgart
    "XBER": ".BE",                         # Germany — Berlin
    "XDUS": ".DU",                         # Germany — Dusseldorf
    "XMUN": ".MU",                         # Germany — Munich
    "XHAM": ".HM",                         # Germany — Hamburg
    "XATH": ".AT",                         # Greece — Athens
    "XICE": ".IC",                         # Iceland — Nasdaq Iceland
    "XDUB": ".IR",                         # Ireland — Euronext Dublin
    "XMIL": ".MI",                         # Italy — Borsa Italiana (Milan)
    "XRIS": ".RG",                         # Latvia — Nasdaq Riga
    "XAMS": ".AS",                         # Netherlands — Euronext Amsterdam
    "XOSL": ".OL",                         # Norway — Oslo Bors
    "XWAR": ".WA",                         # Poland — Warsaw
    "XLIS": ".LS",                         # Portugal — Euronext Lisbon
    "MISX": ".ME",                         # Russia — Moscow Exchange
    "XMAD": ".MC",                         # Spain — Bolsa de Madrid
    "XSTO": ".ST",                         # Sweden — Nasdaq Stockholm
    "XSWX": ".SW", "XVTX": ".SW",          # Switzerland — SIX Swiss Exchange
    "XIST": ".IS",                         # Turkey — Borsa Istanbul
    "XLON": ".L",                          # UK — London Stock Exchange
    "AQSE": ".AQ",                         # UK — Aquis Stock Exchange
    # Middle East / Africa
    "XBAH": ".BD",                         # Bahrain — Bahrain Bourse
    "XCAI": ".CA",                         # Egypt — EGX (Cairo)
    "XTAE": ".TA",                         # Israel — Tel Aviv
    "XKUW": ".KW",                         # Kuwait — Boursa Kuwait
    "DSMD": ".QA", "XQUL": ".QA",          # Qatar — Qatar Stock Exchange
    "XSAU": ".SR",                         # Saudi Arabia — Tadawul
    "XJSE": ".JO",                         # South Africa — Johannesburg
    "XADS": ".AE", "XDFM": ".AE",          # UAE — Abu Dhabi / Dubai
    # Asia-Pacific
    "XASX": ".AX",                         # Australia — ASX
    "XSHE": ".SZ",                         # China — Shenzhen
    "XSHG": ".SS",                         # China — Shanghai
    "XHKG": ".HK",                         # Hong Kong
    "XBOM": ".BO",                         # India — BSE
    "XNSE": ".NS",                         # India — NSE
    "XIDX": ".JK",                         # Indonesia — IDX
    "XTKS": ".T",                          # Japan — Tokyo
    "XKLS": ".KL",                         # Malaysia — Bursa Malaysia
    "XNZE": ".NZ",                         # New Zealand — NZX
    "XSES": ".SI",                         # Singapore — SGX
    "XKRX": ".KS",                         # South Korea — KOSPI
    "XKOS": ".KQ",                         # South Korea — KOSDAQ
    "XTAI": ".TW",                         # Taiwan — Taiwan Stock Exchange
    "ROCO": ".TWO",                        # Taiwan — Taipei Exchange (OTC)
    "XBKK": ".BK",                         # Thailand — SET
    "XSTC": ".VN", "HSTC": ".VN",          # Vietnam — HOSE / HNX
}


def _prefilter(ticker: str) -> str:
    """Convert input into a Yahoo Finance symbol.

    "XPAR:CAP" -> "CAP.PA" (prefix mapped to a Yahoo suffix), "XNAS:AAPL" ->
    "AAPL" (US has no suffix), "AAPL" / "CAP.PA" -> unchanged. An unknown
    exchange prefix falls back to the bare symbol.
    """
    ticker = (ticker or "").strip()
    if ":" in ticker:
        prefix, _, sym = ticker.partition(":")
        sym = sym.strip().upper()
        prefix = prefix.strip().upper()
        if not sym:
            raise HTTPException(status_code=400, detail="A ticker symbol is required.")
        suffix = _MIC_TO_YF_SUFFIX.get(prefix)          # None -> unknown prefix
        return f"{sym}{suffix}" if suffix is not None else sym
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
              "formats": ["markdown"],
              # Force a US exit IP: non-US tickers (.L/.T/.PA ...) otherwise hit
              # Yahoo's EU/UK GDPR consent wall and the stats never render.
              "location": {"country": "US"}},
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
