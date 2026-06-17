from parser import parse


def _intent(text):
    return parse(text, targets=["intent"])["results"]["intent"]


def test_job_posting_is_hiring():
    text = ("We are seeking a Data Engineer to join our team. Responsibilities and preferred "
            "qualifications below. Equal opportunity employer; benefits package.")
    assert _intent(text)["top"]["id"] == "hiring"


def test_lecture_is_teaching():
    text = "In this tutorial you will learn the learning objectives of this course."
    assert _intent(text)["top"]["id"] == "teaching"


def test_marketing_is_selling():
    text = "Special offer! Sign up for a free trial and buy now. Limited time discount."
    assert _intent(text)["top"]["id"] == "selling"


def test_research_is_informing():
    text = "Results show, and the study found, that according to the data the findings were significant."
    assert _intent(text)["top"]["id"] == "informing"


def test_howto_is_instructing():
    text = "How to set it up step by step. Follow these steps: install, configure, run the following."
    assert _intent(text)["top"]["id"] == "instructing"


def test_intent_is_restrictive_and_per_axis_normalized():
    r = parse("We are seeking candidates to join our team.", targets=["intent"])
    assert set(r["results"]) == {"intent"}
    ranked = r["results"]["intent"]["ranked"]
    assert 0.99 <= sum(e["score"] for e in ranked) <= 1.01
    assert r["results"]["intent"]["top"]["matched_terms"]


def test_intent_does_not_leak_into_field_or_sector():
    r = parse("We are seeking candidates to join our team. Equal opportunity employer.",
              targets=["field", "sector", "intent"])
    assert r["results"]["intent"]["top"]["id"] == "hiring"
    field_ids = {e["id"] for e in r["results"]["field"]["ranked"]}
    sector_ids = {e["id"] for e in r["results"]["sector"]["ranked"]}
    assert "hiring" not in field_ids and "hiring" not in sector_ids
