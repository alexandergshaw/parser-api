"""Orchestrates a parse into lens-keyed results.

`parse()` is pure and deterministic. The response is organized entirely by the
requested lenses (``targets``); there is no special-cased primary/secondary.
"""

from __future__ import annotations

from typing import Any

from .classify import ScoredCategory, classify, emphasis_lens, link_term
from .keywords import merge_keywords, rake
from .lenses import Lens, default_target_names, get_lenses, max_term_n, resolve_target
from .lexicons import Lexicon
from .normalize import build_surface_index, count_ngrams, load_stopwords, stem_chunks, to_chunks
from .taxonomy import get_taxonomy
from .tone import score_tone

DEFAULT_MAX_KEYWORDS = 15
DEFAULT_CONFIDENCE_THRESHOLD = 0.15


def _normalize_targets(targets: Any) -> list[tuple[str, int | None]] | None:
    """Normalize the `targets` param to [(name, limit)], or None for 'use defaults'."""
    if targets is None:
        return None
    requested: list[tuple[str, int | None]] = []
    for t in targets:
        if isinstance(t, str):
            requested.append((t, None))
        elif isinstance(t, dict) and isinstance(t.get("name"), str):
            limit = t.get("limit")
            requested.append((t["name"], limit if isinstance(limit, int) else None))
        else:
            raise ValueError("Each target must be a lens name or an object {name, limit}.")
    if not requested:
        raise ValueError("`targets` must be a non-empty array.")
    return requested


def _lexicon_lens(
    lexicon: Lexicon, ngram_counts, scored: list[ScoredCategory], limit: int | None
) -> dict[str, Any]:
    hits = [(ngram_counts.get(e.key, 0), e) for e in lexicon.entries]
    hits = [(c, e) for c, e in hits if c]
    hits.sort(key=lambda ce: (-ce[0], ce[1].display.lower()))
    matched = [
        {"term": e.term, "display": e.display, "related": link_term(e.key, scored)}
        for _, e in hits
    ]
    if limit is not None:
        matched = matched[:limit]
    return {"kind": "lexicon", "matched": matched}


def _keywords_lens(
    chunks, scored: list[ScoredCategory], surface_index, max_keywords: int, limit: int | None
) -> dict[str, Any]:
    keywords = merge_keywords(rake(chunks, load_stopwords(), surface_index), scored, max_keywords)
    items = []
    for kw in keywords:
        items.append(
            {
                "term": kw.term,
                "display": kw.display,
                "score": kw.score,
                "source": kw.source,
                "related": link_term(kw.term, scored),
            }
        )
    if limit is not None:
        items = items[:limit]
    return {"kind": "keywords", "items": items}


def parse(
    text: str,
    *,
    targets: Any = None,
    max_keywords: int = DEFAULT_MAX_KEYWORDS,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> dict[str, Any]:
    """Parse ``text`` into lens-keyed results. Raises ValueError on an unknown target."""
    from . import __version__

    requested = _normalize_targets(targets)
    if requested is None:
        plan: list[tuple[Lens, int | None]] = [(get_lenses()[n], None) for n in default_target_names()]
    else:
        plan = [(resolve_target(name), limit) for name, limit in requested]

    taxonomy = get_taxonomy()
    chunks = to_chunks(text)
    token_count = sum(len(c) for c in chunks)
    max_n = max(taxonomy.max_term_n, max_term_n())
    ngram_counts = count_ngrams(stem_chunks(chunks), max_n)
    scored = classify(ngram_counts, taxonomy)
    surface_index = build_surface_index(text)

    results: dict[str, Any] = {}
    for lens, limit in plan:
        if lens.kind == "emphasis":
            results[lens.name] = emphasis_lens(scored, lens.axis, confidence_threshold, limit)
        elif lens.kind == "lexicon":
            results[lens.name] = _lexicon_lens(lens.lexicon, ngram_counts, scored, limit)
        elif lens.kind == "keywords":
            results[lens.name] = _keywords_lens(chunks, scored, surface_index, max_keywords, limit)
        elif lens.kind == "tone":
            results[lens.name] = score_tone(lens.tone, ngram_counts, chunks, text)

    return {"results": results, "meta": {"token_count": token_count, "version": __version__}}
