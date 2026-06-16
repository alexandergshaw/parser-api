"""Flask application — Vercel entrypoint (WSGI).

Exposes the WSGI ``app`` that Vercel's @vercel/python builder mounts. Serves the
testing UI at ``/`` and the parse endpoint at ``/api/parse``. All heavy lifting
lives in the framework-agnostic ``parser`` package; this module is a thin HTTP shell.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the repo root is importable so the top-level `parser` package resolves
# regardless of the function's working directory on Vercel.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

from parser import __version__, parse
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

MAX_TEXT_CHARS = 50_000
API_KEY = os.environ.get("API_KEY", "").strip()
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
CONFIDENCE_THRESHOLD = float(
    os.environ.get("CONFIDENCE_THRESHOLD", DEFAULT_CONFIDENCE_THRESHOLD)
)

app = Flask(__name__)
app.json.sort_keys = False  # preserve the documented response key order
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


@app.before_request
def _require_api_key():
    """Enforce the shared secret on /api/parse when API_KEY is set; otherwise open."""
    if API_KEY and request.method == "POST" and request.path == "/api/parse":
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


@app.post("/api/parse")
def parse_text():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error(400, "Request body must be a JSON object.")

    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return _error(400, "`text` must be a non-empty string.")
    if len(text) > MAX_TEXT_CHARS:
        return _error(413, f"`text` exceeds the {MAX_TEXT_CHARS}-character limit.")

    max_keywords = body.get("max_keywords", DEFAULT_MAX_KEYWORDS)
    # bool is a subclass of int — reject it explicitly.
    if isinstance(max_keywords, bool) or not isinstance(max_keywords, int) or not 1 <= max_keywords <= 50:
        return _error(422, "`max_keywords` must be an integer between 1 and 50.")

    targets = body.get("targets")
    if targets is not None and not isinstance(targets, list):
        return _error(422, "`targets` must be an array of lens names.")

    try:
        result = parse(
            text,
            targets=targets,
            max_keywords=max_keywords,
            confidence_threshold=CONFIDENCE_THRESHOLD,
        )
    except ValueError as exc:  # unknown/empty target or malformed target item
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
