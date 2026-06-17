# Parser API — Integration Spec (v1.1.0)

Canonical integration reference. The Parser API is a standalone, deterministic, **no-LLM** text
extraction service. It is **lens-oriented**: you tell it which lenses to apply via `targets`, and it
returns a result per lens. It is domain-general and contains no résumé/job/HR-specific concepts.

## 1. Lenses (the core concept)

A **lens** is one way of looking at the text. Four kinds:

| Kind | Returns | Examples |
|---|---|---|
| `emphasis` | Ranked categories of one taxonomy **axis**, normalized within that axis (`top` + `ranked`) | `field`, `sector` |
| `lexicon` | Which terms from a curated list appear, each linked to the doc's relevant emphasis | `technologies` |
| `keywords` | Unsupervised RAKE keyphrases | `keywords` |
| `tone` | Multi-dimensional tone profile — independent 0–1 dimensions | `tone` |

Lenses are **data-driven and discoverable** — fetch the live set from `GET /api/lenses`. The current
built-ins: `field` (emphasis, default), `sector` (emphasis, default), `technologies` (lexicon),
`tone` (tone), `keywords` (default).

**Guarantees:** deterministic (same input + `meta.version` ⇒ byte-identical output, incl. casing),
stateless/idempotent, explainable (every emphasis ships its `matched_terms`), self-describing
(`/openapi.json`, `/docs`).

## 2. Base URL & runtime
- Python / Flask (WSGI) on Vercel serverless; one function serves everything.
- `{BASE_URL}` = your Vercel domain. Bodies are `application/json; charset=utf-8`.

## 3. Auth & CORS
- `API_KEY` env unset → open (default). Set → `POST /api/parse` requires `X-API-Key`; else **401**.
- `ALLOWED_ORIGINS` (comma-separated, default `*`) controls CORS. Server-to-server can ignore CORS.

## 4. Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/parse` | Parse text into lens-keyed results |
| `GET` | `/api/lenses` | Discover available lenses (what `targets` accepts) |
| `GET` | `/api/taxonomy` | Enumerate the emphasis vocabulary |
| `GET` | `/api/health` | Liveness + version + category count |
| `GET` | `/openapi.json`, `/docs` | Schema + Swagger UI |

```jsonc
// GET /api/lenses
{ "version": "1.1.0", "lenses": [
  { "name": "field",        "kind": "emphasis", "default": true },
  { "name": "sector",       "kind": "emphasis", "default": true },
  { "name": "technologies", "kind": "lexicon",  "default": false },
  { "name": "tone",         "kind": "tone",     "default": false },
  { "name": "keywords",     "kind": "keywords", "default": true }
] }

// GET /api/health
{ "status": "ok", "version": "1.1.0", "categories": 22 }
```

## 5. `POST /api/parse` — Request

```jsonc
{
  "text": "string",                      // REQUIRED, 1–50000 chars
  "targets": ["field", "technologies"],  // optional; omit → default lenses. RESTRICTIVE: only these are returned.
  "max_keywords": 15                     // optional, 1..50, default 15 (keywords lens)
}
```
- `targets` items are a **lens name** or `{ "name": "keywords", "limit": 10 }` (per-lens cap).
- Validation: blank/missing `text` → **400**; > 50000 chars → **413**; `max_keywords` out of range,
  `targets` not an array, unknown/duplicate/empty target → **422** (`{ "detail": "…" }`).

## 6. `POST /api/parse` — Response (200)

Real response for `targets: ["field","technologies","keywords"], max_keywords: 4`:

```json
{
  "results": {
    "field": {
      "kind": "emphasis",
      "top": { "id": "data_science", "label": "Data Science", "score": 0.8802,
               "matched_terms": ["ETL","Data Pipeline","SQL","Spark","Airflow","Data","Python"],
               "low_confidence": false },
      "ranked": [
        { "id": "data_science", "label": "Data Science", "score": 0.8802, "matched_terms": ["ETL","..."] },
        { "id": "devops", "label": "DevOps & Cloud Infrastructure", "score": 0.1198, "matched_terms": ["AWS"] }
      ]
    },
    "technologies": {
      "kind": "lexicon",
      "matched": [
        { "term": "spark", "display": "Spark", "related": { "id": "data_science", "label": "Data Science" } },
        { "term": "aws",   "display": "AWS",   "related": { "id": "devops", "label": "DevOps & Cloud Infrastructure" } }
      ]
    },
    "keywords": {
      "kind": "keywords",
      "items": [
        { "term": "build scalable data pipelines", "display": "Build scalable Data pipelines",
          "score": 1.0, "source": "rake", "related": { "id": "data_science", "label": "Data Science" } },
        { "term": "etl", "display": "ETL", "score": 1.0, "source": "rake+lexicon",
          "related": { "id": "data_science", "label": "Data Science" } }
      ]
    }
  },
  "meta": { "token_count": 26, "version": "1.1.0" }
}
```

