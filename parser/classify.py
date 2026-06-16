"""Emphasis scoring + per-axis lens building.

Deterministic and explainable: each category's score is the sum of its matched
terms' contributions; matched terms are returned as evidence. Scores are normalized
*within an axis* (a field's share among fields), so different axes are independent.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .normalize import singularize, tokenize
from .taxonomy import Taxonomy

# A category whose entire evidence is a single low-weight (ambiguous, common-word)
# term is treated as noise, not an emphasis.
_MIN_STRONG_WEIGHT = 2.0


@dataclass
class ScoredCategory:
    id: str
    label: str
    type: str               # axis: "field" | "sector" | ...
    raw_score: float
    matched_terms: list[str]    # authored display evidence, strongest first
    matched_keys: list[str]     # canonical (stemmed) keys, aligned
    matched_surfaces: list[str] # lowercased un-stemmed forms, aligned


def _term_contribution(weight: float, count: int, idf: float) -> float:
    return weight * (1.0 + math.log(count)) * idf


def classify(ngram_counts: Counter[str], taxonomy: Taxonomy) -> list[ScoredCategory]:
    """Score every category against the document's n-gram counts (sorted by raw desc)."""
    scored: list[ScoredCategory] = []
    for cat in taxonomy.categories:
        raw = 0.0
        contributions: list[tuple[float, str]] = []
        max_weight = 0.0
        for key, weight in cat.terms.items():
            count = ngram_counts.get(key, 0)
            if count:
                idf = taxonomy.idf.get(key, 1.0)
                contribution = _term_contribution(weight, count, idf)
                raw += contribution
                contributions.append((contribution, key))
                max_weight = max(max_weight, weight)
        if raw <= 0:
            continue
        if len(contributions) < 2 and max_weight < _MIN_STRONG_WEIGHT:
            continue  # lone ambiguous term -> not a real emphasis
        contributions.sort(reverse=True)
        scored.append(
            ScoredCategory(
                id=cat.id,
                label=cat.label,
                type=cat.type,
                raw_score=raw,
                matched_terms=[cat.display.get(k, k) for _, k in contributions],
                matched_keys=[k for _, k in contributions],
                matched_surfaces=[cat.surface.get(k, k) for _, k in contributions],
            )
        )
    scored.sort(key=lambda s: s.raw_score, reverse=True)
    return scored


def link_term(term: str, scored: list[ScoredCategory]) -> dict[str, str] | None:
    """Link a term to the highest-ranked emphasis sharing a (stemmed) token, else None."""
    tokens = {singularize(tok) for tok in tokenize(term)}
    for cat in scored:  # already sorted by raw desc
        cat_tokens: set[str] = set()
        for key in cat.matched_keys:
            cat_tokens.update(key.split())
        if tokens & cat_tokens:
            return {"id": cat.id, "label": cat.label}
    return None


def emphasis_lens(
    scored: list[ScoredCategory], axis: str, threshold: float, limit: int | None = None
) -> dict[str, Any]:
    """Build an emphasis-lens result for one axis, normalized within that axis."""
    cats = [c for c in scored if c.type == axis]
    total = sum(c.raw_score for c in cats)
    ranked = [
        {
            "id": c.id,
            "label": c.label,
            "score": round(c.raw_score / total, 4) if total else 0.0,
            "matched_terms": c.matched_terms[:8],
        }
        for c in cats  # scored already sorted by raw desc
    ]
    top = None
    if ranked:
        top = {**ranked[0], "low_confidence": ranked[0]["score"] < threshold}
    if limit is not None:
        ranked = ranked[:limit]
    return {"kind": "emphasis", "top": top, "ranked": ranked}
