from api.index import app

client = app.test_client()


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["categories"] >= 21


def test_taxonomy_enumerates_vocabulary():
    r = client.get("/api/taxonomy")
    assert r.status_code == 200
    body = r.get_json()
    assert body["count"] == len(body["categories"]) >= 21
    assert {c["type"] for c in body["categories"]} == {"field", "sector"}
    for c in body["categories"]:
        assert set(c.keys()) == {"id", "label", "type"}
    ids = {c["id"] for c in body["categories"]}
    assert {"data_science", "software_industry", "astronomy"} <= ids


def test_parse_includes_id_on_primary_and_secondary():
    jd = (
        "Senior Data Engineer building data pipelines and ETL with Spark, in an Agile "
        "team with CI/CD and code reviews."
    )
    r = client.post("/api/parse", json={"text": jd})
    assert r.status_code == 200
    d = r.get_json()
    assert d["primary"]["id"] == "data_science"
    assert d["secondary"]["id"] == "software_industry"


def test_missing_or_blank_text_is_400():
    assert client.post("/api/parse", json={}).status_code == 400
    assert client.post("/api/parse", json={"text": "   "}).status_code == 400


def test_max_keywords_out_of_range_is_422():
    assert client.post("/api/parse", json={"text": "x", "max_keywords": 0}).status_code == 422
    assert client.post("/api/parse", json={"text": "x", "max_keywords": 99}).status_code == 422


def test_error_body_is_detail_object():
    body = client.post("/api/parse", json={"text": "  "}).get_json()
    assert isinstance(body, dict) and isinstance(body["detail"], str)


def test_wrong_method_returns_json_405():
    r = client.get("/api/parse")
    assert r.status_code == 405
    assert r.get_json()["detail"]


def test_openapi_and_docs_are_served():
    oa = client.get("/openapi.json")
    assert oa.status_code == 200 and oa.is_json
    assert oa.get_json()["openapi"].startswith("3.")
    docs = client.get("/docs")
    assert docs.status_code == 200 and b"swagger-ui" in docs.data
