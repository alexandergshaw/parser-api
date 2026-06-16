import json

from parser.classify import classify, emphasis_lens, link_term
from parser.normalize import count_ngrams, singularize, stem_chunks, to_chunks
from parser.taxonomy import get_taxonomy, load_taxonomy

DATA_ENGINEER_JD = """
Senior Data Engineer. We are seeking a Data Engineer to design and build scalable
data pipelines and ETL workflows that power our analytics platform. You will own our
data warehouse and data lake, handle data modeling for downstream consumers, and
optimize big data processing with Spark and Airflow. Strong SQL and Python skills are
required, plus feature engineering for machine learning use cases. You'll work in an
Agile team, participate in code review, and ship through our CI/CD pipeline. Experience
with Kafka, dbt, Snowflake, AWS, Docker, and Kubernetes is a plus.
"""


def _scored(text):
    tax = get_taxonomy()
    counts = count_ngrams(stem_chunks(to_chunks(text)), tax.max_term_n)
    return classify(counts, tax)


def test_data_engineer_field_and_sector_tops():
    scored = _scored(DATA_ENGINEER_JD)
    assert emphasis_lens(scored, "field", 0.15)["top"]["id"] == "data_science"
    assert emphasis_lens(scored, "sector", 0.15)["top"]["id"] == "software_industry"


def test_per_axis_scores_sum_to_one():
    field = emphasis_lens(_scored(DATA_ENGINEER_JD), "field", 0.15)
    assert 0.99 <= sum(e["score"] for e in field["ranked"]) <= 1.01


def test_matched_terms_use_display_casing():
    scored = _scored("Deep learning with a neural network trained in PyTorch.")
    ml = next(s for s in scored if s.id == "machine_learning")
    assert "Neural Network" in ml.matched_terms
    assert "neural network" in ml.matched_keys


def test_lone_ambiguous_word_is_not_an_emphasis():
    scored = _scored("Engage students with genuine energy; current expertise; professor role.")
    ids = {s.id for s in scored}
    assert "physics" not in ids and "electrical_engineering" not in ids


def test_singularize_handles_plurals_and_leaves_others_alone():
    assert singularize("networks") == "network"
    assert singularize("pipelines") == "pipeline"
    assert singularize("libraries") == "library"
    for word in ("analysis", "status", "sql", "etl", "data", "css"):
        assert singularize(word) == word


def test_link_term_points_to_top_related_emphasis():
    rel = link_term("spark", _scored(DATA_ENGINEER_JD))
    assert rel is not None and rel["id"] == "data_science"


def test_no_match_returns_empty():
    assert _scored("the quick brown fox jumped over the lazy dog") == []


def test_idf_downweights_shared_terms(tmp_path):
    (tmp_path / "fields.json").write_text(
        json.dumps(
            [
                {"id": "a", "label": "A", "terms": [{"term": "common"}, {"term": "alpha"}]},
                {"id": "b", "label": "B", "terms": [{"term": "common"}, {"term": "beta"}]},
                {"id": "c", "label": "C", "terms": [{"term": "common"}, {"term": "gamma"}]},
            ]
        ),
        encoding="utf-8",
    )
    tax = load_taxonomy(tmp_path)
    assert tax.idf["common"] < tax.idf["alpha"]
