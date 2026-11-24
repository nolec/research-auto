import pytest

from src.extraction import semantic_cluster_development as cluster


def test_rejects_duplicate_or_missing_members():
    ids = {"a", "b", "c"}
    for groups in (
        [{"name": "x", "members": ["a", "b"]}],
        [{"name": "x", "members": ["a", "b"]}, {"name": "y", "members": ["b", "c"]}],
        [{"name": "x", "members": ["a", "b", "c", "d"]}],
    ):
        with pytest.raises(ValueError):
            cluster.validate_partition(ids, groups)


def test_pair_metrics_separate_missed_merges_and_false_merges():
    pairs = [("a", "b", "same"), ("a", "c", "different"),
             ("a", "d", "same"), ("b", "c", "unknown")]
    groups = [{"name": "x", "members": ["a", "b", "c"]},
              {"name": "y", "members": ["d"]}]
    result = cluster.evaluate(pairs, groups)
    assert result["true_merges"] == 1
    assert result["false_merges"] == 1
    assert result["missed_merges"] == 1
    assert result["uncertain_merges"] == 1
    assert result["merge_precision"] == 0.5
    assert result["merge_recall"] == 0.5


def test_saved_input_has_positive_and_negative_reference_pairs():
    records, pairs, bindings = cluster.prepare()
    assert len(records) == 41
    assert sum(p[2] == "same" for p in pairs) == 4
    assert sum(p[2] == "different" for p in pairs) == 9
    assert len({r["id"] for r in records}) == len(records)
    assert bindings["input_sha256"]
