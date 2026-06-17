from api.index import app

client = app.test_client()


def test_health():
    body = client.get("/api/health").get_json()
    assert body["status"] == "ok"
    assert body["version"] == "1.2.0"
    assert body["categories"] >= 22


def test_lenses_discovery():
    r = client.get("/api/lenses")
    assert r.status_code == 200
    body = r.get_json()
    names = {l["name"]: l for l in body["lenses"]}
    assert {"field", "sector", "technologies", "keywords"} <= set(names)
    assert names["field"]["kind"] == "emphasis" and names["field"]["default"] is True
    assert names["technologies"]["kind"] == "lexicon" and names["technologies"]["default"] is False


def test_lenses_includes_tone():
    names = {l["name"]: l for l in client.get("/api/lenses").get_json()["lenses"]}
    assert "tone" in names and names["tone"]["kind"] == "tone" and names["tone"]["default"] is False


def test_parse_tone_target():
    r = client.post("/api/parse", json={"text": "Pursuant to the agreement, respond immediately.",
                                        "targets": ["tone"]})
    assert r.status_code == 200
    dims = r.get_json()["results"]["tone"]["dimensions"]
    assert {d["name"] for d in dims} == {"formality", "sentiment", "urgency", "enthusiasm"}


def test_lenses_includes_intent():
    names = {l["name"]: l for l in client.get("/api/lenses").get_json()["lenses"]}
    assert "intent" in names and names["intent"]["kind"] == "emphasis" and names["intent"]["default"] is False


def test_taxonomy_includes_business_and_intent():
    cats = client.get("/api/taxonomy").get_json()["categories"]
    ids = {c["id"] for c in cats}
    assert {"data_science", "business_management", "hiring"} <= ids
    assert "intent" in {c["type"] for c in cats}


def test_parse_intent_target():
    r = client.post("/api/parse", json={"text": "We are seeking candidates to join our team.",
                                        "targets": ["intent"]})
    assert r.status_code == 200
    assert r.get_json()["results"]["intent"]["top"]["id"] == "hiring"


def test_parse_default_shape():
    r = client.post("/api/parse", json={"text": "Build ETL pipelines with Spark on AWS. Agile CI/CD."})
    assert r.status_code == 200
    body = r.get_json()
    assert set(body["results"]) == {"field", "sector", "keywords"}
    assert body["meta"]["version"] == "1.2.0"


def test_parse_targets_are_restrictive():
    r = client.post("/api/parse", json={"text": "Spark and Python", "targets": ["technologies"]})
    assert r.status_code == 200
    assert set(r.get_json()["results"]) == {"technologies"}


def test_parse_field_top():
    jd = "Data Engineer: ETL data pipelines, Spark, SQL, data warehouse."
    r = client.post("/api/parse", json={"text": jd, "targets": ["field"]})
    assert r.get_json()["results"]["field"]["top"]["id"] == "data_science"


def test_validation_errors():
    assert client.post("/api/parse", json={}).status_code == 400              # missing text
    assert client.post("/api/parse", json={"text": "  "}).status_code == 400   # blank text
    assert client.post("/api/parse", json={"text": "x", "max_keywords": 0}).status_code == 422
    assert client.post("/api/parse", json={"text": "x", "targets": ["nope"]}).status_code == 422
    assert client.post("/api/parse", json={"text": "x", "targets": []}).status_code == 422
    assert client.post("/api/parse", json={"text": "x", "targets": "field"}).status_code == 422


def test_static_assets_served():
    assert b'src="/app.js"' in client.get("/").data
    js = client.get("/app.js")
    assert js.status_code == 200 and "javascript" in js.content_type
    oa = client.get("/openapi.json")
    assert oa.status_code == 200 and oa.is_json
    assert client.get("/docs").status_code == 200
