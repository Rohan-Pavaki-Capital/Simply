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
    GET  /api/credit-rating -> company name -> credit rating mapped to scale (JSON)
    GET  /api/industry      -> ticker -> GuruFocus industry mapped to Damodaran (JSON)
    GET  /api/health        -> health check (for Render/Railway)
"""
from __future__ import annotations

import importlib.util
import os


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from a sibling .env into os.environ.

    Dependency-free (python-dotenv isn't installed) and non-destructive: a
    value already present in the real environment (e.g. set in the Render /
    Railway dashboard) is never overwritten. Must run BEFORE the router imports
    below, since they read os.environ at import time (e.g. FIRECRAWL_API_KEY).
    """
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from simply_route import router as simply_router
from beta.beta_route import router as beta_router
from Company_Industry import router as industry_router


def _load_router_from_path(module_name: str, file_path: str):
    """Load a router module that lives in a non-importable folder.

    The Credit-Ratings folder has a hyphen, so it can't be a Python package;
    load its credit_route.py directly by file path instead.
    """
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.router


credit_router = _load_router_from_path(
    "credit_route",
    os.path.join(os.path.dirname(__file__), "Credit-Ratings", "credit_route.py"),
)

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
app.include_router(credit_router)
app.include_router(industry_router)


@app.get("/")
def root():
    return RedirectResponse(url="/simply")


@app.get("/api/health")
def health():
    return {"status": "ok"}
