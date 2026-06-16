# Parser API — Integration Spec (v0.3.0)

Canonical integration reference for ecosystem consumers. The Parser API is a standalone,
deterministic, **no-LLM** text → emphases + keywords service. It is domain-general and has
multiple consumers — it does **not** contain résumé/job/HR-specific concepts.

## 1. Summary

Stateless HTTP service that turns a block of text into **broad emphases** (curated taxonomy +
lexicon scorer) and **specific keywords** (pure-Python RAKE), with each keyword linked back to its
parent emphasis.

**Guarantees:**
- **Deterministic** — same input + same `meta.version` ⇒ byte-identical output (including `display`).
  Safe to cache on a hash of `(text, max_keywords, version)`.
- **Stateless / idempotent** — no sessions, persistence, or side effects.
- **Explainable** — every emphasis ships the `matched_terms` that produced it.
- **Self-describing** — OpenAPI 3 at `GET /openapi.json` (codegen), Swagger UI at `GET /docs`.

## 2. Base URL & runtime

- Python / FastAPI on Vercel serverless; all routes rewrite to one function.
- Base URL = your Vercel domain, `{BASE_URL}` (e.g. `https://parser-api-<hash>.vercel.app`).
- All bodies are `application/json; charset=utf-8`.

## 3. Authentication

| Condition | Behavior |
|---|---|
| `API_KEY` env **unset/empty** | Endpoints open (default). |
| `API_KEY` env **set** | `POST /api/parse` requires header `X-API-Key: <key>`. Missing/wrong ⇒ **401**. |

`GET /api/health` and `GET /api/taxonomy` are always open.

## 4. CORS

Controlled by `ALLOWED_ORIGINS` (comma-separated; default `*`). Methods `GET, POST, OPTIONS`;
headers `Content-Type, X-API-Key`; credentials disabled. Server-to-server callers can ignore CORS.

## 5. Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/parse` | conditional | Parse text → emphases + keywords |
| `GET` | `/api/health` | open | Liveness + taxonomy size + version |
| `GET` | `/api/taxonomy` | open | Enumerate the controlled vocabulary |
| `GET` | `/openapi.json` | open | Machine-readable schema (codegen) |
| `GET` | `/docs` | open | Swagger UI |
| `GET` | `/` | open | Human testing UI (HTML; not for programmatic use) |

### `GET /api/health` → 200
```json
{ "status": "ok", "version": "0.3.0", "categories": 21 }
```

### `GET /api/taxonomy` → 200
Discover the (growing) vocabulary dynamically instead of hard-coding labels. Sorted by `type`, then `label`.
```json
{
  "version": "0.3.0",
  "count": 21,
  "categories": [
    { "id": "astronomy", "label": "Astronomy & Astrophysics", "type": "field" },
    { "id": "biology",   "label": "Biology",                  "type": "field" }
  ]
}
```

## 6. `POST /api/parse` — Request

```jsonc
{
  "text": "string",          // REQUIRED. Non-empty after trim. Max 50,000 chars.
  "max_keywords": 15,         // optional, integer 1..50, default 15
  "language": "en"            // optional, default "en". ACCEPTED BUT IGNORED (English only).
}
```
Validation: blank `text` → **400**; > 50,000 chars → **413**; wrong types / `max_keywords` out of
`[1,50]` → **422**.

## 7. `POST /api/parse` — Response (200)

Real response for a data-engineer job description (`max_keywords: 6`):

