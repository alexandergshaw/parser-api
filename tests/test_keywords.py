from parser.classify import ScoredCategory
from parser.keywords import Keyword, merge_keywords, rake
from parser.normalize import load_stopwords, to_chunks

STOP = load_stopwords()


def test_rake_extracts_multiword_phrases():
    kws = rake(to_chunks("We build scalable data pipelines for machine learning."), STOP)
    assert any(" " in k.term for k in kws)
    assert all(0.0 <= k.score <= 1.0 for k in kws)


def test_rake_splits_on_stopwords():
    terms = {k.term for k in rake(to_chunks("python and java"), STOP)}
    assert "python" in terms and "java" in terms
    assert "python java" not in terms


def test_rake_returns_nothing_for_only_stopwords():
    assert rake(to_chunks("the and of but"), STOP) == []


def test_merge_dedupes_and_tags_source():
    rake_kws = [Keyword("data pipeline", 1.0, "rake"), Keyword("analytics platform", 0.8, "rake")]
    scored = [
        ScoredCategory("data_science", "Data Science", "field", 0.6, 10.0, ["etl", "data pipeline"])
    ]
    merged = {k.term: k for k in merge_keywords(rake_kws, scored, 10)}
    assert merged["etl"].source == "lexicon"
    assert merged["data pipeline"].source == "rake+lexicon"
    assert merged["analytics platform"].source == "rake"
