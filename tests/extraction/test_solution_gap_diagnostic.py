import json

import pytest


def test_input_hides_reference_labels():
    from src.extraction import solution_gap_diagnostic as gap

    document, labels, cases = gap.prepare()
    payload = json.loads(document["text"])
    assert len(labels) == len(cases) == 20
    assert set(labels.values()) == {"RESOLVED", "PERSISTING", "PAID_PERSISTING", "ADJACENT", "UNKNOWN"}
    assert all(set(case) == {"id", "scope", "problem", "followup"} for case in payload)
    assert len({case["id"] for case in payload}) == 20


def test_grounded_predictions_reject_invented_evidence_and_duplicate_ids():
    from src.extraction import solution_gap_diagnostic as gap

    cases = [{"id": "a", "problem": "I spend an hour correcting it weekly.",
              "followup": "The new setting still drops records."}]
    row = {"id": "a", "state": "PERSISTING", "problem_quote": "I spend an hour", 
           "followup_quote": "still drops records"}
    assert gap.project(cases, [row]) == {"a": "PERSISTING"}
    assert gap.project(cases, [{**row, "followup_quote": "I paid $100"}]) == {"a": "INVALID"}
    with pytest.raises(ValueError):
        gap.project(cases, [row, row])
    with pytest.raises(ValueError):
        gap.project(cases, [])


def test_metrics_distinguish_false_discard_false_promotion_and_payment_claim():
    from src.extraction import solution_gap_diagnostic as gap

    gold = {"a": "PERSISTING", "b": "RESOLVED", "c": "UNKNOWN", "d": "PAID_PERSISTING", "e": "ADJACENT"}
    observed = {"a": "RESOLVED", "b": "PERSISTING", "c": "PAID_PERSISTING", "d": "INVALID", "e": "UNKNOWN"}
    result = gap.compare(gold, observed)
    assert result["correct"] == 0
    assert result["false_discard"] == 1
    assert result["false_gap_promotion"] == 2
    assert result["unsupported_paid_claim"] == 1
    assert result["missed_persisting"] == 2
    assert result["invalid"] == 1
    with pytest.raises(ValueError):
        gap.compare(gold, {"a": "RESOLVED"})


def test_failed_model_call_never_reports_accuracy(tmp_path):
    from src.extraction import solution_gap_diagnostic as gap
    from src.extraction.codex_cli_diagnostic import CliContractError

    def call(_document):
        raise CliContractError("CLI_NONZERO_EXIT", error_class="PERMISSION_ERROR")

    result = gap.execute(tmp_path / "run", call)
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "CLI_NONZERO_EXIT"
    assert result["error_class"] == "PERMISSION_ERROR"
    assert "semantic" not in result
    assert result["official_opportunities"] == 0
    assert json.loads((tmp_path / "run" / "result.json").read_text()) == result


def test_missing_cli_is_not_a_permission_error(tmp_path):
    from src.extraction import solution_gap_diagnostic as gap

    def call(_document):
        raise FileNotFoundError("missing executable")

    result = gap.execute(tmp_path / "run", call)
    assert result["status"] == "INCOMPLETE"
    assert result["error_class"] == "EXECUTABLE_NOT_FOUND"


def test_complete_batch_retains_invalid_rows_without_promoting_cards(tmp_path):
    from src.extraction import solution_gap_diagnostic as gap

    def call(document):
        cases = json.loads(document["text"])
        rows = [{"id": case["id"], "state": "UNKNOWN",
                 "problem_quote": case["problem"].split()[0],
                 "followup_quote": case["followup"].split()[0]} for case in cases]
        rows[0]["problem_quote"] = "invented text"
        return {"document_id": document["document_id"], "rows": rows}, {}

    result = gap.execute(tmp_path / "run", call)
    assert result["status"] == "MEASURED"
    assert result["semantic"]["invalid"] == 1
    assert result["semantic"]["correct"] == 4
    assert result["official_opportunities"] == 0
    assert json.loads((tmp_path / "run" / "predictions.json").read_text())["projection"]["sg01"] == "INVALID"
