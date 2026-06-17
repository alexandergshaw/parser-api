"""Lens registry — declares what the parser can extract, loaded from taxonomy/lenses.json.

A lens is one of these kinds:
- ``emphasis``: rank taxonomy categories of one axis (e.g. field, sector).
- ``lexicon``:  report which terms from a flat curated list appear (e.g. technologies).
- ``keywords``: unsupervised RAKE keyphrases.
- ``tone``:     multi-dimensional tone profile (e.g. formality, sentiment).

Adding a new lens is data-only: edit lenses.json (+ a data file for lexicon/tone lenses).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .lexicons import Lexicon, load_lexicon
from .taxonomy import _default_dir
from .tone import ToneModel, load_tones

VALID_KINDS = {"emphasis", "lexicon", "keywords", "tone"}


@dataclass
class Lens:
    name: str
    kind: str
    axis: str | None = None
    source: str | None = None
    default: bool = False
    lexicon: Lexicon | None = None
    tone: ToneModel | None = None


@lru_cache(maxsize=1)
def get_lenses() -> dict[str, Lens]:
    """Process-cached lens registry, in declaration order."""
    base = _default_dir()
    rows = json.loads((base / "lenses.json").read_text(encoding="utf-8"))
    registry: dict[str, Lens] = {}
    for row in rows:
        lens = Lens(
            name=row["name"],
            kind=row["kind"],
            axis=row.get("axis"),
            source=row.get("source"),
            default=bool(row.get("default", False)),
        )
        if lens.kind == "lexicon" and lens.source:
            lens.lexicon = load_lexicon(base / lens.source)
        elif lens.kind == "tone" and lens.source:
            lens.tone = load_tones(base / lens.source)
        registry[lens.name] = lens
    return registry


def default_target_names() -> list[str]:
    return [name for name, lens in get_lenses().items() if lens.default]


def resolve_target(name: str) -> Lens:
    registry = get_lenses()
    if name not in registry:
        raise ValueError(f"Unknown target '{name}'. Valid targets: {', '.join(registry)}.")
    return registry[name]


def max_term_n() -> int:
    """Longest cue/term (in tokens) across all lexicon + tone lenses, so n-gram
    counting covers their multiword cues."""
    best = 1
    for lens in get_lenses().values():
        if lens.lexicon:
            best = max(best, lens.lexicon.max_term_n)
        if lens.tone:
            best = max(best, lens.tone.max_term_n)
    return best
