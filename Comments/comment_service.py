"""
comment_service.py — standalone "analyst Comments paragraph" feature.

Exposes an APIRouter that app.py can mount on the SAME origin / uvicorn server
as the Simply Wall St forecast, the beta lookup, the credit-rating lookup and
the industry lookup:

  GET  /api/comment?ticker=NKE&company_name=NIKE&...  -> comment paragraph (JSON)

What it does:
  1. Take FACTUAL company data supplied by the caller (company name, nationality,
     industry, period, sales/profit direction, verbatim management quotes,
     balance-sheet facts, the model's verdict, etc.). These values are passed IN
     — the LLM must NEVER invent them.
  2. Ask a cost-efficient Together AI instruct model to assemble those values
     into ONE plain-text analyst "Comments" paragraph following a fixed
     4-part structure (opening / management quotes / balance-sheet facts /
     verdict). Empty fields simply drop their sentence — nothing is fabricated.
  3. Return the clean prose (no markdown, no headings, no bullets) as JSON. The
     text is written into an Excel valuation model at Input sheet!X14, i.e. one
     cell, so the output is plain prose only.

CRITICAL: the endpoint NEVER raises (never 500). On any failure it returns
``comment: null`` with an ``error`` field.

Output shape (success):
  { "ticker": "NKE", "comment": "<the paragraph>" }
Output shape (failure):
  { "ticker": "NKE", "comment": null, "error": "<reason>" }

Config (read from the environment; python-dotenv loads it from .env, and when
this router is mounted, app.py's own .env loader also populates it):
  TOGETHER_API_KEY   required — the Together AI API token.
  TOGETHER_MODEL     optional — overrides the default MODEL below.

INTEGRATION NOTE (not implemented here): this router is mounted into the
existing FastAPI app and deployed on Render. The Excel side will
GET /api/comment?ticker=..., read ``comment``, and write it to Input sheet!X14.
"""
from __future__ import annotations

import os
import re

import requests
from dotenv import load_dotenv
from fastapi import APIRouter, Query

# Load .env so TOGETHER_API_KEY is available when this module is imported or run
# standalone. Non-destructive: values already in the real environment (e.g. set
# in the Render dashboard, or by app.py's own loader) are not overwritten.
load_dotenv()

router = APIRouter()

# ---------------------------------------------------------------------------
# Model — cost-efficient but capable instruct model for prose synthesis.
# This is plain prose assembly, NOT reasoning-heavy, so we do NOT pick an
# expensive model. Override with the TOGETHER_MODEL env var without editing code.
# ---------------------------------------------------------------------------
MODEL = os.environ.get("TOGETHER_MODEL", "").strip() or "meta-llama/Llama-3.3-70B-Instruct-Turbo"

TOGETHER_URL = "https://api.together.xyz/v1/chat/completions"
TIMEOUT_SECONDS = 60

# Tiny in-memory cache keyed by ticker so repeat calls for the same company
# don't re-hit the LLM. Cleared on process restart.
_CACHE: dict[str, str] = {}


# ===========================================================================
# PROMPTS
# ===========================================================================
SYSTEM_PROMPT = (
    "You are an equity analyst assembling a factual company \"Comments\" "
    "paragraph from data that is SUPPLIED to you.\n"
    "\n"
    "Hard rules:\n"
    "- Use ONLY the values provided in the user message. NEVER invent numbers, "
    "quotes, names, titles, ratings, or facts. If a field is empty or missing, "
    "OMIT its sentence entirely — do not fabricate a value to fill it.\n"
    "- Reproduce the management quote(s) EXACTLY as given — do not paraphrase, "
    "shorten, translate, or embellish them.\n"
    "- The verdict (BUY/HOLD/SELL) and the methods-upside figure come from the "
    "input — never decide these yourself; just place them in the final "
    "paragraph.\n"
    "- Output PLAIN TEXT only. No markdown, no bold, no italics, no bullet "
    "points, no headings, no numbered lists. Separate paragraphs with a blank "
    "line (\\n\\n). Aim for about 150-250 words.\n"
    "- Do NOT add a preamble, title, sign-off, or any commentary. Return ONLY "
    "the comment body itself.\n"
    "\n"
    "Structure (4 parts, in this order):\n"
    "1. Opening (one or two sentences): \"{company_name}, a {nationality} "
    "{industry}, delivered/reported {assessment} results in {period}. Sales "
    "{sales_direction}, {profit_direction}.\" Choose {assessment} "
    "('solid'/'good'/'mixed'/'weak') consistent with the sales and profit "
    "direction.\n"
    "2. Management quotes (ONLY if a quote is provided): reproduce the supplied "
    "quote(s) verbatim, e.g. 'Name, Title, said, \"...\"'. Keep multiple quotes "
    "as separate paragraphs.\n"
    "3. Balance-sheet / quality facts: build ONLY from the non-empty fields — "
    "\"The company's balance sheet shows {cash_vs_debt}. Interest coverage "
    "stands at {interest_coverage}. Free cash flows have been {fcff_trend}. The "
    "company pays a dividend yielding {dividend_yield}.\" Omit any sentence "
    "whose field is empty.\n"
    "4. Verdict (always last): \"Overall, the upside from {methods_upside}, "
    "{positive_factors} make {company_name} a {verdict}.\"\n"
)


