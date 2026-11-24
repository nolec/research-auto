import json

import pytest


def test_two_disjoint_sets_hidden_labels():
    from src.extraction import solution_gap_holdout_v2 as v2

    doc, labels, cases = v2.prepare()
    assert len(labels["regression"]) == 18
    assert len(labels["fresh"]) == 15
    assert set(labels["regression"]).isdisjoint(labels["fresh"])
    assert len(cases) == 33
    assert all(set(row) == {"id", "scope", "problem", "followup", "context"}
               for row in json.loads(doc["text"]))


def test_rejects_reused_source_in_fresh_set():
    from src.extraction import solution_gap_holdout_v2 as v2
    from src.extraction import solution_gap_holdout as v1

    new = json.loads(v2.MANIFEST.read_text())
    old = json.loads(v1.MANIFEST.read_text())
    new["cases"][0]["source_id"] = old["cases"][0]["source_id"]
    with pytest.raises(ValueError, match="overlap"):
        v2.prepare(new)


def test_separate_gates_do_not_hide_fresh_failure(tmp_path):
    from src.extraction import solution_gap_holdout_v2 as v2

    def call(doc):
        rows = [{"id": row["id"], "state": "UNKNOWN", "problem_quote": row["problem"],
                 "followup_quote": row["followup"]} for row in json.loads(doc["text"])]
        return {"document_id": doc["document_id"], "rows": rows}, {}

    result = v2.execute(tmp_path / "run", call)
    assert result["status"] == "MEASURED"
    assert result["regression"]["correct"] == 3
    assert result["fresh"]["correct"] == 4
    assert result["regression"]["total"] == 18
    assert result["fresh"]["total"] == 15
    assert result["h10_corrected"] is True
    assert result["gate"] == "FAIL"
    assert result["official_opportunities"] == 0
    assert len(json.loads((tmp_path / "run" / "predictions.json").read_text())["rows"]) == 33


def test_incomplete_call_never_reports_semantic_metrics(tmp_path):
    from src.extraction import solution_gap_holdout_v2 as v2
    from src.extraction.codex_cli_diagnostic import CliContractError

    def call(_doc):
        raise CliContractError("CLI_NONZERO_EXIT", error_class="PERMISSION_ERROR")

    result = v2.execute(tmp_path / "blocked", call)
    assert result["status"] == "INCOMPLETE"
    assert result["gate"] == "NOT_EVALUATED"
    assert result["error_class"] == "PERMISSION_ERROR"
    assert "fresh" not in result and "regression" not in result


def test_both_subsets_and_h10_must_pass():
    from src.extraction import solution_gap_holdout_v2 as v2

    passing = {"accuracy": 1.0, "false_discard": 0, "false_gap_promotion": 0,
               "unsupported_paid_claim": 0, "invalid": 0}
    assert v2.gate(passing, passing, True) == "PASS_DEVELOPMENT_ONLY"
    assert v2.gate(passing, {**passing, "false_gap_promotion": 1}, True) == "FAIL"
    assert v2.gate(passing, passing, False) == "FAIL"
