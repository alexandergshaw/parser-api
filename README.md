# Parser API

The first service in an **LLM-alternative ecosystem**. It ingests a block of text (job
descriptions, resumes, lecture transcripts, …) and returns — **without any LLM**, fully
deterministically — two tiers of output:

1. **Broad emphases** — abstracted topic + sector labels (e.g. *Data Science*, *Software Industry*),
   produced by a curated taxonomy + weighted lexicon scoring engine.
2. **Specific subtopics / keywords** — salient phrases lifted from *this particular document*
   (e.g. *gradient boosting*, *ETL pipeline*), produced by unsupervised keyphrase extraction.

The downstream **researcher API** consumes both: broad labels drive general research, specific
subtopics drive deep-dive research and resume/lecture adaptation.

## How it works

```
text ──► normalize (tokenize, 1–3-grams)
            ├─► classify  (lexicon scoring over taxonomy/*.json)  ──► broad emphases
            └─► extract   (pure-Python RAKE keyphrase extraction) ──► specific keywords
                                                                   merge ─► JSON response
```

- **No LLM, no training data, no network calls.** Everything is deterministic and explainable —
  every emphasis comes with the `matched_terms` that produced it.
- **Data-driven taxonomy.** Categories live in `taxonomy/fields.json` and `taxonomy/sectors.json`.
  Expanding coverage (toward generalist) means editing JSON, not code.
- **Keyword extraction is pure-Python** (RAKE-style) to keep the Vercel bundle dependency-free and
  cold-starts fast.
- **Light stemming** on the matching layer so plurals match (`data pipelines` → `data pipeline`),
  while keywords keep their natural surface form for display.
- **Keywords are linked to their parent emphasis** via `related_emphasis` (label) and
  `related_emphasis_id` (stable id), so consumers can drive both broad and deep-dive research.
- **Human-facing casing** on every keyword: `term` stays lowercased for stable joins/dedup, while
  `display` carries authored casing for acronyms/special forms (`ETL`, `CI/CD`, `Node.js`) or the
  most-frequent source casing for free-text phrases. The same authored casing is used in
  `matched_terms`.

## Project layout

| Path | Purpose |
| --- | --- |
| `api/index.py` | Flask app — Vercel entrypoint, `/api/parse`, serves the testing UI at `/` |
| `parser/` | Framework-agnostic core library (unit-testable without HTTP) |
| `taxonomy/` | `fields.json` + `sectors.json` — the curated lexicons |
| `web/index.html` | Vanilla-JS testing UI (served by the function; not in reserved `public/`) |
| `tests/` | pytest suite incl. the data-engineer acceptance test |

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
| `POST` | `/api/parse` | Parse text → emphases + keywords |
| `GET` | `/api/health` | Liveness, version, taxonomy size |
| `GET` | `/api/taxonomy` | Enumerate the controlled vocabulary (`{id, label, type}`) |
| `GET` | `/docs`, `/openapi.json` | Interactive docs + machine-readable schema |

`POST /api/parse`

```jsonc
// Request
{ "text": "…", "max_keywords": 15 }

// Response 200
{
  "primary":   { "id": "data_science", "label": "Data Science", "type": "field", "score": 0.82,
                 "matched_terms": ["machine learning", "etl", "data pipeline"] },
  "secondary": { "id": "software_industry", "label": "Software Industry", "type": "sector",
                 "score": 0.54, "matched_terms": ["agile", "ci/cd"] },
  "emphases":  [ /* full ranked list */ ],
  "keywords":  [ { "term": "gradient boosting", "display": "Gradient Boosting", "score": 0.91,
                  "source": "rake", "related_emphasis": "Machine Learning",
                  "related_emphasis_id": "machine_learning" } ],
  "meta":      { "token_count": 412, "confidence": 0.82, "low_confidence": false,
                 "version": "0.3.0" }
}
```

Interactive docs + machine-readable schema (a contract for the researcher API) are auto-generated at
`/docs` and `/openapi.json`. For ecosystem consumers, see the full
[integration spec](docs/INTEGRATION.md).

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

## Extending the taxonomy

Add or edit entries in `taxonomy/fields.json` / `taxonomy/sectors.json`. Each category:

```json
{
  "id": "data_science",
  "label": "Data Science",
  "type": "field",
  "terms": [{ "term": "machine learning", "weight": 3 }, { "term": "etl", "weight": 2 }],
  "aliases": ["data engineering", "ml"]
}
```

`weight` lets strong signals outrank ambiguous ones; terms shared across many categories are
automatically down-weighted (IDF) at load time, so you don't need a training corpus.