def _build_user_prompt(fields: dict[str, str]) -> str:
    """Assemble the user prompt from the supplied fields.

    Only non-empty fields are listed, so the model is never even shown an empty
    value to be tempted into filling. The instructions above tell it to omit the
    matching sentence when a field is absent here.
    """
    def g(key: str) -> str:
        return (fields.get(key) or "").strip()

    lines: list[str] = [
        "Assemble the analyst Comments paragraph from these SUPPLIED values. "
        "Use only what is listed here; omit any sentence whose value is not "
        "provided.\n",
    ]

    # Ordered so the prompt mirrors the required output structure.
    ordered = [
        ("company_name", "Company name"),
        ("nationality", "Nationality (country/adjective)"),
        ("industry", "Industry"),
        ("period", "Reporting period"),
        ("sales_direction", "Sales direction"),
        ("profit_direction", "Profit clause"),
        ("management_quotes", "Management quote(s) — reproduce VERBATIM"),
        ("cash_vs_debt", "Cash vs debt"),
        ("interest_coverage", "Interest coverage"),
        ("fcff_trend", "Free cash flow trend"),
        ("dividend_yield", "Dividend yield"),
        ("methods_upside", "Upside (methods)"),
        ("positive_factors", "Positive factors"),
        ("verdict", "Verdict (BUY/HOLD/SELL)"),
    ]
    for key, label in ordered:
        value = g(key)
        if value:
            lines.append(f"- {label}: {value}")

    lines.append(
        "\nReturn only the plain-text comment (about 150-250 words), paragraphs "
        "separated by a blank line."
    )
    return "\n".join(lines)


# ===========================================================================
# OUTPUT CLEANING
# ===========================================================================
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")
_PREAMBLE_RE = re.compile(
    r"^\s*(?:here(?:'s| is)[^\n:]*:|sure[,!][^\n]*\n|comment:|comments:)\s*",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    """Strip markdown fences, a leading preamble, and stray formatting so only
    the clean paragraph remains — it goes into a single Excel cell."""
    if not text:
        return ""
    cleaned = text.strip()

    # Remove a wrapping ```...``` code fence if the model added one.
    if cleaned.startswith("```"):
        cleaned = _FENCE_RE.sub("", cleaned).strip()

    # Drop a conversational preamble line ("Here is the comment:", etc.).
    cleaned = _PREAMBLE_RE.sub("", cleaned).strip()

    # Strip common markdown emphasis / heading / bullet markers line by line —
    # the output must be plain prose for one Excel cell.
    out_lines: list[str] = []
    for line in cleaned.split("\n"):
        line = re.sub(r"^\s*#{1,6}\s*", "", line)          # headings
        line = re.sub(r"^\s*[-*+]\s+", "", line)           # bullets
        line = re.sub(r"^\s*\d+\.\s+", "", line)           # numbered lists
        out_lines.append(line)
    cleaned = "\n".join(out_lines)

    # Remove **bold** / *italic* / __underline__ markers, keeping the text.
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__(.+?)__", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", cleaned)

    # Collapse 3+ newlines to the standard paragraph separator.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# ===========================================================================
