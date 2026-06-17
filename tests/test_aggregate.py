"""Tests for parser.aggregate — deterministic statistics over record sets."""

import pytest

from parser.aggregate import aggregate, records_from_csv

# A small placement/salary survey reused across tests.
SURVEY = [
    {"placement": "Employed", "salary": "85000", "gpa": 3.6},
    {"placement": "Employed", "salary": "95000", "gpa": 3.9},
    {"placement": "Grad school", "salary": "", "gpa": 3.8},
    {"placement": "Employed", "salary": "70000", "gpa": 3.2},
    {"placement": "Seeking", "salary": "N/A", "gpa": 2.9},
]


# ---- numeric ---------------------------------------------------------------

def test_numeric_field_core_stats():
    salary = aggregate(SURVEY, fields=["salary"])["results"]["salary"]
    assert salary["kind"] == "numeric"
    assert salary["count"] == 3 and salary["missing"] == 2  # "" and "N/A"
    assert salary["mean"] == 83333.3333
    assert salary["median"] == 85000
    assert salary["min"] == 70000 and salary["max"] == 95000
    assert salary["sum"] == 250000


def test_numeric_parses_currency_and_percent():
    rows = [{"x": "$1,200"}, {"x": "$1,800"}, {"x": "50%"}]
    x = aggregate(rows, fields=[{"name": "x", "type": "numeric"}])["results"]["x"]
    assert x["min"] == 50 and x["max"] == 1800 and x["sum"] == 3050


def test_numeric_invalid_values_counted_not_crashed():
    rows = [{"salary": "80000"}, {"salary": "TBD"}, {"salary": "90000"}]
    salary = aggregate(rows, fields=[{"name": "salary", "type": "numeric"}])["results"]["salary"]
    assert salary["count"] == 2 and salary["invalid"] == 1
    assert salary["mean"] == 85000


def test_stdev_and_quartiles_need_two_points():
    one = aggregate([{"v": 5}], fields=["v"])["results"]["v"]
    assert one["stdev"] is None and one["p25"] is None and one["p75"] is None
    two = aggregate([{"v": 0}, {"v": 10}], fields=["v"])["results"]["v"]
    assert two["stdev"] is not None and two["p25"] is not None


def test_booleans_are_categorical_not_numeric():
    rows = [{"hired": True}, {"hired": False}, {"hired": True}]
    hired = aggregate(rows, fields=["hired"])["results"]["hired"]
    assert hired["kind"] == "categorical"
    assert hired["mode"] == "True" and hired["distinct"] == 2


# ---- categorical -----------------------------------------------------------

def test_categorical_frequencies_mode_and_proportions():
    placement = aggregate(SURVEY, fields=["placement"])["results"]["placement"]
    assert placement["kind"] == "categorical"
    assert placement["count"] == 5 and placement["distinct"] == 3
    assert placement["mode"] == "Employed"
    top = placement["frequencies"][0]
    assert top == {"value": "Employed", "count": 3, "proportion": 0.6}


def test_categorical_ties_sorted_deterministically():
    rows = [{"c": "b"}, {"c": "a"}]  # equal counts → alphabetical
    freqs = aggregate(rows, fields=["c"])["results"]["c"]["frequencies"]
    assert [f["value"] for f in freqs] == ["a", "b"]


def test_categorical_limit_truncates_but_keeps_distinct():
    rows = [{"c": v} for v in ["a", "a", "b", "c", "d"]]
    c = aggregate(rows, fields=[{"name": "c", "limit": 2}])["results"]["c"]
    assert c["distinct"] == 4 and c["truncated"] is True
    assert len(c["frequencies"]) == 2 and c["frequencies"][0]["value"] == "a"


# ---- detection / missing ---------------------------------------------------

def test_auto_type_detection_by_ratio():
    res = aggregate(SURVEY)["results"]
    assert res["salary"]["kind"] == "numeric"      # mostly numbers
    assert res["placement"]["kind"] == "categorical"
    assert res["gpa"]["kind"] == "numeric"


def test_missing_tokens_and_none_excluded():
    rows = [{"v": None}, {"v": ""}, {"v": "  "}, {"v": "null"}, {"v": "x"}]
    v = aggregate(rows, fields=["v"])["results"]["v"]
    assert v["missing"] == 4 and v["count"] == 1


def test_real_word_none_is_not_treated_as_missing():
    rows = [{"a": "None of the above"}, {"a": "None of the above"}]
    a = aggregate(rows, fields=["a"])["results"]["a"]
    assert a["count"] == 2 and a["mode"] == "None of the above"


def test_field_missing_from_some_records():
    rows = [{"x": 1}, {}, {"x": 3}]  # middle row lacks the key
    x = aggregate(rows, fields=["x"])["results"]["x"]
    assert x["count"] == 2 and x["missing"] == 1


