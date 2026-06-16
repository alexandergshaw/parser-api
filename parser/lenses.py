"""Lens registry — declares what the parser can extract, loaded from taxonomy/lenses.json.

A lens is one of three kinds:
- ``emphasis``: rank taxonomy categories of one axis (e.g. field, sector).
- ``lexicon``:  report which terms from a flat curated list appear (e.g. technologies).
- ``keywords``: unsupervised RAKE keyphrases.

Adding a new lens is data-only: edit lenses.json (+ a lexicon file for lexicon lenses).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .lexicons import Lexicon, load_lexicon
from .taxonomy import _default_dir

VALID_KINDS = {"emphasis", "lexicon", "keywords"}


@dataclass
class Lens:
    name: str
    kind: str
    axis: str | None = None
    source: str | None = None
    default: bool = False
    lexicon: Lexicon | None = None


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
            lens.lexicon = load_lexicon(_default_dir() / lens.source)
        registry[lens.name] = lens
    return registry


def default_target_names() -> list[str]:
    return [name for name, lens in get_lenses().items() if lens.default]


def resolve_target(name: str) -> Lens:
    registry = get_lenses()
    if name not in registry:
        raise ValueError(f"Unknown target '{name}'. Valid targets: {', '.join(registry)}.")
    return registry[name]


def max_lexicon_term_n() -> int:
    return max((l.lexicon.max_term_n for l in get_lenses().values() if l.lexicon), default=1)
