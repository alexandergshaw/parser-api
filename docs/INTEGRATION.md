# Parser API — Integration Spec (v1.4.0)

Canonical integration reference. The Parser API is a standalone, deterministic, **no-LLM** text
extraction service. It is **lens-oriented**: you tell it which lenses to apply via `targets`, and it
returns a result per lens. Input may be an inline string and/or uploaded files (pdf, pptx, docx,
xlsx, txt, …); it is domain-general and contains no résumé/job/HR-specific concepts.

A companion endpoint, `POST /api/aggregate`, works on **structured records** instead of prose: it
computes summary statistics (means, medians, quartiles, frequency distributions) over targeted
fields — same deterministic, no-LLM contract, same `{results, meta}` envelope.

## 1. Lenses (the core concept)

A **lens** is one way of looking at the text. Four kinds:

| Kind | Returns | Examples |
|---|---|---|
| `emphasis` | Ranked categories of one taxonomy **axis**, normalized within that axis (`top` + `ranked`) | `field`, `sector` |
| `lexicon` | Which terms from a curated list appear, each linked to the doc's relevant emphasis | `technologies` |
| `keywords` | Unsupervised RAKE keyphrases | `keywords` |
| `tone` | Multi-dimensional tone profile — independent 0–1 dimensions | `tone` |

Lenses are **data-driven and discoverable** — fetch the live set from `GET /api/lenses`. The current
built-ins: `field` (emphasis, default), `sector` (emphasis, default), `intent` (emphasis),
`technologies` (lexicon), `tone` (tone), `keywords` (default). `field`, `sector`, and `intent` are
three independent emphasis axes (topic / industry / communicative goal).

**Guarantees:** deterministic (same input + `meta.version` ⇒ byte-identical output, incl. casing),
stateless/idempotent, explainable (every emphasis ships its `matched_terms`), self-describing
(`/openapi.json`, `/docs`).

## 2. Base URL & runtime
- Python / Flask (WSGI) on Vercel serverless; one function serves everything.
- `{BASE_URL}` = your Vercel domain. Bodies are `application/json; charset=utf-8`.

## 3. Auth & CORS
- `API_KEY` env unset → open (default). Set → `POST /api/parse` and `POST /api/aggregate` require
  `X-API-Key`; else **401**.
- `ALLOWED_ORIGINS` (comma-separated, default `*`) controls CORS. Server-to-server can ignore CORS.

## 4. Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/parse` | Parse text into lens-keyed results |
| `POST` | `/api/aggregate` | Summarize a record set into per-field statistics |
| `GET` | `/api/lenses` | Discover available lenses (what `targets` accepts) |
| `GET` | `/api/taxonomy` | Enumerate the emphasis vocabulary |
| `GET` | `/api/health` | Liveness + version + category count |
| `GET` | `/openapi.json`, `/docs` | Schema + Swagger UI |

```jsonc
// GET /api/lenses
{ "version": "1.4.0", "lenses": [
  { "name": "field",        "kind": "emphasis", "default": true },
  { "name": "sector",       "kind": "emphasis", "default": true },
  { "name": "intent",       "kind": "emphasis", "default": false },
  { "name": "technologies", "kind": "lexicon",  "default": false },
  { "name": "tone",         "kind": "tone",     "default": false },
  { "name": "keywords",     "kind": "keywords", "default": true }
] }

// GET /api/health
{ "status": "ok", "version": "1.4.0", "categories": 29 }
```

## 5. `POST /api/parse` — Request

Two content types. **`application/json`** (text only — back-compatible):

```jsonc
{
  "text": "string",                      // optional now; provide text and/or files
  "targets": ["field", "technologies"],  // optional; omit → default lenses. RESTRICTIVE: only these are returned.
  "max_keywords": 15                     // optional, 1..50, default 15 (keywords lens)
}
```

**`multipart/form-data`** (text and/or files). Repeat the `files` part per file; `targets` is a JSON
array string or a comma list:

```bash
curl -s {BASE_URL}/api/parse \
  -F files=@lecture3.pptx -F files=@chapter.pdf \
  -F 'text=optional inline framing' \
  -F 'targets=["field","intent","keywords"]' -F max_keywords=20
```

**Inputs (both optional).** Everything submitted is merged into one document — **inline `text` first,
then files sorted by name**, joined with blank lines — then run through the pipeline. Supported files:
`.pdf` (pypdf), `.docx`/`.pptx`/`.xlsx` (stdlib OOXML), and `.txt`/`.md`/`.csv`/`.tsv`/`.log`/`.rst`.
A file that can't be read (unsupported type, corrupt, encrypted, scanned/image-only PDF) **fails
softly** — it's reported in `meta.sources` with `ok:false` and skipped, not fatal.

