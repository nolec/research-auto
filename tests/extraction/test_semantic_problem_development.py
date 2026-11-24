import pytest

from src.extraction import semantic_problem_development as semantic


def test_requires_source_grounded_positive():
    doc = {"document_id": "a", "text": "My report has duplicate rows."}
    output = dict(document_id="a", state="yes", actor="report author", task="prepare report",
                  obstacle="duplicate rows", outcome=None, quote="My report has duplicate rows.")
    semantic.validate(doc, output)
    with pytest.raises(ValueError):
        semantic.validate(doc, {**output, "quote": "I paid for a fix."})
    with pytest.raises(ValueError):
        semantic.validate(doc, {**output, "task": None})


def test_abstention_cannot_carry_unverified_problem():
    doc = {"document_id": "a", "text": "Great tool."}
    with pytest.raises(ValueError):
        semantic.validate(doc, dict(document_id="a", state="unknown", actor="customer",
                                   task=None, obstacle=None, outcome=None, quote=None))


def test_metrics_count_invalid_and_unknown_as_missed_positives():
    gold = {"a": "yes", "b": "yes", "c": "yes", "d": "no", "e": "unknown"}
    result = semantic.compare(gold, {"a": "yes", "b": "invalid", "c": "unknown",
                                     "d": "yes", "e": "yes"})
    assert result["positive_recall"] == 1 / 3
    assert result["positive_precision"] == 1 / 2
    assert result["invalid"] == 1
    assert result["unknown_gold_predicted_yes"] == 1


def test_incomplete_run_is_not_a_quality_measurement():
    with pytest.raises(ValueError):
        semantic.compare({"a": "yes", "b": "no"}, {"a": "yes"})


def test_batch_marks_malformed_schema_invalid_and_retains_other_answers(tmp_path):
    documents = [{"document_id": "a", "text": "Great app."},
                 {"document_id": "b", "text": "Great tool."}]
    gold = {"a": "no", "b": "no"}

    def call(doc):
        if doc["document_id"] == "a":
            return {"document_id": "a", "state": "no"}, {}
        return dict(document_id="b", state="no", actor=None, task=None,
                    obstacle=None, outcome=None, quote=None), {}

    result = semantic.execute(tmp_path / "run", documents, gold, {}, call)
    assert result["status"] == "MEASURED"
    assert result["semantic"]["invalid"] == 1
    assert result["semantic"]["by_label"]["no"]["no"] == 1