`results` is keyed by the lens names you requested (default: `field`, `sector`, `keywords`). The
shape of each value depends on `kind`:

**emphasis** → `{ kind, top, ranked }`. `top` is the highest-scoring category (or `null`), with a
`low_confidence` flag. Each category: `id` (stable key — join on this), `label`, `score` (share
**within that axis**, so an axis's scores sum to ~1), `matched_terms` (display-cased evidence, ≤8).

**lexicon** → `{ kind, matched: [{ term, display, related }] }`. `term` is the lowercased join key;
`display` is human-facing; `related` is `{id,label}` of the doc's relevant emphasis (or `null`).

**keywords** → `{ kind, items: [{ term, display, score, source, related }] }`. `term` lowercased
(stable join/dedup key); `display` human-facing; `score` ∈ [0,1] (ordering only); `source` ∈
`rake | lexicon | rake+lexicon`; `related` `{id,label}` or `null`.

**tone** → `{ kind, dimensions: [{ name, label, score, leaning, evidence }] }`. Independent
dimensions (not competing). `score` ∈ [0,1]. Bipolar dims (`formality`, `sentiment`) report a
`leaning` of either pole or `"neutral"` (0.5 = balanced); unipolar dims (`urgency`, `enthusiasm`)
report intensity (0 = absent) with `leaning` the dimension's label or `"neutral"`. `evidence` lists
the cue words that drove the score. Example:
```jsonc
"tone": { "kind": "tone", "dimensions": [
  { "name": "formality",  "label": "Formality",  "score": 0.82, "leaning": "formal",       "evidence": ["furthermore","pursuant"] },
  { "name": "sentiment",  "label": "Sentiment",  "score": 0.67, "leaning": "positive",     "evidence": ["excellent","strong"] },
  { "name": "urgency",    "label": "Urgency",    "score": 0.40, "leaning": "neutral",      "evidence": ["deadline"] },
  { "name": "enthusiasm", "label": "Enthusiasm", "score": 0.00, "leaning": "neutral",      "evidence": [] }
] }
```

**meta** → `{ token_count, version }`.

## 7. Scoring (emphasis lenses)
Per-category raw = Σ `weight × (1 + ln(count)) × idf(term)`; reported `score` = raw normalized
**within the axis**. A category surfaces only with ≥2 matched terms or one specific (weight ≥2)
term, so a lone common word never creates an emphasis. Matching is case-insensitive and lightly
stemmed (plurals match).

## 8. Vocabulary (`GET /api/taxonomy`)
⚠️ Data-driven and growing — treat ids/labels as an open set; prefer `id`, fetch the live list.
Currently 17 fields (incl. `data_science`, `machine_learning`, `software_engineering`,
`business_management`, `physics`, …) + 5 sectors (`software_industry`, `academia`, `research`,
`healthcare`, `finance`).

## 9. Client example (Python)
```python
import httpx
r = httpx.post(f"{BASE_URL}/api/parse",
               headers={"X-API-Key": KEY},  # only if API_KEY is set
               json={"text": text, "targets": ["field", "technologies"]}, timeout=15)
r.raise_for_status()
res = r.json()["results"]
field = res["field"]["top"]                       # {id,label,score,...} or None
techs = [m["display"] for m in res["technologies"]["matched"]]
```

## 10. Recommended integration pattern
1. On startup, `GET /api/lenses` (+ `/api/taxonomy`) and cache them.
2. Request exactly the lenses you need via `targets` (restrictive → lean responses).
3. Read `results.<lens>.top` for the pertinent emphasis; iterate `matched`/`items` for the rest.
   Render `display`, join/dedup on `term`/`id`, group by `related.id`.
4. Cache on `sha256(text) + sorted(targets) + meta.version`.

## 11. Versioning
`meta.version` / `/api/health` / `/api/taxonomy` / `/api/lenses` report semver (currently `1.1.0`).
1.1.0 is the lens-oriented contract; pin to it and re-fetch `/api/lenses` + `/api/taxonomy` on minor
bumps (which may grow lenses/vocabulary).
