# Parser API

The first service in an **LLM-alternative ecosystem**. It ingests text — as an inline string
and/or uploaded files (**pdf, pptx, docx, xlsx, txt, md, csv, …**) — and returns — **without any
LLM**, fully deterministically — structured extractions organized by **lenses** the caller chooses.

You pass which lenses to apply (`targets`); the API returns a result per lens:

- **emphasis** lenses (e.g. `field`, `sector`, `intent`) rank a curated taxonomy axis → the document's
  topic / industry / communicative goal, each with the `matched_terms` that produced it.
- **lexicon** lenses (e.g. `technologies`) report which terms from a curated list appear, each linked
  to the document's relevant emphasis.
- **keywords** lens returns unsupervised RAKE keyphrases lifted from *this* document.
- **tone** lens returns a multi-dimensional tone profile (formality, sentiment, urgency, enthusiasm).

The downstream **researcher API** consumes these: emphases drive general research; keywords and
detected technologies drive deep-dive research.

## How it works

```
text + files ─► ingest (pdf/docx/pptx/xlsx/txt ─► text) ─► merge ─► normalize (tokenize, stem, n-grams)
          ├─ emphasis lenses ─ per-axis lexicon scoring over taxonomy/*.json ─► top + ranked
          ├─ lexicon lenses  ─ curated term lists in taxonomy/lexicons/      ─► matched terms
          └─ keywords lens   ─ pure-Python RAKE                              ─► keyphrases
                                       results keyed by requested lens (+ meta.sources) ─► JSON
```

- **No LLM, no training data, no network calls.** Deterministic and explainable — every emphasis
  ships the `matched_terms` that produced it.
- **Everything is data-driven.** Categories in `taxonomy/fields.json` / `sectors.json`; lenses in
  `taxonomy/lenses.json`; lexicons in `taxonomy/lexicons/`. New coverage = edit data, not code.
- **Pure-Python** (RAKE + lexicon scoring) — no NLP dependencies, tiny bundle, fast cold starts.
- **Light stemming** so plurals match; **display casing** preserved (`term` lowercased for joins,
  `display` for humans); keywords/technologies **link to their parent emphasis** via `related`.

## Project layout

| Path | Purpose |
| --- | --- |
| `api/index.py` | Flask app — Vercel entrypoint, `/api/parse`, serves the testing UI at `/` |
| `parser/` | Framework-agnostic core (lenses, per-axis scoring, RAKE) |
| `parser/ingest.py` | File → text extraction (pdf via pypdf; docx/pptx/xlsx via stdlib) + deterministic merge |
| `taxonomy/` | `fields.json`, `sectors.json`, `lenses.json`, `lexicons/technologies.json` |
| `web/index.html`, `web/app.js` | Lens-agnostic testing UI (served by the function; not in reserved `public/`) |
| `tests/` | pytest suite |

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (use: source .venv/bin/activate on macOS/Linux)
pip install -r requirements-dev.txt

flask --app api.index run       # → http://127.0.0.1:5000  (UI at /, docs at /docs)
pytest                          # run the test suite
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/parse` | Parse an inline string and/or uploaded files into lens-keyed results |
| `POST` | `/api/aggregate` | Summarize a set of records (JSON or CSV) into per-field statistics |
| `GET` | `/api/lenses` | Discover available lenses (what `targets` accepts) |
| `GET` | `/api/taxonomy` | Enumerate the emphasis vocabulary (`{id, label, type}`) |
| `GET` | `/api/health` | Liveness, version, taxonomy size |
| `GET` | `/docs`, `/openapi.json` | Swagger UI + machine-readable schema |

```jsonc
// POST /api/parse — request (application/json, text only)
{ "text": "…", "targets": ["field", "technologies"], "max_keywords": 15 }
// `targets` is optional (omit → default lenses) and RESTRICTIVE — only those lenses are returned.

