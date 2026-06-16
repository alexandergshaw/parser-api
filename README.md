# Parser API

The first service in an **LLM-alternative ecosystem**. It ingests a block of text (job
descriptions, resumes, lecture transcripts, …) and returns — **without any LLM**, fully
deterministically — structured extractions organized by **lenses** the caller chooses.

You pass which lenses to apply (`targets`); the API returns a result per lens:

- **emphasis** lenses (e.g. `field`, `sector`) rank a curated taxonomy axis → the document's topic /
  industry, each with the `matched_terms` that produced it.
- **lexicon** lenses (e.g. `technologies`) report which terms from a curated list appear, each linked
  to the document's relevant emphasis.
- **keywords** lens returns unsupervised RAKE keyphrases lifted from *this* document.

The downstream **researcher API** consumes these: emphases drive general research; keywords and
detected technologies drive deep-dive research.

## How it works

```
text ─► normalize (tokenize, stem, n-grams)
          ├─ emphasis lenses ─ per-axis lexicon scoring over taxonomy/*.json ─► top + ranked
          ├─ lexicon lenses  ─ curated term lists in taxonomy/lexicons/      ─► matched terms
          └─ keywords lens   ─ pure-Python RAKE                              ─► keyphrases
                                                          results keyed by requested lens ─► JSON
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
| `POST` | `/api/parse` | Parse text into lens-keyed results |
| `GET` | `/api/lenses` | Discover available lenses (what `targets` accepts) |
| `GET` | `/api/taxonomy` | Enumerate the emphasis vocabulary (`{id, label, type}`) |
| `GET` | `/api/health` | Liveness, version, taxonomy size |
| `GET` | `/docs`, `/openapi.json` | Swagger UI + machine-readable schema |

```jsonc
// POST /api/parse — request
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
  "meta": { "token_count": 26, "version": "1.0.0" }
}
```

Full contract for ecosystem consumers: the [integration spec](docs/INTEGRATION.md); live schema at
`/openapi.json` + `/docs`.

### Configuration (env vars)

| Var | Default | Meaning |
| --- | --- | --- |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |
| `API_KEY` | _(empty)_ | When set, callers must send `X-API-Key`; empty = open |
| `CONFIDENCE_THRESHOLD` | `0.15` | Below this, results are flagged `low_confidence` |

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
- The lens must be one of the existing kinds (`emphasis` / `lexicon` / `keywords`). A genuinely new
  *kind* of extraction needs code — a handler in `parser/pipeline.py` and a render branch in the UI.
- The registry is cached at cold start, so a redeploy (or restart) is needed to pick up new data.
