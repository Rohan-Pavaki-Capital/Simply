"""
app.py — standalone deployment entry point for the Simply Wall St forecast
feature and the yfinance beta lookup.

This mounts the Simply Wall St forecast router (simply_route.py) — which
scrapes forward analyst consensus from Simply Wall St with no browser, no OCR,
and no API keys — plus the beta router (beta/beta_route.py), which returns a
company's beta from yfinance. Both run on the same uvicorn server.

Run locally:
    uvicorn app:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /                  -> redirects to the ticker form
    GET  /simply            -> self-contained ticker form (HTML)
    GET  /api/simply        -> ticker [+ exchange] -> forecast rows (JSON)
    GET  /api/simply/excel  -> same forecast as a downloadable .xlsx
    GET  /api/beta          -> ticker -> company beta from yfinance (JSON)
    GET  /api/health        -> health check (for Render/Railway)
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from simply_route import router as simply_router
from beta.beta_route import router as beta_router

app = FastAPI(title="Simply Wall St Forecast")

# Allow a browser frontend on any origin to call the API. Override with the
# CORS_ORIGIN_REGEX env var to lock this down to your own domain.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=os.environ.get("CORS_ORIGIN_REGEX", ".*"),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(simply_router)
app.include_router(beta_router)


@app.get("/")
def root():
    return RedirectResponse(url="/simply")


@app.get("/api/health")
def health():
    return {"status": "ok"}
