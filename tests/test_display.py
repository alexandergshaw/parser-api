import json

from parser import parse


def _kw(result, term):
    return next((k for k in result["results"]["keywords"]["items"] if k["term"] == term), None)


def test_acronym_terms_get_authored_display():
    r = parse("We run ETL jobs through our CI/CD pipeline.", targets=["keywords"], max_keywords=20)
    etl, cicd = _kw(r, "etl"), _kw(r, "cicd")
    assert etl is not None and etl["display"] == "ETL"
    assert cicd is not None and cicd["display"] == "CI/CD"


def test_rake_phrase_keeps_most_frequent_source_casing():
    text = "Distributed Tracing. We use Distributed Tracing. Our distributed tracing stack."
    kw = _kw(parse(text, targets=["keywords"], max_keywords=20), "distributed tracing")
    assert kw is not None and kw["source"] == "rake" and kw["display"] == "Distributed Tracing"


def test_authored_display_applied_to_emphasis_matched_terms():
    r = parse("Our ETL and SQL pipeline.", targets=["field"])
    assert "ETL" in r["results"]["field"]["top"]["matched_terms"]


def test_technologies_lens_display_and_dynamic_link():
    r = parse("Build data pipelines with Spark and Kubernetes deployed on AWS.", targets=["technologies"])
    by_display = {m["display"]: m for m in r["results"]["technologies"]["matched"]}
    assert {"Spark", "Kubernetes", "AWS"} <= set(by_display)
    assert by_display["AWS"]["related"]["id"] == "devops"


def test_output_is_byte_identical_across_runs():
    a = json.dumps(parse("Senior Data Engineer with Spark and Python on AWS."))
    b = json.dumps(parse("Senior Data Engineer with Spark and Python on AWS."))
    assert a == b


def test_version_is_reported():
    assert parse("Machine learning with neural networks.")["meta"]["version"] == "1.0.0"
