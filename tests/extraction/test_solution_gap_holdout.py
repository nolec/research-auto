import json

import pytest


def test_holdout_model_input_excludes_labels_rationale_and_provenance():
    from src.extraction import solution_gap_holdout as holdout

    doc, labels, cases = holdout.prepare()
    assert len(labels) == len(cases) == 18
    assert set(labels.values()) == {"RESOLVED", "PERSISTING", "PAID_PERSISTING", "ADJACENT", "UNKNOWN"}
    assert all(set(row) == {"id", "scope", "problem", "followup", "context"}
               for row in json.loads(doc["text"]))
    assert doc["source"] == "public-evidence-excerpts"


def test_rejects_duplicate_source_and_excessive_quotation():
    from src.extraction import solution_gap_holdout as holdout

    data = json.loads(holdout.MANIFEST.read_text())
    data["cases"][1]["source_id"] = data["cases"][0]["source_id"]
    with pytest.raises(ValueError, match="duplicate"):
        holdout.prepare(data)
    data = json.loads(holdout.MANIFEST.read_text())
    data["cases"][0]["problem"] = "word " * 30
    with pytest.raises(ValueError, match="quote budget"):
        holdout.prepare(data)


def test_measured_batch_uses_existing_scoring_and_never_promotes(tmp_path):
    from src.extraction import solution_gap_holdout as holdout

    def call(document):
        rows = [{"id": row["id"], "state": "UNKNOWN", "problem_quote": row["problem"],
                 "followup_quote": row["followup"]} for row in json.loads(document["text"])]
        return {"document_id": document["document_id"], "rows": rows}, {}

    result = holdout.execute(tmp_path / "run", call)
    assert result["status"] == "MEASURED"
    assert result["semantic"]["correct"] == 3
    assert result["semantic"]["missed_persisting"] == 8
    assert result["gate"] == "FAIL"
    assert result["official_opportunities"] == 0
    assert len(json.loads((tmp_path / "run" / "predictions.json").read_text())["rows"]) == 18
    with pytest.raises(FileExistsError):
        holdout.execute(tmp_path / "run", call)


def test_permission_failure_has_no_semantic_score(tmp_path):
    from src.extraction import solution_gap_holdout as holdout
    from src.extraction.codex_cli_diagnostic import CliContractError

    def call(_document):
        raise CliContractError("CLI_NONZERO_EXIT", error_class="PERMISSION_ERROR")

    result = holdout.execute(tmp_path / "blocked", call)
    assert result["status"] == "INCOMPLETE"
    assert result["error_class"] == "PERMISSION_ERROR"
    assert "semantic" not in result
    assert result["gate"] == "NOT_EVALUATED"


def test_gate_requires_no_critical_errors_even_with_90_percent():
    from src.extraction import solution_gap_holdout as holdout

    score = {"accuracy": 0.95, "false_discard": 0, "false_gap_promotion": 0,
             "unsupported_paid_claim": 0, "invalid": 0}
    assert holdout.gate(score) == "PASS_DEVELOPMENT_ONLY"
    assert holdout.gate({**score, "unsupported_paid_claim": 1}) == "FAIL"
    assert holdout.gate({**score, "accuracy": 0.89}) == "FAIL"