```json
{
  "primary":   { "id": "data_science", "label": "Data Science", "type": "field", "score": 0.6822,
                 "matched_terms": ["ETL","Data Warehouse","Data Pipeline","Big Data","Data","SQL","Spark","Data Lake"] },
  "secondary": { "id": "software_industry", "label": "Software Industry", "type": "sector", "score": 0.2312,
                 "matched_terms": ["CI/CD","Agile","Code Review"] },
  "emphases": [
    { "id": "data_science", "label": "Data Science", "type": "field", "score": 0.6822, "matched_terms": ["ETL","Data Warehouse","..."] },
    { "id": "software_industry", "label": "Software Industry", "type": "sector", "score": 0.2312, "matched_terms": ["CI/CD","Agile","Code Review"] },
    { "id": "machine_learning", "label": "Machine Learning", "type": "field", "score": 0.0867, "matched_terms": ["Machine Learning"] }
  ],
  "keywords": [
    { "term": "support machine learning models", "display": "support machine learning models", "score": 1.0,   "source": "rake",         "related_emphasis": "Machine Learning",  "related_emphasis_id": "machine_learning" },
    { "term": "data warehouse",                  "display": "Data Warehouse",                  "score": 1.0,   "source": "rake+lexicon", "related_emphasis": "Data Science",      "related_emphasis_id": "data_science" },
    { "term": "etl",                             "display": "ETL",                             "score": 1.0,   "source": "lexicon",      "related_emphasis": "Data Science",      "related_emphasis_id": "data_science" },
    { "term": "build scalable data pipelines",   "display": "Build scalable data pipelines",   "score": 0.925, "source": "rake",         "related_emphasis": "Data Science",      "related_emphasis_id": "data_science" },
    { "term": "cicd",                            "display": "CI/CD",                           "score": 0.9,   "source": "rake+lexicon", "related_emphasis": "Software Industry", "related_emphasis_id": "software_industry" },
    { "term": "data pipeline",                   "display": "Data Pipeline",                   "score": 0.9,   "source": "lexicon",      "related_emphasis": "Data Science",      "related_emphasis_id": "data_science" }
  ],
  "meta": { "token_count": 39, "confidence": 0.6822, "low_confidence": false, "version": "0.3.0" }
}
```

### Field reference

**`primary` / `secondary`** — object or `null`. **`emphases[]`** — array (may be empty), one entry
per matched category, sorted by `score` desc. All three use the **same object shape**:

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable machine key, e.g. `data_science`. **Key on this.** |
| `label` | string | Human-facing name (see §10). |
| `type` | string | `"field"` (topic) or `"sector"` (industry/context). |
| `score` | float | Normalized share, see §8. |
| `matched_terms` | string[] | Evidence, strongest first, **capped at 8**, in human-facing display casing. |

**`keywords[]`** — specific subtopics, sorted by `score` desc, length ≤ `max_keywords`:

| Field | Type | Notes |
|---|---|---|
| `term` | string | **Lowercased, de-punctuated** — the stable join/dedup key. Never changes. |
| `display` | string | Human-facing casing: authored form for lexicon terms (`ETL`, `CI/CD`, `Node.js`), or the most-frequent **source casing** for free-text phrases. Render this. |
| `score` | float | Relative salience in `[0,1]` within this response; ties at `1.0` possible. Not a probability; not comparable across requests. |
| `source` | enum | `"rake"`, `"lexicon"`, or `"rake+lexicon"` (both signals agree). |
| `related_emphasis` | string \| null | `label` of the parent emphasis. |
| `related_emphasis_id` | string \| null | **Stable `id`** of the parent emphasis — your id-based join key. `null` iff `related_emphasis` is `null`. |

**`meta`:**

| Field | Type | Notes |
|---|---|---|
| `token_count` | int | Tokens parsed. |
| `confidence` | float | = `primary.score` (0 if no match). |
| `low_confidence` | bool | `true` when `primary` is `null` **or** `confidence < CONFIDENCE_THRESHOLD` (default `0.15`). Treat as "weak signal." |
| `version` | string | Engine/taxonomy semver. |

## 8. Emphasis scoring & selection

- Per-category raw score = Σ over matched terms of `weight × (1 + ln(count)) × idf(term)`. `weight`
  is authored per term; `idf` down-weights terms shared across many categories.
- Reported `score` = `raw / Σ raw` across returned emphases → **scores sum to ≈ 1.0 within a
  response** (a share of total matched signal). Comparable *within* a response, not across responses.
- **`primary`** = highest raw score. **`secondary`** = highest of the *opposite* `type` (so you
  reliably get one field + one sector); if no opposite type matched, falls back to 2nd overall.
- Matching is case-insensitive and **lightly stemmed** (plural→singular), so `data pipelines`
  matches the lexicon's `data pipeline`.