// Response 200 — keyed by the requested lenses
{
  "results": {
    "field": {
      "kind": "emphasis",
      "top":    { "id": "data_science", "label": "Data Science", "score": 0.88,
                  "matched_terms": ["ETL", "Spark", "SQL"], "low_confidence": false },
      "ranked": [ /* categories of this axis, scores sum to ~1 */ ]
    },
    "technologies": {
      "kind": "lexicon",
      "matched": [ { "term": "spark", "display": "Spark",
                     "related": { "id": "data_science", "label": "Data Science" } } ]
    }
  },
  // `meta.sources` lists what was ingested (the inline `text` + each file).
  "meta": { "token_count": 26, "version": "1.4.0",
            "sources": [ { "name": "text", "kind": "text", "chars": 142, "ok": true } ] }
}
```

### Inputs: text and/or files

`text` and files are both optional; submit any subset and the parser parses the union. Everything is
merged into one document in a deterministic order — **inline `text` first, then files sorted by name**
— and run through the same pipeline. `meta.sources` reports each input (a failed file appears with
`ok:false` and an `error`, and is simply skipped — one bad file never sinks the request).

```bash
# multipart/form-data — files (repeat `files` per file) + optional text/targets
curl -s {BASE_URL}/api/parse \
  -F files=@lecture3.pptx \
  -F files=@chapter.pdf \
  -F 'text=Intro framing for the deck' \
  -F 'targets=["field","intent","keywords"]'
```

| Format | How it's read |
| --- | --- |
| `.txt` `.md` `.csv` `.tsv` `.log` `.rst` | decoded as text (UTF-8 with fallback) |
| `.docx` `.pptx` `.xlsx` | stdlib `zipfile` + `xml.etree` (OOXML) — no `lxml`/Office libs |
| `.pdf` | `pypdf` (pure-Python). Scanned/image-only PDFs yield no text (no OCR) |

Not supported: legacy binary `.doc`/`.ppt`/`.xls` (OLE) and OCR of image-only PDFs. Limits
(`MAX_COMBINED_CHARS`, `MAX_FILES`, `MAX_FILE_BYTES`, `MAX_TOTAL_UPLOAD_BYTES`) are configurable —
see below. On Vercel, note the platform's ~4.5 MB serverless body cap.

### Aggregating records (`/api/aggregate`)

A second front door that takes **structured records** instead of prose — job postings, student-survey
rows, … — and returns summary statistics over targeted fields. Same deterministic, LLM-free contract;
same `{results, meta}` shape, keyed by field instead of lens.

Each field's *kind* is inferred from its values: mostly numbers → **numeric** (mean/median/min/max/
stdev/quartiles); otherwise → **categorical** (value frequencies, mode, proportions). So a salary
column gets descriptive stats while a "placement after graduation" column gets a distribution. Like
`targets`, `fields` is **restrictive** — omit it to summarize every field. Force a kind or cap a
category list per field with `{ "name": …, "type": "numeric"|"categorical", "limit": N }`.

```jsonc
// POST /api/aggregate — request (application/json)
{
  "records": [
    { "placement": "Employed",    "salary": "85000" },
    { "placement": "Employed",    "salary": "95000" },
    { "placement": "Grad school", "salary": "" }
  ],
  "fields": ["salary", "placement"]   // optional; omit → every field
}

// Response 200 — keyed by field
{
  "results": {
    "salary":    { "kind": "numeric", "count": 2, "missing": 1, "invalid": 0,
                   "mean": 90000, "median": 90000, "min": 85000, "max": 95000,
                   "sum": 180000, "stdev": 7071.0678, "p25": 82500, "p75": 97500 },
    "placement": { "kind": "categorical", "count": 3, "missing": 0, "distinct": 2,
                   "mode": "Employed",
                   "frequencies": [ { "value": "Employed", "count": 2, "proportion": 0.6667 },
                                    { "value": "Grad school", "count": 1, "proportion": 0.3333 } ] }
  },
  "meta": { "records": 3, "fields_analyzed": 2, "version": "1.4.0" }
}
```

Numeric parsing is forgiving — `"$85,000"` and `"12%"` read as `85000` and `12`; blanks and the NA
markers (`""`, `na`, `n/a`, `null`, `nan`) count as `missing`; present-but-unparseable values count
as `invalid`. Booleans are treated as categorical. Categories are **case-sensitive** by default;
pass `"casefold": true` (request-level, or per field) to merge `"Employed"`/`"employed"`. Survey/job
exports are usually CSV, so a single CSV/TSV file works too (header row = field names; delimiter sniffed):

```bash
# multipart/form-data — one tabular file + optional fields selector
curl -s {BASE_URL}/api/aggregate \
  -F file=@survey.csv \
  -F 'fields=["salary","placement"]'
