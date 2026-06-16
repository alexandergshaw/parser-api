from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["categories"] >= 21


def test_taxonomy_enumerates_vocabulary():
    r = client.get("/api/taxonomy")
    assert r.status_code == 200
    body = r.json()
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
    d = r.json()
    assert d["primary"]["id"] == "data_science"
    assert d["secondary"]["id"] == "software_industry"


def test_parse_empty_text_is_400():
    assert client.post("/api/parse", json={"text": "   "}).status_code == 400


def test_parse_validation_errors_are_422():
    assert client.post("/api/parse", json={}).status_code == 422
    assert client.post("/api/parse", json={"text": "x", "max_keywords": 0}).status_code == 422
