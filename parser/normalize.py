"""Text normalization: lowercasing, symbol-token rescue, chunking, and n-gram counting.

The same tokenization is applied to both the input text and the taxonomy lexicon
terms, so matching is consistent by construction.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

_STOPWORDS_PATH = Path(__file__).resolve().parent / "stopwords.txt"

# A handful of technical tokens that carry meaning but would otherwise be shredded
# by punctuation splitting. Mapped to alphabetic stand-ins *before* tokenizing, so
# they survive as single tokens in both text and lexicon terms.
_SUBSTITUTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"c\+\+"), " cplusplus "),
    (re.compile(r"f#"), " fsharp "),
    (re.compile(r"c#"), " csharp "),
    (re.compile(r"\.net\b"), " dotnet "),
    (re.compile(r"\bnode\.js\b"), " nodejs "),
    (re.compile(r"\bci\s*/\s*cd\b"), " cicd "),
]

# Any run of characters that is neither alphanumeric nor whitespace is a phrase
# boundary (sentence/clause punctuation, slashes, hyphens, etc.). Splitting on
# these keeps RAKE phrases and classifier n-grams from spanning unrelated terms.
_SEPARATOR_RE = re.compile(r"[^a-z0-9\s]+")


@lru_cache(maxsize=1)
def load_stopwords() -> frozenset[str]:
    """Load the static stopword set (cached for the process lifetime)."""
    words: set[str] = set()
    for line in _STOPWORDS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            words.add(line)
    return frozenset(words)


def _preprocess(text: str) -> str:
    text = text.lower()
    for pattern, replacement in _SUBSTITUTIONS:
        text = pattern.sub(replacement, text)
    return text


def to_chunks(text: str) -> list[list[str]]:
    """Split text into chunks at punctuation; each chunk is a list of tokens.

    Stopwords are *kept* so that multi-word lexicon terms and RAKE phrase
    boundaries are both representable from the same structure.
    """
    chunks: list[list[str]] = []
    for line in _preprocess(text).splitlines():
        for raw in _SEPARATOR_RE.split(line):
            tokens = raw.split()
            if tokens:
                chunks.append(tokens)
    return chunks


def tokenize(text: str) -> list[str]:
    """Flat token list (chunks flattened). Useful for counts and term normalization."""
    return [tok for chunk in to_chunks(text) for tok in chunk]


def normalize_term(term: str) -> str:
    """Normalize a lexicon term to the same space-joined token form the text uses."""
    return " ".join(tokenize(term))


def count_ngrams(chunks: list[list[str]], n_max: int = 3) -> Counter[str]:
    """Count contiguous 1..n_max-grams within each chunk (never across boundaries)."""
    counts: Counter[str] = Counter()
    for tokens in chunks:
        length = len(tokens)
        for n in range(1, n_max + 1):
            for i in range(length - n + 1):
                counts[" ".join(tokens[i : i + n])] += 1
    return counts
