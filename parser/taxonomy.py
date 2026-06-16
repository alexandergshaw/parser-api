"""Loads and indexes the curated taxonomy (taxonomy/*.json).

Each category contributes a set of normalized lexicon terms with weights. At load
time we also compute a discriminative IDF weight per term: a term shared across many
categories (e.g. "python") is down-weighted, a rare/specific term counts more. This
gives TF-IDF-like behaviour without needing a training corpus.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .normalize import normalize_term

# taxonomy/ sits next to the parser/ package at the repo root.
_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "taxonomy"

# Aliases are alternative names for the whole category, so they're a strong signal.
_ALIAS_WEIGHT = 3.0
# Hard cap on n-gram length we bother to generate/match.
_MAX_N = 4


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    type: str  # "field" | "sector"
    terms: dict[str, float]  # normalized term -> weight


@dataclass
class Taxonomy:
    categories: list[Category] = field(default_factory=list)
    idf: dict[str, float] = field(default_factory=dict)
    max_term_n: int = 1


def _load_category(raw: dict, fallback_type: str) -> Category:
    terms: dict[str, float] = {}
    for entry in raw.get("terms", []):
        term = normalize_term(entry["term"])
        if not term:
            continue
        weight = float(entry.get("weight", 1))
        terms[term] = max(terms.get(term, 0.0), weight)
    for alias in raw.get("aliases", []):
        term = normalize_term(alias)
        if term:
            terms[term] = max(terms.get(term, 0.0), _ALIAS_WEIGHT)
    return Category(
        id=raw["id"],
        label=raw["label"],
        type=raw.get("type", fallback_type),
        terms=terms,
    )


def load_taxonomy(directory: Path | str | None = None) -> Taxonomy:
    """Build a Taxonomy from the JSON files in ``directory`` (uncached)."""
    base = Path(directory) if directory else Path(os.environ.get("TAXONOMY_DIR", _DEFAULT_DIR))
    categories: list[Category] = []
    for path in sorted(base.glob("*.json")):
        fallback_type = path.stem.rstrip("s")  # fields.json -> "field"
        data = json.loads(path.read_text(encoding="utf-8"))
        for raw in data:
            categories.append(_load_category(raw, fallback_type))

    # Document frequency of each term across all categories -> smoothed IDF.
    doc_freq: dict[str, int] = {}
    for cat in categories:
        for term in cat.terms:
            doc_freq[term] = doc_freq.get(term, 0) + 1
    n_cats = len(categories) or 1
    idf = {
        term: math.log((n_cats + 1) / (df + 1)) + 1.0
        for term, df in doc_freq.items()
    }

    max_term_n = 1
    for cat in categories:
        for term in cat.terms:
            max_term_n = max(max_term_n, len(term.split()))
    max_term_n = min(max_term_n, _MAX_N)

    return Taxonomy(categories=categories, idf=idf, max_term_n=max_term_n)


@lru_cache(maxsize=1)
def get_taxonomy() -> Taxonomy:
    """Process-cached taxonomy singleton (built once per cold start)."""
    return load_taxonomy()
