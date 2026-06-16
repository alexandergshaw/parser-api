"""FastAPI application — Vercel entrypoint.

Exposes the ASGI ``app`` that Vercel's @vercel/python builder mounts. Serves the
testing UI at ``/`` and the parse endpoint at ``/api/parse``. All heavy lifting
lives in the framework-agnostic ``parser`` package.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the repo root is importable so the top-level `parser` package resolves
# regardless of the function's working directory on Vercel.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from parser import __version__, parse
from parser.pipeline import DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_MAX_KEYWORDS
from parser.taxonomy import get_taxonomy

MAX_TEXT_CHARS = 50_000
_UI_PATH = Path(__file__).resolve().parent.parent / "public" / "index.html"

API_KEY = os.environ.get("API_KEY", "").strip()
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
CONFIDENCE_THRESHOLD = float(
    os.environ.get("CONFIDENCE_THRESHOLD", DEFAULT_CONFIDENCE_THRESHOLD)
)


# --------------------------------------------------------------------------- models
class ParseRequest(BaseModel):
    text: str = Field(..., description="The block of text to analyze.")
    max_keywords: int = Field(
        DEFAULT_MAX_KEYWORDS, ge=1, le=50, description="Max specific keywords to return."
    )
    language: str = Field("en", description="Reserved for future multi-language support.")


class Emphasis(BaseModel):
    label: str
    type: str
    score: float
    matched_terms: list[str]


class RankedEmphasis(Emphasis):
    id: str


class Keyword(BaseModel):
    term: str
    score: float
    source: str


class Meta(BaseModel):
    token_count: int
    confidence: float
    low_confidence: bool
    version: str


class ParseResponse(BaseModel):
    primary: Emphasis | None
    secondary: Emphasis | None
    emphases: list[RankedEmphasis]
    keywords: list[Keyword]
    meta: Meta


# --------------------------------------------------------------------------- app
app = FastAPI(
    title="Parser API",
    version=__version__,
    description=(
        "Deterministic, LLM-free extraction of a text's broad emphases (curated "
        "taxonomy + lexicon scoring) and specific subtopics/keywords (RAKE)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce the shared secret when API_KEY is configured; otherwise open."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@app.on_event("startup")
def _warm_taxonomy() -> None:
    # Build + cache the taxonomy at cold start so the first request is fast.
    get_taxonomy()


@app.get("/api/health")
def health() -> dict[str, object]:
    tax = get_taxonomy()
    return {"status": "ok", "version": __version__, "categories": len(tax.categories)}


@app.post("/api/parse", response_model=ParseResponse, dependencies=[Depends(require_api_key)])
def parse_text(req: ParseRequest) -> dict:
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="`text` must be a non-empty string.")
    if len(req.text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"`text` exceeds the {MAX_TEXT_CHARS}-character limit.",
        )
    return parse(
        req.text,
        max_keywords=req.max_keywords,
        confidence_threshold=CONFIDENCE_THRESHOLD,
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse("<h1>Parser API</h1><p>See <a href='/docs'>/docs</a>.</p>")
    # Inject the key so the same-origin testing UI can call a protected endpoint.
    # (Internal tool: anyone who can load this page can read the key.)
    html = _UI_PATH.read_text(encoding="utf-8").replace("__API_KEY__", API_KEY)
    return HTMLResponse(html)