- `targets` items are a **lens name** or `{ "name": "keywords", "limit": 10 }` (per-lens cap).
- Validation: no usable input at all → **400**; inputs given but none yield text → **422** (detail
  lists the per-file reasons); combined text > `MAX_COMBINED_CHARS` (default 200000) → **413**; request
  body > `MAX_TOTAL_UPLOAD_BYTES` or more than `MAX_FILES` files → **413**/**422**; `max_keywords` out
  of range, `targets` not an array, unknown/duplicate/empty target → **422** (`{ "detail": "…" }`).
- Per-file size cap `MAX_FILE_BYTES` (default 10 MB). **On Vercel**, the platform caps serverless
  request bodies at ~4.5 MB — large uploads may be rejected before reaching the function.

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
  "meta": { "token_count": 26, "version": "1.4.0",
            "sources": [ { "name": "text", "kind": "text", "chars": 142, "ok": true } ] }
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

**meta** → `{ token_count, version, sources }`. `sources` lists what was ingested — one entry per
input (`name`: filename or `"text"`; `kind`; `chars`; `ok`; plus `error` when `ok` is false). Failed
files appear here with `ok:false` and are skipped from the parse, so callers can audit coverage.

## 7. `POST /api/aggregate` — Records → statistics

A non-text modality sharing the same `{results, meta}` envelope, keyed by **field** instead of lens.
Takes a set of records (job postings, survey rows, …) and returns summary statistics per field.

**Request** — `application/json`:
```jsonc
{
  "records": [ { "placement": "Employed", "salary": "85000" }, … ],  // required: non-empty array of objects
  "fields": ["salary", "placement"],  // optional; omit → every field. RESTRICTIVE.
  "casefold": false                    // optional; fold categorical values case-insensitively
}                                      // field item: a name, or { "name", "type"?, "limit"?, "casefold"? }
```
Or `multipart/form-data`: one CSV/TSV `file` (header row = field names; delimiter sniffed) + optional
`fields` (a JSON array string or comma list) and `casefold` (`1`/`true`/`yes`/`on`).

**Field kind** is inferred from the values — predominantly number-like → `numeric`, else
`categorical` — and can be forced per field via `type`:

- **numeric** → `{ kind, count, missing, invalid, mean, median, min, max, sum, stdev, p25, p75 }`.
  `count` = parsed numbers; `missing` = blank/NA/absent; `invalid` = present but unparseable. `stdev`
  is the sample stdev; `stdev`/`p25`/`p75` are `null` when `count < 2`. Parsing strips `$ , %` (so
  `"$85,000"` and `"12%"` read as numbers); booleans are treated as categorical, not numeric.
- **categorical** → `{ kind, count, missing, distinct, mode, frequencies:[{ value, count, proportion }] }`,
  sorted by `count` desc then `value` asc. `distinct` is the full cardinality even when `frequencies`
  is capped by a field's `limit` (in which case `truncated: true` is also present). Case-sensitive
  unless `casefold` is set (request-level or per field), which folds values and reports the folded form.
- **empty** → `{ kind:"empty", count:0, missing }` for a field with no present values.

```jsonc
// Response 200 (fields: ["salary","placement"])
{
  "results": {
    "salary":    { "kind":"numeric", "count":2, "missing":1, "invalid":0, "mean":90000, "median":90000,
                   "min":85000, "max":95000, "sum":180000, "stdev":7071.0678, "p25":82500, "p75":97500 },
    "placement": { "kind":"categorical", "count":3, "missing":0, "distinct":2, "mode":"Employed",
                   "frequencies":[ { "value":"Employed","count":2,"proportion":0.6667 },
                                   { "value":"Grad school","count":1,"proportion":0.3333 } ] }
  },
  "meta": { "records":3, "fields_analyzed":2, "version":"1.4.0" }
}
```

**Missing markers:** `null`, `""`, whitespace, and `na`/`n/a`/`null`/`nan` (case-insensitive).
**Validation:** absent `records` (or no multipart `file`) → **400**; `records` not a non-empty array
of objects, an unknown field name, an empty `fields`, or a bad `type` → **422**; file over
`MAX_FILE_BYTES` (10 MB) → **413**.

## 8. Scoring (emphasis lenses)
Per-category raw = Σ `weight × (1 + ln(count)) × idf(term)`; reported `score` = raw normalized
**within the axis**. A category surfaces only with ≥2 matched terms or one specific (weight ≥2)
term, so a lone common word never creates an emphasis. Matching is case-insensitive and lightly
stemmed (plurals match).

## 9. Vocabulary (`GET /api/taxonomy`)
⚠️ Data-driven and growing — treat ids/labels as an open set; prefer `id`, fetch the live list.
Currently 17 fields (incl. `data_science`, `machine_learning`, `software_engineering`,
`business_management`, `physics`, …) + 5 sectors (`software_industry`, `academia`, `research`,
`healthcare`, `finance`) + 7 intents on the `intent` axis (`hiring`, `teaching`, `selling`,
`informing`, `instructing`, `requesting`, `announcing`). Each category carries its `type` (the axis).

## 10. Client example (Python)
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

## 11. Recommended integration pattern
1. On startup, `GET /api/lenses` (+ `/api/taxonomy`) and cache them.
2. Request exactly the lenses you need via `targets` (restrictive → lean responses).
3. Read `results.<lens>.top` for the pertinent emphasis; iterate `matched`/`items` for the rest.
   Render `display`, join/dedup on `term`/`id`, group by `related.id`.
4. Cache on `sha256(text) + sorted(targets) + meta.version`.

## 12. Versioning
`meta.version` / `/api/health` / `/api/taxonomy` / `/api/lenses` report semver (currently `1.4.0`).
The 1.x line is the lens-oriented contract; pin to it and re-fetch `/api/lenses` + `/api/taxonomy` on
minor bumps (which may grow lenses/vocabulary). 1.3.0 added file ingestion (multipart uploads +
`meta.sources`); 1.4.0 added record aggregation (`POST /api/aggregate`). The JSON text-only
`/api/parse` request remains back-compatible throughout.
