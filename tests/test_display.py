import json

from parser import parse
from parser.taxonomy import get_taxonomy
from tests.test_classify import DATA_ENGINEER_JD


def _keyword(result, term):
    return next((k for k in result["keywords"] if k["term"] == term), None)


def test_acronym_terms_get_authored_display():
    r = parse("We run ETL jobs through our CI/CD pipeline.", max_keywords=20)
    etl = _keyword(r, "etl")
    cicd = _keyword(r, "cicd")
    assert etl is not None and etl["display"] == "ETL"
    assert cicd is not None and cicd["display"] == "CI/CD"
    # term stays the lowercased join key
    assert etl["term"] == "etl" and cicd["term"] == "cicd"


def test_rake_phrase_keeps_most_frequent_source_casing():
    text = "Distributed Tracing. We use Distributed Tracing. Our distributed tracing stack."
    r = parse(text, max_keywords=20)
    kw = _keyword(r, "distributed tracing")
    assert kw is not None
    assert kw["source"] == "rake"  # not a lexicon term
    assert kw["display"] == "Distributed Tracing"  # title-case form is most frequent


def test_authored_display_applied_to_matched_terms():
    r = parse("Our ETL and SQL pipeline.", max_keywords=10)
    assert "ETL" in r["primary"]["matched_terms"]
    assert "SQL" in r["primary"]["matched_terms"]


def test_related_emphasis_id_matches_taxonomy_and_is_consistent():
    ids = {c.id for c in get_taxonomy().categories}
    r = parse(DATA_ENGINEER_JD)
    for kw in r["keywords"]:
        if kw["related_emphasis"] is None:
            assert kw["related_emphasis_id"] is None
        else:
            assert kw["related_emphasis_id"] in ids


def test_output_is_byte_identical_across_runs():
    a = json.dumps(parse(DATA_ENGINEER_JD))
    b = json.dumps(parse(DATA_ENGINEER_JD))
    assert a == b


def test_backward_compatible_fields_unchanged():
    r = parse(DATA_ENGINEER_JD)
    # term is always the lowercased, de-punctuated join key
    for kw in r["keywords"]:
        assert kw["term"] == kw["term"].lower()
        assert kw["related_emphasis"] is None or isinstance(kw["related_emphasis"], str)
        assert 0.0 <= kw["score"] <= 1.0
    # meta shape is unchanged
    assert set(r["meta"].keys()) == {"token_count", "confidence", "low_confidence", "version"}
    assert r["meta"]["version"] == "0.3.2"
