from parser.classify import ScoredCategory
from parser.keywords import Keyword, merge_keywords, rake
from parser.normalize import build_surface_index, load_stopwords, to_chunks

STOP = load_stopwords()


def _rake(text):
    return rake(to_chunks(text), STOP, build_surface_index(text))


def test_rake_extracts_multiword_phrases():
    kws = _rake("We build scalable data pipelines for machine learning.")
    assert any(" " in k.term for k in kws)
    assert all(0.0 <= k.score <= 1.0 for k in kws)


def test_rake_splits_on_stopwords():
    terms = {k.term for k in _rake("python and java")}
    assert "python" in terms and "java" in terms
    assert "python java" not in terms


def test_rake_returns_nothing_for_only_stopwords():
    assert _rake("the and of but") == []


def test_merge_dedupes_and_tags_source():
    rake_kws = [Keyword("data pipeline", 1.0, "rake"), Keyword("analytics platform", 0.8, "rake")]
    scored = [
        ScoredCategory(
            id="data_science",
            label="Data Science",
            type="field",
            score=0.6,
            raw_score=10.0,
            matched_terms=["ETL", "Data Pipeline"],   # authored display
            matched_keys=["etl", "data pipeline"],     # stemmed canonical keys
            matched_surfaces=["etl", "data pipeline"], # lowercased join keys
        )
    ]
    merged = {k.term: k for k in merge_keywords(rake_kws, scored, 10)}
    assert merged["etl"].source == "lexicon"
    assert merged["etl"].display == "ETL"
    assert merged["data pipeline"].source == "rake+lexicon"
    assert merged["data pipeline"].display == "Data Pipeline"
    assert merged["analytics platform"].source == "rake"
