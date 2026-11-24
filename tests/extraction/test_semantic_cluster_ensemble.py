from src.extraction import semantic_cluster_ensemble as ensemble


def test_overlapping_groups_preserve_distinct_tasks_without_transitive_merges():
    result = ensemble.combine(
        [{"name": "cleaning", "members": ["a", "b"]}],
        [{"name": "laundry", "members": ["a", "b"]},
         {"name": "cooking", "members": ["b", "c"]}],
        [("a", "b", "same"), ("b", "c", "same"), ("a", "c", "different")],
    )
    assert len(result["proposals"]) == 3
    assert result["unique_merged_pairs"] == 2
    assert result["semantic"]["false_merges"] == 0


def test_real_saved_runs_are_combined_without_promoting_opportunities():
    result = ensemble.prepare()
    assert result["documents"] == 41
    assert result["unique_merged_pairs"] == 4
    assert result["semantic"]["true_merges"] == 4
    assert result["semantic"]["false_merges"] == 0
    assert result["official_opportunities"] == 0