```

Full contract for ecosystem consumers: the [integration spec](docs/INTEGRATION.md); live schema at
`/openapi.json` + `/docs`.

### Configuration (env vars)

| Var | Default | Meaning |
| --- | --- | --- |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |
| `API_KEY` | _(empty)_ | When set, callers must send `X-API-Key`; empty = open |
| `CONFIDENCE_THRESHOLD` | `0.15` | Below this, results are flagged `low_confidence` |
| `MAX_COMBINED_CHARS` | `200000` | Cap on the merged text the parser sees (`413` over cap) |
| `MAX_FILES` | `20` | Max uploaded files per request |
| `MAX_FILE_BYTES` | `10485760` | Per-file size cap (oversized files fail softly) |
| `MAX_TOTAL_UPLOAD_BYTES` | `16777216` | Whole-request body cap (`413`) |

See `.env.example`.

## Deployment (Vercel)

`vercel.json` declares an explicit `@vercel/python` build and routes all paths to the Flask function,
which serves both the UI and the API. The builder installs `requirements.txt` and mounts the WSGI `app`.

```bash
vercel        # preview
vercel --prod # production
```

## Adding a target (lens) — data only, no code

A new `targets` value is added by editing data, not code. Nothing hard-codes lens names: the
pipeline dispatches on a lens's `kind`, the API validates against the registry, and the UI loops
`GET /api/lenses` and renders by `kind`. So any new lens of an existing kind flows through
untouched — instantly requestable via `targets`, listed by `/api/lenses`, rendered by the UI,
validated by the API, and bundled into the Vercel function (the `includeFiles: "**"` glob already
covers new files).

**A new lexicon lens** (detect terms from a curated list — e.g. methodologies, certifications) —
two data edits:

1. One entry in `taxonomy/lenses.json`:
   ```json
   { "name": "methodologies", "kind": "lexicon", "source": "lexicons/methodologies.json" }
   ```
2. The list at `taxonomy/lexicons/methodologies.json`:
   ```json
   [ { "term": "scrum", "display": "Scrum" }, { "term": "kanban", "display": "Kanban" } ]
   ```

Each matched term is linked dynamically to the document's relevant emphasis (`related`).

**A new emphasis axis** (rank a new vocabulary — e.g. `seniority`) — also data only:

1. A categories file (e.g. `taxonomy/seniority.json`, or set `"type": "seniority"` on the entries).
2. One entry in `taxonomy/lenses.json`: `{ "name": "seniority", "kind": "emphasis", "axis": "seniority" }`.

**Growing an existing emphasis category** — edit `taxonomy/fields.json` / `sectors.json`:

```json
{
  "id": "data_science", "label": "Data Science",
  "terms": [{ "term": "machine learning", "weight": 3 }, { "term": "etl", "weight": 2, "display": "ETL" }],
  "aliases": ["data engineering", "ml"]
}
```
`weight` lets strong signals outrank ambiguous ones; shared terms are auto down-weighted (IDF). A
category only surfaces with ≥2 matched terms or one weight-≥2 term, so lone common words can't create
false emphases. Optional `display` gives a term human-facing casing.

**Caveats**
- The lens must be one of the existing kinds (`emphasis` / `lexicon` / `keywords` / `tone`). A
  genuinely new *kind* needs code — a handler in `parser/pipeline.py` and a render branch in the UI.
- The registry is cached at cold start, so a redeploy (or restart) is needed to pick up new data.
