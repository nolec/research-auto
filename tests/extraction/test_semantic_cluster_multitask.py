import pytest

from src.extraction import semantic_cluster_multitask as multi
from src.extraction import semantic_cluster_development as single


def test_decomposed_tasks_preserve_parent_and_require_exact_evidence():
    records = [{"id": "a", "kind": "archived_buyer_summary", "source": "test",
                "summary": "Weekly cleaning and laundry"}]
    rows = [{"source_id": "a", "tasks": [
        {"description": "house cleaning", "field": "summary", "evidence": "cleaning"},
        {"description": "laundry", "field": "summary", "evidence": "laundry"}]}]
    atoms = multi.decompose(records, rows)
    assert [a["source_id"] for a in atoms] == ["a", "a"]
    assert len({a["id"] for a in atoms}) == 2
    rows[0]["tasks"][0]["evidence"] = "cooking"
    with pytest.raises(ValueError):
        multi.decompose(records, rows)
    with pytest.raises(ValueError):
        multi.decompose(records, [])


def test_source_overlap_does_not_transitively_merge_unrelated_tasks():
    atoms = [{"id": "1", "source_id": "a"}, {"id": "2", "source_id": "a"},
             {"id": "3", "source_id": "b"}, {"id": "4", "source_id": "c"}]
    groups = [{"name": "cleaning", "members": ["1", "3"]},
              {"name": "laundry", "members": ["2", "4"]}]
    projected = multi.project_groups(atoms, groups)
    metrics = single.evaluate([("a", "b", "same"), ("a", "c", "same"),
                               ("b", "c", "different")], projected)
    assert metrics["true_merges"] == 2
    assert metrics["false_merges"] == 0
    assert metrics["correct_separations"] == 1
    with pytest.raises(ValueError):
        multi.project_groups(atoms, [{"name": "duplicate parent",
                                      "members": ["1", "2", "3", "4"]}])
