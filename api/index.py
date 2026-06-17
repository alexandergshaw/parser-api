"""Flask application — Vercel entrypoint (WSGI).

Exposes the WSGI ``app`` that Vercel's @vercel/python builder mounts. Serves the
testing UI at ``/`` and the parse endpoint at ``/api/parse``. All heavy lifting
lives in the framework-agnostic ``parser`` package; this module is a thin HTTP shell.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure the repo root is importable so the top-level `parser` package resolves
# regardless of the function's working directory on Vercel.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

from parser import __version__, parse
from parser.aggregate import aggregate, records_from_csv
from parser.ingest import combine
from parser.lenses import get_lenses
from parser.pipeline import DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_MAX_KEYWORDS
from parser.taxonomy import get_taxonomy

# On Vercel the function's working directory and bundled-file layout can vary, so
# resolve bundled assets by probing the likely roots rather than assuming one.
_CANDIDATE_ROOTS = [
    Path(__file__).resolve().parent.parent,  # repo root (api/..)
    Path.cwd(),
    Path("/var/task"),                        # Vercel / Lambda task root
]


def _asset(rel: str) -> Path:
    for root in _CANDIDATE_ROOTS:
        candidate = root / rel
        if candidate.exists():
            return candidate
    return _CANDIDATE_ROOTS[0] / rel


# NB: assets live in web/ (NOT public/) — Vercel reserves public/ for static
# output and excludes it from the serverless function bundle.
_UI_PATH = _asset("web/index.html")
_JS_PATH = _asset("web/app.js")
_OPENAPI_PATH = _asset("web/openapi.json")

# Applies to the *combined* extracted text (inline string + all files merged).
# Raised well above the old text-only 50k because a single PDF/deck easily exceeds it.
MAX_COMBINED_CHARS = int(os.environ.get("MAX_COMBINED_CHARS", 200_000))
MAX_FILES = int(os.environ.get("MAX_FILES", 20))
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", 10 * 1024 * 1024))  # 10 MB / file
# Whole-request ceiling (memory guard). NB: Vercel caps serverless bodies at ~4.5 MB,
# below this — large uploads may be rejected by the platform before reaching the app.
MAX_TOTAL_UPLOAD_BYTES = int(os.environ.get("MAX_TOTAL_UPLOAD_BYTES", 16 * 1024 * 1024))

API_KEY = os.environ.get("API_KEY", "").strip()
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
CONFIDENCE_THRESHOLD = float(
    os.environ.get("CONFIDENCE_THRESHOLD", DEFAULT_CONFIDENCE_THRESHOLD)
)

app = Flask(__name__)
app.json.sort_keys = False  # preserve the documented response key order
app.config["MAX_CONTENT_LENGTH"] = MAX_TOTAL_UPLOAD_BYTES  # Flask 413s oversized bodies
CORS(
    app,
    resources={r"/*": {"origins": ALLOWED_ORIGINS}},
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# Build + cache the taxonomy and lens registry at import (cold start).
get_taxonomy()
get_lenses()


def _error(status: int, detail: str):
    return jsonify({"detail": detail}), status


_PROTECTED_POSTS = {"/api/parse", "/api/aggregate"}


@app.before_request
def _require_api_key():
    """Enforce the shared secret on the POST endpoints when API_KEY is set; else open."""
    if API_KEY and request.method == "POST" and request.path in _PROTECTED_POSTS:
        if request.headers.get("X-API-Key") != API_KEY:
            return _error(401, "Invalid or missing API key.")
    return None


@app.get("/api/health")
def health():
    tax = get_taxonomy()
    return jsonify({"status": "ok", "version": __version__, "categories": len(tax.categories)})


@app.get("/api/taxonomy")
def taxonomy():
    """Enumerate the controlled vocabulary so consumers can discover it dynamically."""
    tax = get_taxonomy()
    categories = sorted(
        ({"id": c.id, "label": c.label, "type": c.type} for c in tax.categories),
        key=lambda c: (c["type"], c["label"]),
    )
    return jsonify({"version": __version__, "count": len(categories), "categories": categories})


@app.get("/api/lenses")
def lenses():
    """Enumerate the available extraction lenses a caller can request via `targets`."""
    reg = get_lenses()
    return jsonify(
        {
            "version": __version__,
            "lenses": [
                {"name": l.name, "kind": l.kind, "default": l.default} for l in reg.values()
            ],
        }
    )


_MAX_KW_ERROR = "`max_keywords` must be an integer between 1 and 50."


def _coerce_max_keywords(raw):
    """Validate max_keywords from JSON (int) or a multipart form field (str).
    Returns (value, error) — error is a string only when invalid."""
    if raw is None or raw == "":
        return DEFAULT_MAX_KEYWORDS, None
    if isinstance(raw, str):
        try:
            raw = int(raw)
        except ValueError:
            return None, _MAX_KW_ERROR
    # bool is a subclass of int — reject it explicitly.
    if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 50:
        return None, _MAX_KW_ERROR
    return raw, None


_TRUE_FORM = {"1", "true", "yes", "on"}


def _coerce_bool_form(raw: str | None) -> bool:
    """A multipart boolean field — anything truthy ('1', 'true', 'yes', 'on') is True."""
    return bool(raw) and str(raw).strip().lower() in _TRUE_FORM


def _coerce_targets_form(raw: str | None):
    """A multipart `targets` field may be a JSON array string or a comma list."""
    if not raw or not raw.strip():
        return None
    s = raw.strip()
    if s.startswith("["):
        try:
            v = json.loads(s)
            if isinstance(v, list):
                return v
        except ValueError:
            pass
    return [t.strip() for t in s.split(",") if t.strip()]


@app.post("/api/parse")
def parse_text():
    """Parse an inline string and/or uploaded files (any subset; all optional).

    Accepts `application/json` (`{text, targets, max_keywords}`, back-compatible) or
    `multipart/form-data` (`text`/`targets`/`max_keywords` fields + `files` parts).
    Everything submitted is merged into one document and run through the same pipeline.
    """
    content_type = (request.content_type or "").split(";")[0].strip().lower()

    if content_type == "multipart/form-data":
        text = request.form.get("text") or ""
        targets = _coerce_targets_form(request.form.get("targets"))
        max_keywords, kw_err = _coerce_max_keywords(request.form.get("max_keywords"))
        uploads = [fs for fs in request.files.getlist("files") if fs and fs.filename]
        if len(uploads) > MAX_FILES:
            return _error(422, f"Too many files (max {MAX_FILES}).")
        files = [(fs.filename, fs.read()) for fs in uploads]
    else:
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        elif not isinstance(body, dict):
            return _error(400, "Request body must be a JSON object.")
        text = body.get("text") or ""
        if not isinstance(text, str):
            return _error(400, "`text` must be a string.")
        targets = body.get("targets")
        if targets is not None and not isinstance(targets, list):
            return _error(422, "`targets` must be an array of lens names.")
        max_keywords, kw_err = _coerce_max_keywords(body.get("max_keywords"))
        files = []

    if kw_err:
        return _error(422, kw_err)

    merged, sources = combine(text, files, max_file_bytes=MAX_FILE_BYTES)

    if not merged.strip():
        if not (text and text.strip()) and not files:
            return _error(400, "Provide `text` and/or at least one file.")
        detail = "; ".join(f"{s.name}: {s.error}" for s in sources if not s.ok and s.error)
        return _error(422, f"No extractable text from the provided input(s). {detail}".strip())
    if len(merged) > MAX_COMBINED_CHARS:
        return _error(413, f"Combined text exceeds the {MAX_COMBINED_CHARS}-character limit.")

    try:
        result = parse(
            merged,
            targets=targets,
            max_keywords=max_keywords,
            confidence_threshold=CONFIDENCE_THRESHOLD,
        )
    except ValueError as exc:  # unknown/empty target or malformed target item
        return _error(422, str(exc))
    result["meta"]["sources"] = [s.to_meta() for s in sources]
    return jsonify(result)


@app.post("/api/aggregate")
def aggregate_records():
    """Summarize a set of records into per-field statistics.

    Accepts `application/json` (`{records, fields}`) or `multipart/form-data` (a
    single CSV/TSV `file` + optional `fields`). Numeric fields return
    mean/median/min/max/stdev/quartiles; categorical fields return value
    frequencies. `fields` is restrictive — omit it to summarize every field.
    """
    content_type = (request.content_type or "").split(";")[0].strip().lower()

    if content_type == "multipart/form-data":
        uploads = [fs for fs in request.files.getlist("file") if fs and fs.filename]
        if not uploads:
            return _error(400, "Provide a CSV/TSV `file` (or POST JSON with `records`).")
        if len(uploads) > 1:
            return _error(422, "Provide a single tabular `file`.")
        raw = uploads[0].read()
        if len(raw) > MAX_FILE_BYTES:
            return _error(413, f"File exceeds the {MAX_FILE_BYTES}-byte limit.")
        records = records_from_csv(raw)
        fields = _coerce_targets_form(request.form.get("fields"))
        casefold = _coerce_bool_form(request.form.get("casefold"))
    else:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _error(400, "Request body must be a JSON object with `records`.")
        records = body.get("records")
        if records is None:
            return _error(400, "Provide `records` (a non-empty array of objects).")
        fields = body.get("fields")
        if fields is not None and not isinstance(fields, list):
            return _error(422, "`fields` must be an array of field names.")
        casefold = body.get("casefold", False)
        if not isinstance(casefold, bool):
            return _error(422, "`casefold` must be a boolean.")

    try:
        result = aggregate(records, fields=fields, casefold=casefold)
    except ValueError as exc:  # malformed records, empty input, or unknown field
        return _error(422, str(exc))
    return jsonify(result)


@app.get("/openapi.json")
def openapi():
    if _OPENAPI_PATH.exists():
        return Response(_OPENAPI_PATH.read_text(encoding="utf-8"), mimetype="application/json")
    return _error(404, "OpenAPI schema not found.")


_SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Parser API — Docs</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => SwaggerUIBundle({ url: "/openapi.json", dom_id: "#swagger-ui" });
  </script>
</body>
</html>"""


@app.get("/docs")
def docs():
    return Response(_SWAGGER_HTML, mimetype="text/html")


@app.get("/")
def ui():
    if not _UI_PATH.exists():
        return Response("<h1>Parser API</h1><p>See <a href='/docs'>/docs</a>.</p>", mimetype="text/html")
    return Response(_UI_PATH.read_text(encoding="utf-8"), mimetype="text/html")


@app.get("/app.js")
def app_js():
    if not _JS_PATH.exists():
        return _error(404, "app.js not found.")
    return Response(_JS_PATH.read_text(encoding="utf-8"), mimetype="text/javascript")


@app.errorhandler(404)
def _not_found(_e):
    return _error(404, "Not found.")


@app.errorhandler(405)
def _method_not_allowed(_e):
    return _error(405, "Method not allowed.")


@app.errorhandler(413)
def _too_large(_e):
    return _error(413, f"Request body exceeds the {MAX_TOTAL_UPLOAD_BYTES}-byte limit.")
