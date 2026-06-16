"""Flat lexicon loading + matching (e.g. the technologies list).

A lexicon is a plain list of terms; unlike the taxonomy it does not classify into a
single label — it reports *which* of its terms appear in the text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .normalize import canonical_term, display_term, title_case


@dataclass(frozen=True)
class LexEntry:
    key: str      # canonical (stemmed) match key
    term: str     # lowercased surface — stable join key
    display: str  # authored human-facing form


@dataclass
class Lexicon:
    entries: list[LexEntry]
    max_term_n: int


def load_lexicon(path: Path | str) -> Lexicon:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    entries: list[LexEntry] = []
    seen: set[str] = set()
    for row in rows:
        key = canonical_term(row["term"])
        if not key or key in seen:
            continue
        seen.add(key)
        display = row.get("display") or title_case(display_term(row["term"]))
        entries.append(LexEntry(key=key, term=display_term(row["term"]), display=display))
    max_n = max((len(e.key.split()) for e in entries), default=1)
    return Lexicon(entries=entries, max_term_n=max_n)
