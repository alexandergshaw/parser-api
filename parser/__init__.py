"""Parser API core library.

Deterministic, LLM-free extraction of a text's broad emphases (via curated taxonomy
+ lexicon scoring) and specific subtopics/keywords (via pure-Python RAKE).
"""

__version__ = "1.1.0"

from .pipeline import parse  # noqa: F401

__all__ = ["parse", "__version__"]
