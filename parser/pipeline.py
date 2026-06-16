"""Orchestrates the full parse: normalize -> classify (broad) + extract (specific) -> result."""

from __future__ import annotations

from typing import Any

from .classify import ScoredCategory, classify, pick_primary_secondary
from .keywords import assign_related_emphasis, merge_keywords, rake
from .normalize import count_ngrams, load_stopwords, stem_chunks, to_chunks
from .taxonomy import Taxonomy, get_taxonomy

DEFAULT_MAX_KEYWORDS = 15
DEFAULT_CONFIDENCE_THRESHOLD = 0.15


def _emphasis_dict(cat: ScoredCategory | None, max_terms: int = 8) -> dict[str, Any] | None:
    if cat is None:
        return None
    return {
        "id": cat.id,
        "label": cat.label,
        "type": cat.type,
        "score": cat.score,
        "matched_terms": cat.matched_terms[:max_terms],
    }


def parse(
    text: str,
    *,
    max_keywords: int = DEFAULT_MAX_KEYWORDS,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    taxonomy: Taxonomy | None = None,
) -> dict[str, Any]:
    """Parse ``text`` into broad emphases + specific keywords. Pure, deterministic."""
    from . import __version__

    taxonomy = taxonomy or get_taxonomy()
    chunks = to_chunks(text)
    token_count = sum(len(c) for c in chunks)

    # Matching uses stemmed n-grams (so plurals match); keyword display uses the
    # original surface forms from `chunks`.
    ngram_counts = count_ngrams(stem_chunks(chunks), taxonomy.max_term_n)
    scored = classify(ngram_counts, taxonomy)
    primary, secondary = pick_primary_secondary(scored)

    rake_keywords = rake(chunks, load_stopwords())
    keywords = merge_keywords(rake_keywords, scored, max_keywords)
    assign_related_emphasis(keywords, scored)

    confidence = primary.score if primary else 0.0
    low_confidence = primary is None or confidence < confidence_threshold

    return {
        "primary": _emphasis_dict(primary),
        "secondary": _emphasis_dict(secondary),
        "emphases": [
            {
                "id": s.id,
                "label": s.label,
                "type": s.type,
                "score": s.score,
                "matched_terms": s.matched_terms[:8],
            }
            for s in scored
        ],
        "keywords": [
            {
                "term": kw.term,
                "score": kw.score,
                "source": kw.source,
                "related_emphasis": kw.related,
            }
            for kw in keywords
        ],
        "meta": {
            "token_count": token_count,
            "confidence": round(confidence, 4),
            "low_confidence": low_confidence,
            "version": __version__,
        },
    }
