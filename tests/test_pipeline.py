import pytest

from parser import parse
from tests.test_classify import DATA_ENGINEER_JD


def test_default_targets_shape():
    r = parse(DATA_ENGINEER_JD)
    assert set(r["results"]) == {"field", "sector", "keywords"}
    assert set(r["meta"]) == {"token_count", "version"}


def test_field_and_sector_tops():
    r = parse(DATA_ENGINEER_JD)
    assert r["results"]["field"]["top"]["id"] == "data_science"
    assert r["results"]["sector"]["top"]["id"] == "software_industry"


def test_targets_are_restrictive():
    r = parse(DATA_ENGINEER_JD, targets=["technologies"])
    assert set(r["results"]) == {"technologies"}


def test_technologies_lens_links_dynamically():
    r = parse(DATA_ENGINEER_JD, targets=["technologies"])
    by_display = {m["display"]: m for m in r["results"]["technologies"]["matched"]}
    assert "Spark" in by_display and by_display["Spark"]["related"]["id"] == "data_science"
    assert by_display["AWS"]["related"]["id"] == "devops"


def test_business_posting_classifies_as_business_field():
    text = (
        "Introduction to Business and Management. Concepts of business management and "
        "leadership, business strategy, and operations management."
    )
    r = parse(text, targets=["field"])
    assert r["results"]["field"]["top"]["id"] == "business_management"


def test_business_academia_posting_has_no_physics_noise():
    text = (
        "Adjunct faculty to teach business courses. Engage students with genuine energy; "
        "demonstrate current expertise; professor in higher education."
    )
    field_ids = {e["id"] for e in parse(text)["results"]["field"]["ranked"]}
    assert "physics" not in field_ids and "electrical_engineering" not in field_ids


def test_unmatched_text_yields_empty_lenses():
    r = parse("the and or but if then of to")
    assert r["results"]["field"]["top"] is None
    assert r["results"]["keywords"]["items"] == []


def test_per_target_limit_override():
    r = parse(DATA_ENGINEER_JD, targets=[{"name": "keywords", "limit": 3}])
    assert len(r["results"]["keywords"]["items"]) <= 3


def test_unknown_target_raises():
    with pytest.raises(ValueError):
        parse("x", targets=["nope"])


def test_keywords_carry_nested_related():
    r = parse(DATA_ENGINEER_JD, targets=["keywords"])
    items = r["results"]["keywords"]["items"]
    assert items and all(set(k) == {"term", "display", "score", "source", "related"} for k in items)
    linked = [k for k in items if k["related"]]
    assert linked and set(linked[0]["related"]) == {"id", "label"}