def test_empty_field_reported():
    rows = [{"x": None}, {"x": ""}]
    x = aggregate(rows, fields=["x"])["results"]["x"]
    assert x["kind"] == "empty" and x["count"] == 0 and x["missing"] == 2


# ---- selection / meta ------------------------------------------------------

def test_fields_are_restrictive_and_ordered():
    res = aggregate(SURVEY, fields=["salary", "placement"])
    assert list(res["results"]) == ["salary", "placement"]  # requested order preserved


def test_default_summarizes_all_fields_first_seen_order():
    res = aggregate(SURVEY)
    assert list(res["results"]) == ["placement", "salary", "gpa"]
    assert res["meta"]["fields_analyzed"] == 3


def test_meta_includes_record_count_and_version():
    meta = aggregate(SURVEY)["meta"]
    assert meta["records"] == 5 and meta["version"] == "1.4.0"


def test_forced_type_override():
    rows = [{"zip": "10001"}, {"zip": "90210"}]  # numeric-looking but really a label
    zip_ = aggregate(rows, fields=[{"name": "zip", "type": "categorical"}])["results"]["zip"]
    assert zip_["kind"] == "categorical" and zip_["distinct"] == 2


# ---- casefold --------------------------------------------------------------

def test_casefold_merges_case_variants():
    rows = [{"p": "Employed"}, {"p": "employed"}, {"p": "EMPLOYED"}, {"p": "Seeking"}]
    plain = aggregate(rows, fields=["p"])["results"]["p"]
    assert plain["distinct"] == 4  # case-sensitive by default

    folded = aggregate(rows, fields=["p"], casefold=True)["results"]["p"]
    assert folded["distinct"] == 2 and folded["mode"] == "employed"
    assert folded["frequencies"][0] == {"value": "employed", "count": 3, "proportion": 0.75}


def test_casefold_default_applies_to_all_fields():
    rows = [{"a": "X", "b": "Y"}, {"a": "x", "b": "y"}]
    res = aggregate(rows, casefold=True)["results"]
    assert res["a"]["distinct"] == 1 and res["b"]["distinct"] == 1


def test_per_field_casefold_overrides_global():
    rows = [{"a": "X", "b": "Y"}, {"a": "x", "b": "y"}]
    # Global on, but field `a` opts out.
    res = aggregate(rows, fields=[{"name": "a", "casefold": False}, "b"], casefold=True)["results"]
    assert res["a"]["distinct"] == 2  # opted out → case-sensitive
    assert res["b"]["distinct"] == 1  # inherits global fold


def test_bad_casefold_rejected():
    with pytest.raises(ValueError):
        aggregate(SURVEY, casefold="yes")
    with pytest.raises(ValueError):
        aggregate(SURVEY, fields=[{"name": "salary", "casefold": "nope"}])


# ---- determinism -----------------------------------------------------------

def test_output_is_deterministic():
    assert aggregate(SURVEY) == aggregate(SURVEY)


# ---- validation ------------------------------------------------------------

def test_non_list_records_rejected():
    with pytest.raises(ValueError):
        aggregate({"not": "a list"})


def test_empty_records_rejected():
    with pytest.raises(ValueError):
        aggregate([])


def test_non_dict_record_rejected():
    with pytest.raises(ValueError):
        aggregate([{"ok": 1}, "nope"])


def test_unknown_field_rejected():
    with pytest.raises(ValueError, match="Unknown field"):
        aggregate(SURVEY, fields=["nonexistent"])


def test_empty_fields_list_rejected():
    with pytest.raises(ValueError):
        aggregate(SURVEY, fields=[])


def test_bad_forced_type_rejected():
    with pytest.raises(ValueError):
        aggregate(SURVEY, fields=[{"name": "salary", "type": "bogus"}])


# ---- CSV front door --------------------------------------------------------

def test_records_from_csv_comma():
    rows = records_from_csv("placement,salary\nEmployed,85000\nSeeking,\n")
    assert rows == [
        {"placement": "Employed", "salary": "85000"},
        {"placement": "Seeking", "salary": ""},
    ]


def test_records_from_csv_sniffs_tab_and_semicolon():
    tab = records_from_csv("a\tb\n1\t2\n")
    semi = records_from_csv("a;b\n1;2\n")
    assert tab == [{"a": "1", "b": "2"}] and semi == [{"a": "1", "b": "2"}]


def test_records_from_csv_accepts_bytes_with_bom():
    rows = records_from_csv("name,age\nAda,36\n".encode("utf-8-sig"))  # encoder adds the BOM
    assert rows == [{"name": "Ada", "age": "36"}]


def test_csv_then_aggregate_end_to_end():
    rows = records_from_csv("placement,salary\nEmployed,85000\nEmployed,95000\nSeeking,\n")
    res = aggregate(rows)["results"]
    assert res["salary"]["mean"] == 90000
    assert res["placement"]["mode"] == "Employed"
