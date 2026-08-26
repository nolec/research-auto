from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from src.extraction.calibration_gate import (
    _write_immutable,
    build_freeze_receipt,
    evaluate_gate,
    load_gate_config,
    main,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/extraction/calibration-gate-v1.json"
BASELINE = ROOT / "artifacts/extraction/calibration/rule-v1/555d9a2e0881d2ea7d92b9882de34b7d6fa1a1d85ad9da616f28775f99acaa98"
RUN_RECEIPT = {"variant_id": "model-v1", "status": "success", "output_sha256": "9" * 64}


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _metric(tp: int, fp: int, fn: int, tn: int) -> dict[str, object]:
    predicted = tp + fp
    actual = tp + fn
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "predicted_positive": predicted, "actual_positive": actual,
        "precision": tp / predicted if predicted else None,
        "recall": tp / actual if actual else None,
    }


def _candidate(
    *, problem: tuple[int, int] = (17, 2), evidence: tuple[int, int] = (14, 2),
    covered: int = 14, invalid: int = 0,
) -> dict[str, object]:
    p_tp, p_fp = problem
    e_tp, e_fp = evidence
    metrics = {
        "problem_signal": _metric(p_tp, p_fp, 33 - p_tp, 7 - p_fp),
        "usable_evidence": _metric(e_tp, e_fp, 33 - e_tp, 7 - e_fp),
        "money_signal": _metric(3, 1, 6, 30),
    }
    source_metrics = {
        source: {"coverage": 0.25, "invalid_count": 0,
                 "usable_evidence": _metric(3, 0, 2, 5)}
        for source in ("github", "stackexchange", "steam", "ted")
    }
    return {
        "candidate_run_sha256": _digest(RUN_RECEIPT),
        "run_receipt": RUN_RECEIPT,
        "input_count": 40,
        "covered_count": covered,
        "invalid_count": invalid,
        "metrics": metrics,
        "source_metrics": source_metrics,
        "evaluation_receipt": {
            "status": "success",
            "upstream_run_receipt_sha256": _digest(RUN_RECEIPT),
            "input_count": 40,
            "covered_count": covered,
            "invalid_count": invalid,
            "report_sha256": _digest(
                {"metrics": metrics, "source_metrics": source_metrics}
            ),
        },
    }


def _audit(audited: int = 16, unsupported: int = 0) -> dict[str, object]:
    return {
        "schema_version": "calibration-audit-aggregate/v1",
        "status": "complete", "candidate_run_sha256": _digest(RUN_RECEIPT),
        "packet_sha256": "c" * 64, "assignment_sha256": "d" * 64,
        "submission_sha256": "e" * 64, "reviewer_id": "reviewer-2",
        "audited_count": audited,
        "supported_count": audited - unsupported,
        "unsupported_count": unsupported,
        "raw_rows_persisted": False,
    }


def _rebind_report(candidate: dict[str, object]) -> None:
    candidate["evaluation_receipt"]["report_sha256"] = _digest({
        "metrics": candidate["metrics"],
        "source_metrics": candidate["source_metrics"],
    })


def test_gate_accepts_exact_count_aware_boundary() -> None:
    config = load_gate_config(CONFIG, baseline_root=BASELINE)
    result = evaluate_gate(_candidate(), _audit(), config)
    assert result["status"] == "PASS"
    assert result["hard_failures"] == []


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (_candidate(problem=(9, 0)), "problem_predicted_positive"),
        (_candidate(evidence=(11, 2)), "evidence_predicted_positive"),
        (_candidate(problem=(16, 2), evidence=(14, 2)), "macro_tp_sum"),
        (_candidate(problem=(18, 2), evidence=(13, 1)), "evidence_tp"),
        (_candidate(covered=13), "covered_count"),
        (_candidate(invalid=1), "invalid_count"),
    ],
)
def test_gate_rejects_each_hard_boundary(
    candidate: dict[str, object], reason: str
) -> None:
    result = evaluate_gate(candidate, _audit(), load_gate_config(CONFIG, baseline_root=BASELINE))
    assert result["status"] == "FAIL"
    assert reason in result["hard_failures"]


@pytest.mark.parametrize(
    ("audit", "status"),
    [
        (_audit(14, 0), "PASS"),
        (_audit(14, 1), "FAIL"),
        (_audit(20, 1), "PASS"),
        (_audit(13, 0), "BLOCKED"),
        ({**_audit(20, 0), "status": "incomplete"}, "BLOCKED"),
    ],
)
def test_gate_uses_integer_unsupported_evidence_boundary(
    audit: dict[str, object], status: str
) -> None:
    audited = int(audit["audited_count"])
    if audited == 20:
        candidate = _candidate(evidence=(17, 3))
    elif audited == 14:
        candidate = _candidate(evidence=(audited, 0))
    else:
        candidate = _candidate()
    assert evaluate_gate(
        candidate, audit, load_gate_config(CONFIG, baseline_root=BASELINE)
    )["status"] == status


def test_gate_blocks_incomplete_audit_population_and_rejects_tampered_counts() -> None:
    config = load_gate_config(CONFIG, baseline_root=BASELINE)
    result = evaluate_gate(_candidate(), _audit(15, 0), config)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "audit_population_mismatch"

    candidate = _candidate()
    candidate["metrics"]["problem_signal"]["actual_positive"] = 999
    with pytest.raises(ValueError, match="report hash"):
        evaluate_gate(candidate, _audit(), config)


