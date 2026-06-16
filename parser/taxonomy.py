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

from .normalize import canonical_term, display_term, title_case

# taxonomy/ sits next to the parser/ package at the repo root. The function's
# working directory / bundle layout can vary on Vercel, so probe likely roots.
_CANDIDATE_ROOTS = [
    Path(__file__).resolve().parent.parent,  # repo root (parser/..)
    Path.cwd(),
    Path("/var/task"),                        # Vercel / Lambda task root
]


def _default_dir() -> Path:
    env = os.environ.get("TAXONOMY_DIR")
    if env:
        return Path(env)
    for root in _CANDIDATE_ROOTS:
        candidate = root / "taxonomy"
        if candidate.is_dir():
            return candidate
    return _CANDIDATE_ROOTS[0] / "taxonomy"

# Aliases are alternative names for the whole category, so they're a strong signal.
_ALIAS_WEIGHT = 3.0
# Hard cap on n-gram length we bother to generate/match.
_MAX_N = 4


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    type: str  # "field" | "sector"
    terms: dict[str, float]  # canonical (stemmed) key -> weight
    display: dict[str, str]  # canonical key -> authored human-facing form ("ETL", "CI/CD")
    surface: dict[str, str]  # canonical key -> lowercased un-stemmed form (stable join key)


@dataclass
class Taxonomy:
    categories: list[Category] = field(default_factory=list)
    idf: dict[str, float] = field(default_factory=dict)
    max_term_n: int = 1


def _load_category(raw: dict, fallback_type: str) -> Category:
    terms: dict[str, float] = {}
    surface: dict[str, str] = {}   # canonical key -> shortest lowercased surface
    authored: dict[str, str] = {}  # canonical key -> explicit display, if any

    def add(text: str, weight: float, display: str | None = None) -> None:
        key = canonical_term(text)
        if not key:
            return
        terms[key] = max(terms.get(key, 0.0), weight)
        # Prefer the shortest surface form (usually the singular) as the join key.
        low = display_term(text)
        if key not in surface or len(low) < len(surface[key]):
            surface[key] = low
        if display and key not in authored:
            authored[key] = display  # first authored display wins (file order)

    for entry in raw.get("terms", []):
        add(entry["term"], float(entry.get("weight", 1)), entry.get("display"))
    for alias in raw.get("aliases", []):
        alias_text, alias_display = (alias, None) if isinstance(alias, str) else (
            alias["term"],
            alias.get("display"),
        )
        add(alias_text, _ALIAS_WEIGHT, alias_display)

    # Display = authored form when given, otherwise a deterministic title-case fallback.
    display = {key: authored.get(key, title_case(surface[key])) for key in terms}

    return Category(
        id=raw["id"],
        label=raw["label"],
        type=raw.get("type", fallback_type),
        terms=terms,
        display=display,
        surface=surface,
    )


def load_taxonomy(directory: Path | str | None = None) -> Taxonomy:
    """Build a Taxonomy from the JSON files in ``directory`` (uncached)."""
    base = Path(directory) if directory else _default_dir()
    categories: list[Category] = []
    for path in sorted(base.glob("*.json")):
        if path.name == "lenses.json":
            continue  # the lens registry is not a category file
        fallback_type = path.stem.rstrip("s")  # fields.json -> "field"
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for raw in data:
            if isinstance(raw, dict) and "id" in raw:
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
