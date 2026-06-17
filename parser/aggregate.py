"""Deterministic statistical aggregation over a set of records.

A second, non-text front door to the service. Where :func:`parser.parse` reads a
block of prose, :func:`aggregate` reads a *series of records* — job postings,
student-survey rows, … — and returns summary statistics over targeted fields:
means/medians/quartiles for numbers, frequency distributions for categories.

Like the rest of the API it is pure-Python, deterministic, and LLM-free: the same
records always yield byte-identical output (ties broken by stable sort keys).

A field's *kind* is inferred from its values — if (almost) every present value
parses as a number the field is ``numeric``; otherwise it is ``categorical``. The
caller can override per field via ``{"name": ..., "type": "numeric"|"categorical"}``
and cap a category list with ``"limit"`` (mirroring ``parse``'s ``targets``).
"""

from __future__ import annotations

import csv
import io
import statistics
from typing import Any

# Sentinels treated as "missing" (case-insensitive), in addition to None and any
# blank/whitespace-only string. Kept conservative on purpose: common survey "no
# answer" markers only, so a real category like "None of the above" survives.
_NA_TOKENS = {"", "na", "n/a", "null", "nan"}

# Auto-detect a field as numeric when at least this share of its *present* values
# parse as numbers; otherwise it is categorical.
_NUMERIC_DETECT_RATIO = 0.8

# Currency / grouping / percent glyphs stripped before a numeric parse attempt,
# so "$85,000" and "12%" read as 85000 and 12.
_NUM_STRIP = str.maketrans("", "", "$,%")

# Decimal places for derived floats (means, stdev, quartiles, proportions). Raw
# observed values (min/max/sum) are not rounded.
_NDIGITS = 4


def _round(x: float | None, ndigits: int = _NDIGITS) -> Any:
    """Round, returning an int for integral results so output is clean (50000, not
    50000.0) while genuine fractions (84210.5) stay floats. ``None`` passes through."""
    if x is None:
        return None
    r = round(float(x), ndigits)
    return int(r) if r == int(r) else r


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _NA_TOKENS
    return False