def test_gate_blocks_audit_from_a_different_candidate_run() -> None:
    audit = {**_audit(), "candidate_run_sha256": "f" * 64}
    result = evaluate_gate(
        _candidate(), audit, load_gate_config(CONFIG, baseline_root=BASELINE)
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "audit_candidate_mismatch"


def test_gate_rejects_metrics_tampered_after_evaluation() -> None:
    candidate = _candidate()
    candidate["metrics"]["problem_signal"] = _metric(18, 1, 15, 6)
    with pytest.raises(ValueError, match="report hash"):
        evaluate_gate(
            candidate, _audit(), load_gate_config(CONFIG, baseline_root=BASELINE)
        )


def test_money_and_source_regressions_require_review_without_hard_failure() -> None:
    candidate = _candidate()
    candidate["metrics"]["money_signal"] = _metric(0, 0, 9, 31)
    candidate["source_metrics"]["steam"]["coverage"] = 0.0
    _rebind_report(candidate)
    result = evaluate_gate(candidate, _audit(), load_gate_config(CONFIG, baseline_root=BASELINE))
    assert result["status"] == "REVIEW_REQUIRED"
    assert "money_regression" in result["warnings"]
    assert "steam_coverage" in result["warnings"]


@pytest.mark.parametrize("mutation", ["empty", "missing_source", "missing_evidence"])
def test_gate_rejects_incomplete_source_diagnostics(mutation: str) -> None:
    candidate = _candidate()
    if mutation == "empty":
        candidate["source_metrics"] = {}
    elif mutation == "missing_source":
        candidate["source_metrics"].pop("ted")
    else:
        candidate["source_metrics"]["steam"].pop("usable_evidence")
    _rebind_report(candidate)
    with pytest.raises(ValueError, match="source"):
        evaluate_gate(
            candidate, _audit(), load_gate_config(CONFIG, baseline_root=BASELINE)
        )


def test_config_and_freeze_receipt_are_bound_to_real_baseline() -> None:
    config = load_gate_config(CONFIG, baseline_root=BASELINE)
    receipt = build_freeze_receipt(
        config_path=CONFIG,
        baseline_root=BASELINE,
        code_commit_sha="a" * 40,
    )
    assert receipt["status"] == "frozen"
    assert receipt["model_calls"] == 0
    assert receipt["baseline_bundle_sha256"] == config["baseline"]["bundle_sha256"]


def test_freeze_receipt_loads_the_hashed_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "gate.json"
    config_path.write_text(CONFIG.read_text(), encoding="utf-8")

    receipt = build_freeze_receipt(
        config_path=config_path,
        baseline_root=BASELINE,
        code_commit_sha="a" * 40,
    )
    assert receipt["thresholds"]["covered_min_count"] == 14


def test_freeze_uses_one_config_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.extraction import calibration_gate

    config_path = tmp_path / "gate.json"
    original = CONFIG.read_bytes()
    config_path.write_bytes(original)
    real_loader = calibration_gate.load_gate_config

    def mutate_after_load(path: Path, *, baseline_root: Path) -> dict[str, object]:
        loaded = real_loader(path, baseline_root=baseline_root)
        config_path.write_bytes(original + b"\n")
        return loaded

    monkeypatch.setattr(calibration_gate, "load_gate_config", mutate_after_load)
    receipt = build_freeze_receipt(
        config_path=config_path, baseline_root=BASELINE, code_commit_sha="a" * 40
    )
    assert receipt["config_sha256"] == sha256(original).hexdigest()

    bad = json.loads(CONFIG.read_text())
    bad["baseline"]["bundle_sha256"] = "0" * 64
    path = CONFIG.parent / ".bad-gate-test.json"
    try:
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="baseline bundle"):
            load_gate_config(path, baseline_root=BASELINE)
    finally:
        path.unlink(missing_ok=True)


def test_evaluate_cli_writes_once_and_freeze_rejects_wrong_checkpoint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = tmp_path / "candidate.json"
    audit = tmp_path / "audit.json"
    output = tmp_path / "decision.json"
    candidate.write_text(json.dumps(_candidate()), encoding="utf-8")
    audit.write_text(json.dumps(_audit()), encoding="utf-8")
    assert main([
        "evaluate", "--config", str(CONFIG), "--baseline", str(BASELINE),
        "--candidate", str(candidate), "--audit", str(audit), "--output", str(output),
    ]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"
    assert main([
        "evaluate", "--config", str(CONFIG), "--baseline", str(BASELINE),
        "--candidate", str(candidate), "--audit", str(audit), "--output", str(output),
    ]) == 1

    freeze = tmp_path / "freeze.json"
    assert main([
        "freeze", "--config", str(CONFIG), "--baseline", str(BASELINE),
        "--code-commit", "0" * 40, "--output", str(freeze),
    ]) == 1
    assert not freeze.exists()
    assert "does not match HEAD" in capsys.readouterr().err


def test_immutable_writer_preserves_concurrently_created_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "freeze.json"
    destination.write_bytes(b"existing\n")
    original_exists = Path.exists

    def hide_destination(path: Path) -> bool:
        if path == destination:
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", hide_destination)
    with pytest.raises(FileExistsError):
        _write_immutable(destination, {"status": "frozen"})
    assert destination.read_bytes() == b"existing\n"


def test_immutable_writer_cleans_temporary_file_when_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "freeze.json"

    def fail_publish(source: Path, target: Path) -> None:
        raise OSError("injected publish failure")

    monkeypatch.setattr(os, "link", fail_publish)
    with pytest.raises(OSError, match="injected"):
        _write_immutable(destination, {"status": "frozen"})
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
