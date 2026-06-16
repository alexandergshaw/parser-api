import json

from parser.classify import classify, pick_primary_secondary
from parser.normalize import count_ngrams, singularize, stem_chunks, to_chunks
from parser.taxonomy import get_taxonomy, load_taxonomy

DATA_ENGINEER_JD = """
Senior Data Engineer. We are seeking a Data Engineer to design and build scalable
data pipelines and ETL workflows that power our analytics platform. You will own our
data warehouse and data lake, handle data modeling for downstream consumers, and
optimize big data processing with Spark and Airflow. Strong SQL and Python skills are
required, plus feature engineering for machine learning use cases. You'll work in an
Agile team, participate in code review, and ship through our CI/CD pipeline. Experience
with Kafka, dbt, and Snowflake is a plus.
"""


def _score(text):
    tax = get_taxonomy()
    counts = count_ngrams(stem_chunks(to_chunks(text)), tax.max_term_n)
    return classify(counts, tax)


def test_data_engineer_primary_and_secondary():
    primary, secondary = pick_primary_secondary(_score(DATA_ENGINEER_JD))
    assert primary is not None and primary.id == "data_science"
    assert primary.type == "field"
    assert secondary is not None and secondary.id == "software_industry"
    assert secondary.type == "sector"


def test_matched_terms_are_returned_as_evidence():
    scored = _score("Deep learning with a neural network trained in PyTorch.")
    top = scored[0]
    assert top.id == "machine_learning"
    assert "neural network" in top.matched_terms


def test_no_taxonomy_match_returns_empty():
    assert _score("the quick brown fox jumped over the lazy dog") == []


def test_scores_are_normalized_shares():
    scored = _score(DATA_ENGINEER_JD)
    total = sum(s.score for s in scored)
    assert 0.99 <= total <= 1.01
    assert scored == sorted(scored, key=lambda s: s.raw_score, reverse=True)


def test_singularize_handles_plurals_and_leaves_others_alone():
    assert singularize("networks") == "network"
    assert singularize("pipelines") == "pipeline"
    assert singularize("libraries") == "library"
    assert singularize("processes") == "process"
    # Should NOT be mangled:
    for word in ("analysis", "status", "sql", "etl", "data", "css"):
        assert singularize(word) == word


def test_plural_text_matches_singular_lexicon():
    scored = _score("We built scalable data pipelines and trained neural networks.")
    ids = {s.id for s in scored}
    assert "data_science" in ids  # "data pipelines" -> "data pipeline"
    ml = next(s for s in scored if s.id == "machine_learning")
    assert "neural network" in ml.matched_terms  # plural matched, singular displayed


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
