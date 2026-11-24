import pytest

from src.extraction import semantic_problem_holdout as holdout


def test_holdout_complete_labels_bound_to_snapshot():
    docs = [{"document_id": "x"}, {"document_id": "y"}]
    payload = {"snapshot_sha256": "abc", "labels": {"x": "yes", "y": "unknown"}}
    assert holdout.read_labels(docs, "abc", payload) == {"x": "yes", "y": "unknown"}
    for altered in (
        {**payload, "snapshot_sha256": "other"},
        {**payload, "labels": {"x": "yes"}},
        {**payload, "labels": {"x": "yes", "y": "maybe"}},
    ):
        with pytest.raises(ValueError):
            holdout.read_labels(docs, "abc", altered)


def test_ai_review_is_accepted_with_distinct_provenance_and_reasons():
    docs = [{"document_id": "x"}]
    payload = {"snapshot_sha256": "abc", "presentation": "ai_source_review",
               "labels": {"x": "yes"}, "reasons": {"x": "Observed failure"}}
    assert holdout.read_labels(docs, "abc", payload) == {"x": "yes"}
    assert holdout.review_label_type(payload) == "AI_REVIEWED_HELDOUT_DIAGNOSTIC"
    with pytest.raises(ValueError):
        holdout.read_labels(docs, "abc", {**payload, "reasons": {}})


def test_real_holdout_has_four_sources_and_excludes_development():
    documents, _ = holdout.prepare()
    assert len(documents) == 40
    assert len({d["document_id"] for d in documents}) == 40
    assert {source: sum(d["source"] == source for d in documents)
            for source in ("github", "stackexchange", "steam", "ted")} == {
                "github": 10, "stackexchange": 10, "steam": 10, "ted": 10}


def test_korean_review_records_all_original_documents_without_labels():
    import json
    documents, digest = holdout.prepare()
    html = holdout.render(documents, digest, korean=True)
    data = json.loads(html.split("const data=", 1)[1].split(";\n", 1)[0])
    assert data["presentation"] == "ai_summary_ko"
    assert len(data["records"]) == 40
    assert all(0 < len(row["summary_ko"]) < 250 for row in data["records"])
    assert [{k: v for k, v in row.items() if k != "summary_ko"} for row in data["records"]] == documents
    assert "labels" not in data
    by_id = {row["document_id"]:row["summary_ko"] for row in data["records"]}
    assert "일부는 이미 한계에 도달했다" in by_id["ted:efc42285-6b71-483f-b8ec-ba6bcc05c505"]
    assert "초과" not in by_id["ted:efc42285-6b71-483f-b8ec-ba6bcc05c505"]