# TOGETHER AI CALL
# ===========================================================================
def _generate(fields: dict[str, str]) -> str:
    """Call Together AI and return the cleaned comment text. Raises on failure
    (the caller turns any exception into a JSON error, never a 500)."""
    api_key = os.environ.get("TOGETHER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TOGETHER_API_KEY is not set")

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(fields)},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(
        TOGETHER_URL, json=payload, headers=headers, timeout=TIMEOUT_SECONDS
    )
    resp.raise_for_status()
    data = resp.json()

    try:
        raw = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"unexpected Together AI response shape: {exc}")

    comment = _clean(raw or "")
    if not comment:
        raise RuntimeError("model returned empty text")
    return comment


# ===========================================================================
# ENDPOINT
# ===========================================================================
@router.get("/api/comment")
def get_comment(
    ticker: str = Query(..., description="Company ticker; used only as the response key and cache key."),
    company_name: str = Query("", description='e.g. "NIKE"'),
    nationality: str = Query("", description='country/adjective, e.g. "American"'),
    industry: str = Query("", description='e.g. "footwear brand"'),
    period: str = Query("", description='e.g. "nine months ending in Feb 2026"'),
    sales_direction: str = Query("", description='"rose" | "fell"'),
    profit_direction: str = Query("", description='e.g. "but profit fell"'),
    management_quotes: str = Query("", description="VERBATIM quote(s), incl. name+title. May be empty."),
    cash_vs_debt: str = Query("", description='e.g. "more cash than debt"'),
    interest_coverage: str = Query("", description='e.g. "46 times" (or "")'),
    fcff_trend: str = Query("", description='e.g. "positive in 10 out of 10 years" (or "")'),
    dividend_yield: str = Query("", description='e.g. "3.9%" (or "")'),
    methods_upside: str = Query("", description='e.g. "15 of 24 methods"'),
    verdict: str = Query("", description='"BUY" | "HOLD" | "SELL"'),
    positive_factors: str = Query("", description="comma list of positive factors"),
):
    """Generate the analyst Comments paragraph. Never returns a 500 — on any
    failure the response is ``{ticker, comment: null, error}``."""
    fields = {
        "company_name": company_name,
        "nationality": nationality,
        "industry": industry,
        "period": period,
        "sales_direction": sales_direction,
        "profit_direction": profit_direction,
        "management_quotes": management_quotes,
        "cash_vs_debt": cash_vs_debt,
        "interest_coverage": interest_coverage,
        "fcff_trend": fcff_trend,
        "dividend_yield": dividend_yield,
        "methods_upside": methods_upside,
        "verdict": verdict,
        "positive_factors": positive_factors,
    }

    cache_key = (ticker or "").strip().upper()
    if cache_key and cache_key in _CACHE:
        return {"ticker": ticker, "comment": _CACHE[cache_key]}

    try:
        comment = _generate(fields)
    except requests.Timeout:
        return {"ticker": ticker, "comment": None, "error": "Together AI request timed out"}
    except requests.RequestException as exc:
        return {"ticker": ticker, "comment": None, "error": f"Together AI request failed: {exc}"}
    except Exception as exc:  # noqa: BLE001 — never let anything become a 500
        return {"ticker": ticker, "comment": None, "error": str(exc)}

    if cache_key:
        _CACHE[cache_key] = comment
    return {"ticker": ticker, "comment": comment}


# ===========================================================================
# STANDALONE TEST — generate a comment from a hardcoded NIKE-like sample so the
# format can be eyeballed before wiring Excel:  python Comments/comment_service.py
# ===========================================================================
if __name__ == "__main__":
    sample = {
        "company_name": "NIKE",
        "nationality": "American",
        "industry": "footwear brand",
        "period": "nine months ending in Feb 2026",
        "sales_direction": "rose",
        "profit_direction": "but profit fell",
        "management_quotes": (
            'Elliott Hill, President and Chief Executive Officer, NIKE, Inc, said, '
            '"Our results reflect the progress we are making, and while there is '
            'more work ahead, I am confident in our path forward."'
        ),
        "cash_vs_debt": "more cash than debt",
        "interest_coverage": "46 times",
        "fcff_trend": "positive in 10 out of 10 years",
        "dividend_yield": "3.9%",
        "methods_upside": "15 of 24 methods",
        "verdict": "BUY",
        "positive_factors": (
            "more cash than debt, good interest coverage, excellent FCFF trend, "
            "good earnings outlook, and dividend payment"
        ),
    }

    print(f"Model: {MODEL}\n")
    try:
        print(_generate(sample))
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}")
