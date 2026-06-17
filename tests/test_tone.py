import json

from parser import parse
from parser.normalize import count_ngrams, stem_chunks, to_chunks
from parser.tone import load_tones, score_tone


def _tone(text):
    dims = parse(text, targets=["tone"])["results"]["tone"]["dimensions"]
    return {d["name"]: d for d in dims}


def test_formal_vs_casual():
    assert _tone("Pursuant to the agreement, we shall therefore proceed accordingly.")["formality"]["leaning"] == "formal"
    assert _tone("gonna grab some cool stuff, kinda awesome you guys")["formality"]["leaning"] == "casual"


def test_sentiment_positive_vs_negative():
    assert _tone("An excellent, outstanding, and effective success.")["sentiment"]["leaning"] == "positive"
    assert _tone("A poor, weak failure and a serious problem.")["sentiment"]["leaning"] == "negative"


def test_light_negation_flips_sentiment():
    assert _tone("This is great.")["sentiment"]["leaning"] == "positive"
    assert _tone("This is not great.")["sentiment"]["leaning"] == "negative"


def test_urgency_intensity_rises_with_cues():
    low = _tone("We will review the document at some point.")["urgency"]["score"]
    high = _tone("Urgent: the critical deadline is immediately; respond asap.")["urgency"]["score"]
    assert high > low and high > 0.3


def test_enthusiasm_boosted_by_exclamation():
    plain = _tone("The team will work on the project.")["enthusiasm"]["score"]
    loud = _tone("We are thrilled and excited! Amazing energy!")["enthusiasm"]["score"]
    assert loud > plain


def test_neutral_text_is_neutral():
    t = _tone("The cat sat on the mat near the table.")
    assert t["formality"]["leaning"] == "neutral" and t["sentiment"]["leaning"] == "neutral"


def test_dimensions_follow_config_and_carry_evidence():
    dims = parse("An excellent, outstanding result.", targets=["tone"])["results"]["tone"]["dimensions"]
    assert [d["name"] for d in dims] == ["formality", "sentiment", "urgency", "enthusiasm"]
    sentiment = next(d for d in dims if d["name"] == "sentiment")
    assert "excellent" in sentiment["evidence"]


def test_adding_a_tone_dimension_is_data_only(tmp_path):
    # A brand-new tone dimension works from a data file alone — no code change.
    spec = tmp_path / "tones.json"
    spec.write_text(
        json.dumps([{"name": "humor", "label": "Humor", "high_label": "humorous",
                     "high": ["funny", "hilarious", "joke"]}]),
        encoding="utf-8",
    )
    model = load_tones(spec)
    assert [d.name for d in model.dimensions] == ["humor"]
    text = "That was a hilarious and funny joke."
    counts = count_ngrams(stem_chunks(to_chunks(text)), model.max_term_n)
    res = score_tone(model, counts, to_chunks(text), text)
    assert res["dimensions"][0]["leaning"] == "humorous"