def _to_number(value: Any) -> float | None:
    """Coerce a value to float, or None if it isn't number-like. Booleans are NOT
    numbers here — a true/false column is treated as categorical."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().translate(_NUM_STRIP).strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _classify_field(values: list[Any]) -> str:
    """Return 'numeric', 'categorical', or 'empty' for a column of raw values."""
    present = [v for v in values if not _is_missing(v)]
    if not present:
        return "empty"
    numeric = sum(1 for v in present if _to_number(v) is not None)
    return "numeric" if numeric / len(present) >= _NUMERIC_DETECT_RATIO else "categorical"


def _numeric_stats(values: list[Any]) -> dict[str, Any]:
    present = [v for v in values if not _is_missing(v)]
    nums: list[float] = []
    invalid = 0
    for v in present:
        n = _to_number(v)
        if n is None:
            invalid += 1  # present but unparseable (e.g. "TBD" in a salary column)
        else:
            nums.append(n)

    stats: dict[str, Any] = {
        "kind": "numeric",
        "count": len(nums),
        "missing": len(values) - len(present),
        "invalid": invalid,
    }
    if not nums:
        stats.update(dict.fromkeys(
            ("mean", "median", "min", "max", "sum", "stdev", "p25", "p75"), None
        ))
        return stats

    stats.update(
        mean=_round(statistics.fmean(nums)),
        median=_round(statistics.median(nums)),
        min=_round(min(nums)),
        max=_round(max(nums)),
        sum=_round(sum(nums)),
        stdev=_round(statistics.stdev(nums)) if len(nums) >= 2 else None,
    )
    if len(nums) >= 2:
        p25, _p50, p75 = statistics.quantiles(nums, n=4)  # exclusive quartiles
        stats["p25"], stats["p75"] = _round(p25), _round(p75)
    else:
        stats["p25"] = stats["p75"] = None
    return stats


def _categorical_stats(values: list[Any], limit: int | None, casefold: bool) -> dict[str, Any]:
    present = [v for v in values if not _is_missing(v)]
    counts: dict[str, int] = {}
    for v in present:
        key = v.strip() if isinstance(v, str) else str(v)
        if casefold:
            key = key.casefold()  # merge "Employed"/"employed"; reported value is folded
        counts[key] = counts.get(key, 0) + 1

    total = len(present)
    # Most frequent first; ties broken alphabetically so output is deterministic.
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    frequencies = [
        {"value": val, "count": c, "proportion": _round(c / total)}
        for val, c in ordered
    ]
    stats: dict[str, Any] = {
        "kind": "categorical",
        "count": total,
        "missing": len(values) - len(present),
        "distinct": len(counts),
        "mode": ordered[0][0] if ordered else None,
    }
    if limit is not None and len(frequencies) > limit:
        stats["frequencies"] = frequencies[:limit]
        stats["truncated"] = True  # `distinct` still reflects the full cardinality
    else:
        stats["frequencies"] = frequencies
    return stats


# A planned field: (name, forced_type, limit, casefold). `casefold` is None when the
# field doesn't override the request-level default.
_Field = tuple[str, "str | None", "int | None", "bool | None"]


def _normalize_fields(fields: Any) -> list[_Field] | None:
    """Normalize `fields` to [(name, forced_type, limit, casefold)], or None for 'all fields'."""
    if fields is None:
        return None
    out: list[_Field] = []
    for f in fields:
        if isinstance(f, str):
            out.append((f, None, None, None))
        elif isinstance(f, dict) and isinstance(f.get("name"), str):
            ftype = f.get("type")
            if ftype is not None and ftype not in ("numeric", "categorical"):
                raise ValueError("Field `type` must be 'numeric' or 'categorical'.")
            cf = f.get("casefold")
            if cf is not None and not isinstance(cf, bool):
                raise ValueError("Field `casefold` must be a boolean.")
            limit = f.get("limit")
            out.append((f["name"], ftype, limit if isinstance(limit, int) else None, cf))
        else:
            raise ValueError("Each field must be a name or an object {name, type?, limit?, casefold?}.")
    if not out:
        raise ValueError("`fields` must be a non-empty array.")
    return out


def aggregate(records: Any, fields: Any = None, casefold: bool = False) -> dict[str, Any]:
    """Summarize `records` (a list of dict rows) into per-field statistics.

    `fields` is restrictive, like ``parse``'s ``targets``:
      * ``None``        → every field seen across the records (first-seen order), auto-typed
      * ``["salary"]``  → only those fields, auto-typed
      * ``[{"name": "salary", "type": "numeric", "limit": 10}]`` → force kind / cap categories

    `casefold` folds categorical values case-insensitively (so "Employed"/"employed"
    merge) for every field; a field may override it via ``{"casefold": true|false}``.

    Raises ``ValueError`` on malformed input or an unknown field name (the HTTP
    layer maps that to a 422).
    """
    from . import __version__

    if not isinstance(records, list):
        raise ValueError("`records` must be an array of objects.")
    if not records:
        raise ValueError("`records` must contain at least one record.")
    if not isinstance(casefold, bool):
        raise ValueError("`casefold` must be a boolean.")
    for r in records:
        if not isinstance(r, dict):
            raise ValueError("Every record must be a JSON object.")

    # Columns in first-seen order across all records (deterministic, union of keys).
    seen: set[str] = set()
    all_keys: list[str] = []
    for r in records:
        for k in r:
            if k not in seen:
                seen.add(k)
                all_keys.append(k)

    requested = _normalize_fields(fields)
    if requested is None:
        plan: list[_Field] = [(k, None, None, None) for k in all_keys]
    else:
        unknown = [name for name, *_ in requested if name not in seen]
        if unknown:
            raise ValueError(f"Unknown field(s): {', '.join(unknown)}.")
        plan = requested

    results: dict[str, Any] = {}
    for name, forced, limit, cf in plan:
        values = [r.get(name) for r in records]
        kind = forced or _classify_field(values)
        if kind == "numeric":
            results[name] = _numeric_stats(values)
        elif kind == "empty":
            results[name] = {"kind": "empty", "count": 0, "missing": len(values)}
        else:
            results[name] = _categorical_stats(values, limit, casefold if cf is None else cf)

    return {
        "results": results,
        "meta": {
            "records": len(records),
            "fields_analyzed": len(results),
            "version": __version__,
        },
    }


# ---- CSV / TSV front door --------------------------------------------------

def _decode(data: bytes) -> str:
    """Decode tabular bytes, tolerating a BOM, falling back to latin-1 (never raises)."""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def records_from_csv(data: str | bytes) -> list[dict[str, Any]]:
    """Parse CSV/TSV text (header row = field names) into a list of row dicts.

    The delimiter is sniffed (comma / tab / semicolon) so survey exports work as-is.
    Values stay strings — numeric detection in :func:`aggregate` handles coercion.
    """
    text = _decode(data) if isinstance(data, (bytes, bytearray)) else data
    if not text.strip():
        return []
    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel  # default to comma when the sniff is inconclusive
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    records: list[dict[str, Any]] = []
    for row in reader:
        row.pop(None, None)  # drop overflow columns DictReader files under None
        records.append({k: v for k, v in row.items() if k is not None})
    return records
