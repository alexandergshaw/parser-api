"""Specific keyword extraction via a pure-Python RAKE implementation.

Unsupervised, single-document, deterministic: split text into candidate phrases at
stopwords/punctuation, score words by degree/frequency and phrases by the sum of
their word scores. No model, no corpus, no network.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .classify import ScoredCategory

_MIN_WORD_LEN = 2
_MAX_PHRASE_WORDS = 4


@dataclass
class Keyword:
    term: str  # lowercased, de-punctuated — stable join/dedup key
    score: float
    source: str  # "rake" | "lexicon" | "rake+lexicon"
    display: str | None = None  # human-facing casing
    related: dict[str, str] | None = None  # {id, label} of the parent emphasis, or None


def _render(term: str, surface_index: dict[str, str]) -> str:
    """Render a RAKE term with the casing it had in the source (token-wise, deterministic)."""
    return " ".join(surface_index.get(tok, tok.capitalize()) for tok in term.split())


def _candidate_phrases(
    chunks: list[list[str]], stopwords: frozenset[str]
) -> list[tuple[str, ...]]:
    phrases: list[tuple[str, ...]] = []
    for tokens in chunks:
        current: list[str] = []
        for tok in tokens:
            if tok in stopwords or len(tok) < _MIN_WORD_LEN or tok.isdigit():
                if current:
                    phrases.append(tuple(current))
                    current = []
            else:
                current.append(tok)
        if current:
            phrases.append(tuple(current))
    return [p for p in phrases if 1 <= len(p) <= _MAX_PHRASE_WORDS]


def rake(
    chunks: list[list[str]],
    stopwords: frozenset[str],
    surface_index: dict[str, str],
) -> list[Keyword]:
    """Rank candidate keyphrases by RAKE score, normalized to [0, 1]."""
    phrases = _candidate_phrases(chunks, stopwords)
    if not phrases:
        return []

    freq: Counter[str] = Counter()
    degree: Counter[str] = Counter()
    for phrase in phrases:
        span = len(phrase)
        for word in phrase:
            freq[word] += 1
            degree[word] += span  # degree includes the word itself (standard RAKE)

    word_score = {word: degree[word] / freq[word] for word in freq}

    phrase_scores: dict[str, float] = {}
    for phrase in phrases:
        term = " ".join(phrase)
        if term not in phrase_scores:
            phrase_scores[term] = sum(word_score[w] for w in phrase)

    top = max(phrase_scores.values())
    return [
        Keyword(term=term, score=round(score / top, 4), source="rake", display=_render(term, surface_index))
        for term, score in sorted(phrase_scores.items(), key=lambda kv: kv[1], reverse=True)
    ]


def merge_keywords(
    rake_keywords: list[Keyword],
    scored: list[ScoredCategory],
    max_keywords: int,
) -> list[Keyword]:
    """Merge RAKE phrases with classifier evidence terms, dedupe, and re-rank.

    The join key is the lowercased surface; the human-facing form is the taxonomy's
    authored display. A term found by both sources is tagged ``rake+lexicon``.
    """
    merged: dict[str, Keyword] = {kw.term: kw for kw in rake_keywords}

    for rank, cat in enumerate(scored[:4]):
        base = max(0.3, 1.0 - rank * 0.2)
        for i, key in enumerate(cat.matched_keys):
            term = cat.matched_surfaces[i] if i < len(cat.matched_surfaces) else key
            disp = cat.matched_terms[i] if i < len(cat.matched_terms) else None
            lex_score = round(base * (1.0 - min(i, 9) * 0.05), 4)
            existing = merged.get(term)
            if existing is None:
                merged[term] = Keyword(term=term, score=lex_score, source="lexicon", display=disp)
            else:
                merged[term] = Keyword(
                    term=term,
                    score=min(1.0, round(max(existing.score, lex_score) + 0.1, 4)),
                    source="rake+lexicon",
                    display=disp or existing.display,
                )

    ranked = sorted(merged.values(), key=lambda kw: kw.score, reverse=True)
    return ranked[:max_keywords]
