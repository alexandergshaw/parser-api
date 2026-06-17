"""Tests for parser.ingest — file extraction + deterministic merge.

Fixtures are built in-process (OOXML is just a zip of XML; PDF is hand-assembled
with a valid xref) so the suite needs no committed binary files.
"""

import io
import zipfile

from parser.ingest import SUPPORTED_EXTS, Source, combine, extract

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return buf.getvalue()


def _docx(text: str) -> bytes:
    doc = (
        f'<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>'
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    return _zip({"word/document.xml": doc})


def _slide(text: str) -> str:
    return (
        f'<?xml version="1.0"?><p:sld xmlns:p="ppt" xmlns:a="{A_NS}">'
        f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>"
    )


def _pptx(slides: dict[int, str]) -> bytes:
    return _zip({f"ppt/slides/slide{n}.xml": _slide(t) for n, t in slides.items()})


def _xlsx(strings: list[str]) -> bytes:
    items = "".join(f"<si><t>{s}</t></si>" for s in strings)
    return _zip({"xl/sharedStrings.xml": f'<?xml version="1.0"?><sst xmlns="x">{items}</sst>'})


def _pdf(text: str) -> bytes:
    """Minimal single-page PDF with correct xref offsets, text in a Tj operator."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = b"BT /F1 24 Tf 72 700 Td (" + text.encode("latin-1") + b") Tj ET"
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    )
    return bytes(out)


# ---- plain text ------------------------------------------------------------

def test_extract_txt():
    s = extract("notes.txt", b"Build ETL pipelines with Spark and Python")
    assert s.ok and s.kind == "txt" and "Spark" in s.text and s.chars == len(s.text)


def test_extract_txt_decodes_latin1_fallback():
    s = extract("n.txt", "café résumé".encode("latin-1"))
    assert s.ok and "caf" in s.text  # never raises on odd encodings


def test_unsupported_extension_soft_fails():
    s = extract("legacy.doc", b"\xd0\xcf\x11\xe0binary")  # OLE magic
    assert not s.ok and "unsupported" in s.error and s.chars == 0


# ---- OOXML -----------------------------------------------------------------

def test_extract_docx():
    s = extract("report.docx", _docx("Machine learning and neural networks"))
    assert s.ok and s.kind == "docx" and "neural networks" in s.text


def test_extract_pptx_slides_in_numeric_order():
    # slide10 must come AFTER slide2, not after slide1 (numeric, not lexical).
    s = extract("deck.pptx", _pptx({1: "Alpha", 2: "Beta", 10: "Gamma"}))
    assert s.ok and s.kind == "pptx"
    assert s.text.index("Alpha") < s.text.index("Beta") < s.text.index("Gamma")


def test_extract_xlsx_shared_strings():
    s = extract("data.xlsx", _xlsx(["Revenue", "Forecast", "Q3"]))
    assert s.ok and s.kind == "xlsx" and "Forecast" in s.text


def test_corrupt_ooxml_soft_fails():
    s = extract("broken.docx", b"not a zip at all")
    assert not s.ok and "could not read file" in s.error


# ---- PDF -------------------------------------------------------------------

def test_extract_pdf():
    s = extract("paper.pdf", _pdf("Spark Python Airflow"))
    assert s.ok and s.kind == "pdf" and "Spark" in s.text


def test_empty_pdf_reports_scanned_hint():
    s = extract("scan.pdf", _pdf(" "))
    assert not s.ok and "scanned" in s.error


# ---- limits ----------------------------------------------------------------

def test_max_file_bytes_enforced():
    s = extract("big.txt", b"x" * 100, max_file_bytes=10)
    assert not s.ok and "exceeds" in s.error


# ---- combine (merge + determinism) -----------------------------------------

def test_combine_order_is_text_then_files_sorted():
    text = "Inline note about Kafka"
    files = [("zeta.txt", b"Zeta body"), ("alpha.txt", b"Alpha body")]
    merged, sources = combine(text, files)
    # inline text first, then files alphabetical regardless of submission order
    assert merged.index("Inline") < merged.index("Alpha body") < merged.index("Zeta body")
    assert [s.name for s in sources] == ["text", "alpha.txt", "zeta.txt"]


def test_combine_is_deterministic():
    files = [("b.txt", b"Beta"), ("a.txt", b"Alpha")]
    assert combine("hi", files)[0] == combine("hi", list(reversed(files)))[0]


def test_combine_skips_failed_but_lists_them():
    merged, sources = combine(None, [("a.txt", b"Keep me"), ("x.doc", b"drop")])
    assert "Keep me" in merged and "drop" not in merged
    assert {s.name: s.ok for s in sources} == {"a.txt": True, "x.doc": False}


def test_combine_blank_text_not_listed():
    merged, sources = combine("   ", [("a.txt", b"Body")])
    assert [s.name for s in sources] == ["a.txt"]  # blank inline text contributes nothing


def test_to_meta_omits_text_and_includes_error():
    ok = Source("a.txt", "txt", 4, True, text="body").to_meta()
    assert ok == {"name": "a.txt", "kind": "txt", "chars": 4, "ok": True}  # no `text`
    bad = Source("x.doc", "doc", 0, False, error="unsupported").to_meta()
    assert bad["error"] == "unsupported" and bad["ok"] is False


def test_supported_exts_advertised():
    assert {".pdf", ".docx", ".pptx", ".txt"} <= SUPPORTED_EXTS
