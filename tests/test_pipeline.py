from parser import parse
from tests.test_classify import DATA_ENGINEER_JD


def test_data_engineer_end_to_end():
    r = parse(DATA_ENGINEER_JD)
    assert r["primary"]["label"] == "Data Science"
    assert r["primary"]["id"] == "data_science"
    assert r["primary"]["type"] == "field"
    assert r["secondary"]["label"] == "Software Industry"
    assert r["secondary"]["id"] == "software_industry"
    assert r["meta"]["low_confidence"] is False
    assert len(r["keywords"]) > 0
    # Keywords feed the researcher API: should surface specific data terms.
    terms = " ".join(k["term"] for k in r["keywords"])
    assert any(token in terms for token in ("etl", "data", "spark", "warehouse"))


def test_response_shape_is_stable():
    r = parse("Machine learning with neural networks and PyTorch.")
    assert set(r.keys()) == {"primary", "secondary", "emphases", "keywords", "meta"}
    assert set(r["meta"].keys()) == {"token_count", "confidence", "low_confidence", "version"}
    for kw in r["keywords"]:
        assert set(kw.keys()) == {
            "term", "display", "score", "source", "related_emphasis", "related_emphasis_id"
        }


def test_keywords_are_linked_to_parent_emphasis():
    r = parse(DATA_ENGINEER_JD)
    related = {k["related_emphasis"] for k in r["keywords"]}
    assert "Data Science" in related


def test_business_posting_gets_business_field():
    text = (
        "Introduction to Business and Management. Fundamental concepts of business "
        "management and leadership, business strategy, and operations management."
    )
    r = parse(text)
    labels = {e["label"] for e in r["emphases"]}
    assert "Business & Management" in labels


def test_unmatched_text_is_low_confidence():
    r = parse("the and or but if then of to")
    assert r["primary"] is None
    assert r["meta"]["low_confidence"] is True


def test_max_keywords_is_respected():
    r = parse(DATA_ENGINEER_JD, max_keywords=5)
    assert len(r["keywords"]) <= 5


def test_physics_lecture_classifies_as_physics_and_academia():
    text = (
        "Today's lecture covers classical mechanics: Newton's laws, momentum, velocity, "
        "and acceleration under a constant force. Homework from the textbook is due before "
        "the next lecture and the exam covers this coursework."
    )
    r = parse(text)
    labels = {e["label"] for e in r["emphases"]}
    assert "Physics" in labels
    assert r["primary"] is not None
    assert "Academia & Education" in labels
