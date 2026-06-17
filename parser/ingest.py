"""File ingestion: extract plain text from uploaded files, deterministically and
without any LLM or network call — the file-aware front door to :func:`parse`.

Each supported format has a pure-Python extractor:

  - ``.txt`` / ``.md`` / ``.csv`` / …  -> decode bytes (UTF-8 with fallback)
  - ``.docx`` / ``.pptx`` / ``.xlsx``   -> OOXML zip; pull text runs via the stdlib
                                          (``zipfile`` + ``xml.etree``) — no lxml, no
                                          third-party Office libraries
  - ``.pdf``                            -> ``pypdf`` (pure-Python, the lone dependency)

The HTTP layer reads each request file part as ``(filename, bytes)`` and calls
:func:`combine`, which merges the optional inline ``text`` string and the files into
one document in a **fixed, deterministic order** (inline text first, then files
sorted by name) joined with blank lines. The merged string then flows through the
existing :func:`parser.parse` unchanged — files are a new front door, not a new
contract. Per-source outcomes are reported back as :class:`Source` records.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Guard against decompression bombs: refuse OOXML archives whose *uncompressed*
# payload is implausibly large for a document.
_MAX_UNCOMPRESSED = 64 * 1024 * 1024

# Plain-text extensions decoded as-is. Office binaries (.doc/.ppt/.xls) are the
# legacy OLE format and are intentionally unsupported (would need heavy deps).
_TEXT_EXTS = {".txt", ".text", ".md", ".markdown", ".csv", ".tsv", ".log", ".rst"}


@dataclass(frozen=True)
class Source:
    """One ingested input. ``text`` carries the extracted body (not serialized to
    the client); :meth:`to_meta` is the public, text-free summary for ``meta.sources``."""

    name: str
    kind: str
    chars: int
    ok: bool
    text: str = ""
    error: str | None = None

    def to_meta(self) -> dict:
        d: dict = {"name": self.name, "kind": self.kind, "chars": self.chars, "ok": self.ok}
        if self.error:
            d["error"] = self.error
        return d


def _kind_for(ext: str) -> str:
    return ext.lstrip(".") or "unknown"


def _decode(data: bytes) -> str:
    """Decode text bytes, tolerating a BOM and falling back to latin-1 (never raises)."""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


# ---- OOXML (docx / pptx / xlsx) — stdlib only ------------------------------

def _open_zip(data: bytes) -> zipfile.ZipFile:
    zf = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in zf.infolist()) > _MAX_UNCOMPRESSED:
        raise ValueError("archive too large when decompressed")
    return zf


def _local(tag: str) -> str:
    """Local element name with the XML namespace stripped (``{ns}t`` -> ``t``)."""
    return tag.rsplit("}", 1)[-1]


def _xml_text(data: bytes, text_tag: str = "t", para_tag: str = "p") -> str:
    """Concatenate text runs from an OOXML part, inserting a newline at each
    paragraph boundary. Works across docx (``w:t``/``w:p``), pptx (``a:t``/``a:p``),
    and xlsx shared strings (``t``/``si``) because we match on local names."""
    if not data:
        return ""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return ""
    parts: list[str] = []
    for el in root.iter():
        ln = _local(el.tag)
        if ln == para_tag:
            parts.append("\n")
        elif ln == text_tag and el.text:
            parts.append(el.text)
    return "".join(parts)


def _read(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        return zf.read(name)
    except KeyError:
        return b""


def _extract_docx(data: bytes) -> str:
    return _xml_text(_read(_open_zip(data), "word/document.xml"), "t", "p")


def _extract_pptx(data: bytes) -> str:
    zf = _open_zip(data)
    slides = [n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    slides.sort(key=lambda n: int(re.search(r"(\d+)", n).group(1)))  # slide2 before slide10
    return "\n".join(_xml_text(_read(zf, n), "t", "p") for n in slides)


def _extract_xlsx(data: bytes) -> str:
    return _xml_text(_read(_open_zip(data), "xl/sharedStrings.xml"), "t", "si")


# ---- PDF — pypdf (pure-Python) ---------------------------------------------

def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader  # imported lazily so non-PDF requests never pay for it

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        # Many PDFs are "encrypted" only with an empty owner password; try that.
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("encrypted PDF (password required)")
    return "\n".join((page.extract_text() or "") for page in reader.pages)


_EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".pptx": _extract_pptx,
    ".xlsx": _extract_xlsx,
}

# Extensions the parser knows how to read (for callers that want to advertise it).
SUPPORTED_EXTS = frozenset(_EXTRACTORS) | _TEXT_EXTS


def extract(name: str, data: bytes, *, max_file_bytes: int | None = None) -> Source:
    """Extract text from one file. Never raises — unreadable/unsupported/empty files
    come back as ``Source(ok=False, error=...)`` so one bad file can't sink the request."""
    ext = Path(name).suffix.lower()
    kind = _kind_for(ext)

    if max_file_bytes is not None and len(data) > max_file_bytes:
        return Source(name, kind, 0, False, error=f"file exceeds the {max_file_bytes}-byte limit")

    try:
        if ext in _EXTRACTORS:
            text = _EXTRACTORS[ext](data)
        elif ext in _TEXT_EXTS:
            text = _decode(data)
        else:
            return Source(name, kind, 0, False, error=f"unsupported file type '{ext or name}'")
    except ValueError as exc:  # our own guards (encrypted PDF, zip bomb, …)
        return Source(name, kind, 0, False, error=str(exc))
    except Exception as exc:  # corrupt/malformed file — soft-fail, never crash the request
        return Source(name, kind, 0, False, error=f"could not read file ({exc.__class__.__name__})")

    text = text.strip() if text else ""
    if not text:
        reason = (
            "no extractable text (possibly scanned/image-only)"
            if ext == ".pdf"
            else "no extractable text"
        )
        return Source(name, kind, 0, False, error=reason)
    return Source(name, kind, len(text), True, text=text)


def combine(
    text: str | None,
    files: list[tuple[str, bytes]],
    *,
    max_file_bytes: int | None = None,
) -> tuple[str, list[Source]]:
    """Merge the optional inline ``text`` and ``files`` into one document.

    Order is deterministic — inline text first, then files sorted by filename — so the
    same inputs always yield byte-identical merged output. Returns ``(merged, sources)``
    where ``sources`` describes every input (including failed ones) for ``meta.sources``.
    """
    sources: list[Source] = []
    if text and text.strip():
        body = text.strip()
        sources.append(Source("text", "text", len(body), True, text=body))
    for name, data in sorted(files, key=lambda f: f[0]):
        sources.append(extract(name, data, max_file_bytes=max_file_bytes))

    merged = "\n\n".join(s.text for s in sources if s.ok and s.text)
    return merged, sources