## 9. Keyword semantics

RAKE phrases scored by degree/frequency, normalized so the top phrase = 1.0; lexicon-evidence terms
scored by category rank; overlaps become `rake+lexicon` with a small boost. **Use `score` only for
ordering**; use `term` for joins/dedup, `display` for rendering, and `related_emphasis_id` to group
specific subtopics under broad labels.

> Note: keywords are **not** classified into tool/skill/methodology/etc. The taxonomy is
> fields/sectors only. A consumer needing a different classification should map from
> `related_emphasis_id` (+ its own lexicon) on its side.

## 10. Controlled vocabulary (current — 21 categories)

⚠️ **Data-driven and growing.** Treat ids/labels as an **open set** — don't hard-fail on unknown
values; prefer `id`, and fetch the live list from `GET /api/taxonomy`.

**Fields (`type: "field"`)** — 16:
`data_science` · `machine_learning` · `software_engineering` · `web_development` · `devops` · `cybersecurity` · `physics` · `mathematics` · `biology` · `chemistry` · `statistics` · `astronomy` · `electrical_engineering` · `mechanical_engineering` · `economics` · `neuroscience`

**Sectors (`type: "sector"`)** — 5:
`software_industry` · `academia` · `research` · `healthcare` · `finance`

## 11. Errors

All errors use FastAPI's shape: `{ "detail": "<message>" }` (422 `detail` is an array of validation objects).

| Status | When |
|---|---|
| `400` | `text` missing or blank after trim |
| `401` | `API_KEY` configured and `X-API-Key` missing/wrong |
| `413` | `text` > 50,000 chars |
| `422` | malformed body / `max_keywords` out of range / wrong types |

A `200` with `meta.low_confidence: true` and `primary: null` is **not** an error — it means "no
category matched." Handle explicitly.

## 12. Limits & operational notes

- **Payload:** 50,000 chars; `max_keywords` 1–50.
- **No built-in rate limiting** — add it at your gateway if exposed publicly.
- **Cold starts:** taxonomy built once per cold start (warmed at app startup) then cached; warm
  calls are pure in-memory.
- **Latency** scales with text length, not network.

## 13. Versioning

`meta.version`, `/api/health`, and `/api/taxonomy` report semver (currently `0.3.0`). Minor/patch
bumps may grow the taxonomy or tweak scoring (output may shift); pin expectations to a version and
re-fetch `/api/taxonomy` on changes. Field additions are additive and backward-compatible.

## 14. Client examples

**curl**
```bash
curl -s {BASE_URL}/api/parse \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $PARSER_API_KEY" \
  -d '{"text":"<any block of text>","max_keywords":10}'
```

**Python (httpx)**
```python
import httpx
r = httpx.post(f"{BASE_URL}/api/parse",
               headers={"X-API-Key": PARSER_API_KEY},
               json={"text": text, "max_keywords": 10}, timeout=15)
r.raise_for_status()
data = r.json()

primary_id = data["primary"]["id"] if data["primary"] else None
# group specific subtopics under broad labels (by stable id):
by_emphasis: dict[str | None, list[str]] = {}
for kw in data["keywords"]:
    by_emphasis.setdefault(kw["related_emphasis_id"], []).append(kw["display"])
```

**TypeScript (fetch)**
```ts
const res = await fetch(`${BASE_URL}/api/parse`, {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": process.env.PARSER_API_KEY! },
  body: JSON.stringify({ text, max_keywords: 10 }),
});
if (!res.ok) throw new Error(`parser ${res.status}: ${(await res.json()).detail}`);
const data = await res.json();
```

## 15. Recommended integration pattern

1. On startup, `GET /api/taxonomy` and cache the vocabulary (`id` → `label`/`type`).
2. Per request, send raw text; check `meta.low_confidence` first — if `true`, fall back to
   keyword-only behavior or skip.
3. Use **`primary`/`secondary` (`id` + `label`)** to seed broad behavior.
4. Group **`keywords` by `related_emphasis_id`** for per-topic deep dives. Render `display`,
   join/dedup on `term`.
5. Cache results on `sha256(text) + max_keywords + meta.version`.
