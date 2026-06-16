"""Broad-emphasis classifier: weighted lexicon scoring over the taxonomy.

Deterministic and explainable — every category's score is the sum of its matched
terms' contributions, and the matched terms are returned as evidence.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from .taxonomy import Taxonomy


@dataclass
class ScoredCategory:
    id: str
    label: str
    type: str
    score: float            # normalized share in [0, 1] across all categories
    raw_score: float        # unnormalized weighted-match score
    matched_terms: list[str]  # evidence, strongest contribution first


def _term_contribution(weight: float, count: int, idf: float) -> float:
    # Sub-linear in count so a term repeated 50x doesn't dominate; weight x IDF
    # scale strong/specific signals above ambiguous ones.
    return weight * (1.0 + math.log(count)) * idf


def classify(ngram_counts: Counter[str], taxonomy: Taxonomy) -> list[ScoredCategory]:
    """Score every category against the document's n-gram counts.

    Returns categories sorted by raw score (desc). ``score`` is each category's
    share of the total matched signal, so scores sum to ~1 across the result.
    """
    scored: list[ScoredCategory] = []
    for cat in taxonomy.categories:
        raw = 0.0
        contributions: list[tuple[float, str]] = []
        for term, weight in cat.terms.items():
            count = ngram_counts.get(term, 0)
            if count:
                idf = taxonomy.idf.get(term, 1.0)
                contribution = _term_contribution(weight, count, idf)
                raw += contribution
                contributions.append((contribution, term))
        if raw <= 0:
            continue
        contributions.sort(reverse=True)
        scored.append(
            ScoredCategory(
                id=cat.id,
                label=cat.label,
                type=cat.type,
                score=0.0,  # filled in after normalization
                raw_score=raw,
                matched_terms=[term for _, term in contributions],
            )
        )

    total = sum(s.raw_score for s in scored)
    if total > 0:
        for s in scored:
            s.score = round(s.raw_score / total, 4)

    scored.sort(key=lambda s: s.raw_score, reverse=True)
    return scored


def pick_primary_secondary(
    scored: list[ScoredCategory],
) -> tuple[ScoredCategory | None, ScoredCategory | None]:
    """Primary = top overall; secondary = top of the *other* axis (falls back to #2)."""
    if not scored:
        return None, None
    primary = scored[0]
    secondary = next((s for s in scored[1:] if s.type != primary.type), None)
    if secondary is None and len(scored) > 1:
        secondary = scored[1]
    return primary, secondary
