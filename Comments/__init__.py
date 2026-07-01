"""Comments — analyst "Comments" paragraph generator (Together AI).

Exposes ``router`` (a FastAPI APIRouter) that app.py can mount, serving
``GET /api/comment?ticker=...`` and returning the plain-text paragraph written
into the Excel valuation model at Input sheet!X14.
"""
from .comment_service import router

__all__ = ["router"]
