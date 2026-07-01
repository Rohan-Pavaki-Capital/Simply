# Comments — analyst "Comments" paragraph generator

Generates a plain-text analyst **Comments** paragraph for a company from
**supplied** factual data and returns it as JSON. The text is written into an
Excel valuation model at **Input sheet!X14** (one cell), so the output is plain
prose only — no markdown, no headings, no bullet points.

The LLM only *assembles* the values you pass in; it never invents numbers,
quotes, names, ratings, or facts. Empty optional fields simply drop their
sentence.

## LLM provider

Uses the **Together AI** OpenAI-compatible chat/completions endpoint. The model
is set in the `MODEL` constant at the top of `comment_service.py` (default
`meta-llama/Llama-3.3-70B-Instruct-Turbo`, a cost-efficient instruct model for
prose assembly). Override it without editing code via the `TOGETHER_MODEL` env
var.

## Required `.env` keys

```
TOGETHER_API_KEY=your_together_api_key      # required
TOGETHER_MODEL=meta-llama/Llama-3.3-70B-Instruct-Turbo   # optional override
```

`python-dotenv` loads these automatically. When mounted in the main app,
`app.py`'s own `.env` loader also populates them.

## Install

```
pip install -r Comments/requirements.txt
```

## Run

Mounted in the main FastAPI app (`app.py`) — see the integration note below —
then:

```
uvicorn app:app --host 0.0.0.0 --port 8000
```

Standalone format check (generates a comment from a hardcoded NIKE sample and
prints it):

```
python Comments/comment_service.py
```

## Endpoint

```
GET /api/comment?ticker=...
```

All the factual fields are passed as query params (values are supplied — the
LLM must not invent them):

| param | example | notes |
|---|---|---|
| `ticker` | `NKE` | required; response key + cache key |
| `company_name` | `NIKE` | |
| `nationality` | `American` | country/adjective |
| `industry` | `footwear brand` | |
| `period` | `nine months ending in Feb 2026` | |
| `sales_direction` | `rose` | `rose` \| `fell` |
| `profit_direction` | `but profit fell` | full clause |
| `management_quotes` | `Elliott Hill, ... said, "..."` | **verbatim**; may be empty |
| `cash_vs_debt` | `more cash than debt` | |
| `interest_coverage` | `46 times` | omit sentence if empty |
| `fcff_trend` | `positive in 10 out of 10 years` | omit if empty |
| `dividend_yield` | `3.9%` | omit if empty |
| `methods_upside` | `15 of 24 methods` | from the model |
| `verdict` | `BUY` | `BUY` \| `HOLD` \| `SELL` |
| `positive_factors` | `more cash than debt, good interest coverage, ...` | comma list |

### Response

Success:

```json
{ "ticker": "NKE", "comment": "NIKE, an American footwear brand, reported ..." }
```

Failure (never a 500):

```json
{ "ticker": "NKE", "comment": null, "error": "<reason>" }
```

### Example curl

```bash
curl -G "http://localhost:8000/api/comment" \
  --data-urlencode "ticker=NKE" \
  --data-urlencode "company_name=NIKE" \
  --data-urlencode "nationality=American" \
  --data-urlencode "industry=footwear brand" \
  --data-urlencode "period=nine months ending in Feb 2026" \
  --data-urlencode "sales_direction=rose" \
  --data-urlencode "profit_direction=but profit fell" \
  --data-urlencode 'management_quotes=Elliott Hill, President and Chief Executive Officer, NIKE, Inc, said, "Our results reflect the progress we are making."' \
  --data-urlencode "cash_vs_debt=more cash than debt" \
  --data-urlencode "interest_coverage=46 times" \
  --data-urlencode "fcff_trend=positive in 10 out of 10 years" \
  --data-urlencode "dividend_yield=3.9%" \
  --data-urlencode "methods_upside=15 of 24 methods" \
  --data-urlencode "verdict=BUY" \
  --data-urlencode "positive_factors=more cash than debt, good interest coverage, excellent FCFF trend, good earnings outlook, and dividend payment"
```

## Robustness

- The Together call is wrapped in try/except and timed out (60s). Any failure
  returns `comment: null` + `error` — **never** a 500.
- The model's response is validated as non-empty; markdown fences, a leading
  preamble, and stray formatting are stripped so only clean prose remains.
- A tiny in-memory cache keyed by ticker avoids re-generating on repeat calls
  (cleared on process restart).

## Integration note

This router mounts into the existing FastAPI app and deploys on Render. The
Excel side will `GET /api/comment?ticker=...`, read `comment`, and write it to
`Input sheet!X14`. To mount it, add to `app.py`:

```python
from Comments import router as comment_router
app.include_router(comment_router)
```
