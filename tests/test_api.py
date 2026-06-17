import io

from api.index import app

client = app.test_client()


def test_health():
    body = client.get("/api/health").get_json()
    assert body["status"] == "ok"
    assert body["version"] == "1.4.0"
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
    assert body["meta"]["version"] == "1.4.0"


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


def _file(content: bytes, name: str):
    return (io.BytesIO(content), name)


def test_json_response_includes_meta_sources():
    body = client.post("/api/parse", json={"text": "Spark and Python on AWS."}).get_json()
    assert body["meta"]["sources"] == [{"name": "text", "kind": "text",
                                        "chars": len("Spark and Python on AWS."), "ok": True}]


def test_multipart_single_txt_file():
    r = client.post("/api/parse", data={
        "files": _file(b"Data Engineer: ETL data pipelines, Spark, SQL, data warehouse.", "jd.txt"),
        "targets": "field",
    }, content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["results"]["field"]["top"]["id"] == "data_science"
    assert body["meta"]["sources"] == [{"name": "jd.txt", "kind": "txt",
                                        "chars": 62, "ok": True}]


def test_multipart_text_plus_files_are_merged():
    r = client.post("/api/parse", data={
        "text": "Spark and Airflow.",
        "files": [_file(b"SQL data warehouse.", "a.txt"), _file(b"Python ETL.", "b.txt")],
        "targets": "field,keywords",
    }, content_type="multipart/form-data")
    assert r.status_code == 200
    names = [s["name"] for s in r.get_json()["meta"]["sources"]]
    assert names == ["text", "a.txt", "b.txt"]  # inline first, files sorted


def test_multipart_unsupported_only_is_422_with_detail():
    r = client.post("/api/parse", data={"files": _file(b"binary", "legacy.doc")},
                    content_type="multipart/form-data")
    assert r.status_code == 422
    assert "legacy.doc" in r.get_json()["detail"]


def test_multipart_bad_file_is_soft_failure_among_good_ones():
    r = client.post("/api/parse", data={
        "files": [_file(b"Spark and SQL pipelines.", "good.txt"), _file(b"x", "bad.doc")],
    }, content_type="multipart/form-data")
    assert r.status_code == 200
    sources = {s["name"]: s for s in r.get_json()["meta"]["sources"]}
    assert sources["good.txt"]["ok"] is True and sources["bad.doc"]["ok"] is False


def test_no_input_at_all_is_400():
    r = client.post("/api/parse", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


# ---- /api/aggregate --------------------------------------------------------

_SURVEY = [
    {"placement": "Employed", "salary": "85000"},
    {"placement": "Employed", "salary": "95000"},
    {"placement": "Seeking", "salary": ""},
]


def test_aggregate_json_numeric_and_categorical():
    r = client.post("/api/aggregate", json={"records": _SURVEY})
    assert r.status_code == 200
    body = r.get_json()
    assert body["results"]["salary"]["mean"] == 90000
    assert body["results"]["placement"]["mode"] == "Employed"
    assert body["meta"] == {"records": 3, "fields_analyzed": 2, "version": "1.4.0"}


def test_aggregate_fields_are_restrictive():
    r = client.post("/api/aggregate", json={"records": _SURVEY, "fields": ["salary"]})
    assert set(r.get_json()["results"]) == {"salary"}


def test_aggregate_validation_errors():
    assert client.post("/api/aggregate", json={}).status_code == 400              # no records
    assert client.post("/api/aggregate", json={"records": []}).status_code == 422  # empty
    assert client.post("/api/aggregate", json={"records": _SURVEY,
                                               "fields": "salary"}).status_code == 422
    assert client.post("/api/aggregate", json={"records": _SURVEY,
                                               "fields": ["nope"]}).status_code == 422


def test_aggregate_multipart_csv():
    r = client.post("/api/aggregate", data={
        "file": _file(b"placement,salary\nEmployed,85000\nEmployed,95000\nSeeking,\n", "survey.csv"),
        "fields": "salary,placement",
    }, content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["results"]["salary"]["mean"] == 90000
    assert body["meta"]["records"] == 3


def test_aggregate_multipart_requires_a_file():
    r = client.post("/api/aggregate", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_aggregate_casefold_json():
    recs = [{"p": "Employed"}, {"p": "employed"}, {"p": "Seeking"}]
    r = client.post("/api/aggregate", json={"records": recs, "casefold": True})
    assert r.get_json()["results"]["p"]["distinct"] == 2
    r2 = client.post("/api/aggregate", json={"records": recs, "casefold": "yes"})
    assert r2.status_code == 422  # must be a boolean


def test_aggregate_casefold_multipart():
    r = client.post("/api/aggregate", data={
        "file": _file(b"p\nEmployed\nemployed\nSeeking\n", "s.csv"),
        "casefold": "true",
    }, content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["results"]["p"]["distinct"] == 2


def test_static_assets_served():
    assert b'src="/app.js"' in client.get("/").data
    js = client.get("/app.js")
    assert js.status_code == 200 and "javascript" in js.content_type
    oa = client.get("/openapi.json")
    assert oa.status_code == 200 and oa.is_json
    assert client.get("/docs").status_code == 200
