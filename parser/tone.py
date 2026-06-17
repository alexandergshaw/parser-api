"""Tone lens — a multi-dimensional, deterministic tone profile.

Each dimension is scored from cue lexicons over the document. Dimensions are
data-driven (taxonomy/lexicons/tones.json), so adding a tone is a data-only edit.
Bipolar dimensions (formal↔casual) report a leaning; unipolar ones (urgency) report
intensity. No LLM — the `evidence` array always shows which cue words drove a score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .normalize import canonical_term, singularize

_NEGATORS = {"not", "no", "never", "without", "lack", "lacks", "cannot"}
_UNIPOLAR_SATURATION = 2.0  # score = hits / (hits + this)
_MAX_EVIDENCE = 6
# Note: ALL-CAPS is intentionally NOT used as an urgency signal — acronyms
# (ETL, SQL, AWS) are common in real text and would inflate it.


@dataclass
class ToneDimension:
    name: str
    label: str
    high_label: str
    low_label: str | None     # None => unipolar (intensity only)
    high: dict[str, str]      # canonical key -> cue display
    low: dict[str, str]

    @property
    def bipolar(self) -> bool:
        return self.low_label is not None


@dataclass
class ToneModel:
    dimensions: list[ToneDimension]
    max_term_n: int


def _keymap(terms: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for term in terms:
        key = canonical_term(term)
        if key and key not in out:
            out[key] = term
    return out


def load_tones(path: Path | str) -> ToneModel:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    dims: list[ToneDimension] = []
    max_n = 1
    for row in rows:
        high, low = _keymap(row.get("high", [])), _keymap(row.get("low", []))
        dims.append(
            ToneDimension(
                name=row["name"],
                label=row["label"],
                high_label=row.get("high_label", row["name"]),
                low_label=row.get("low_label"),
                high=high,
                low=low,
            )
        )
        for key in list(high) + list(low):
            max_n = max(max_n, len(key.split()))
    return ToneModel(dimensions=dims, max_term_n=max_n)


def _evidence(cues: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for c in cues:
        if c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) >= _MAX_EVIDENCE:
            break
    return out


def score_tone(model: ToneModel, ngram_counts, chunks: list[list[str]], text: str) -> dict[str, Any]:
    """Score each tone dimension. Deterministic; reuses the document's n-gram counts."""
    stemmed = [[singularize(tok) for tok in chunk] for chunk in chunks]
    exclamations = text.count("!")

    dimensions = []
    for dim in model.dimensions:
        high_uni = {k: v for k, v in dim.high.items() if " " not in k}
        low_uni = {k: v for k, v in dim.low.items() if " " not in k}
        H = L = 0.0
        ev_high: list[str] = []
        ev_low: list[str] = []

        # Unigram cues — positional scan with light negation (bipolar only).
        for toks in stemmed:
            for i, tok in enumerate(toks):
                negated = dim.bipolar and any(toks[j] in _NEGATORS for j in range(max(0, i - 2), i))
                if tok in high_uni:
                    if negated:
                        L += 1; ev_low.append(high_uni[tok])
                    else:
                        H += 1; ev_high.append(high_uni[tok])
                elif tok in low_uni:
                    if negated:
                        H += 1; ev_high.append(low_uni[tok])
                    else:
                        L += 1; ev_low.append(low_uni[tok])

        # Multiword cues — bag match (no negation).
        for key, disp in dim.high.items():
            if " " in key and ngram_counts.get(key, 0):
                H += ngram_counts[key]; ev_high.append(disp)
        for key, disp in dim.low.items():
            if " " in key and ngram_counts.get(key, 0):
                L += ngram_counts[key]; ev_low.append(disp)

        # Light heuristic: exclamation marks read as enthusiasm.
        if dim.name == "enthusiasm" and exclamations:
            H += min(exclamations, 3)

        if dim.bipolar:
            total = H + L
            score = round(H / total, 4) if total else 0.5
            leaning = dim.high_label if score > 0.55 else dim.low_label if score < 0.45 else "neutral"
            evidence = _evidence(ev_high if score >= 0.5 else ev_low)
        else:
            score = round(H / (H + _UNIPOLAR_SATURATION), 4) if H else 0.0
            leaning = dim.high_label if score >= 0.33 else "neutral"
            evidence = _evidence(ev_high)

        dimensions.append(
            {"name": dim.name, "label": dim.label, "score": score, "leaning": leaning, "evidence": evidence}
        )

    return {"kind": "tone", "dimensions": dimensions}
