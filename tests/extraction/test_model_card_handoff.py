from __future__ import annotations

import fcntl
import json
import socket
from hashlib import sha256
from pathlib import Path

import pytest

import src.extraction.model_card_handoff as handoff
from src.extraction.model_card_handoff import (
    HandoffBlocked,
    execute_same_process_card_handoff,
)
from src.extraction.model_runner import ModelCalibrationFailure, ModelCalibrationRun
from src.extraction.opportunity_slice import build_vertical_slice


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _card(index: int) -> dict[str, object]:
    evidence = {
        "evidence_id": f"ev-{index}",
        "document_id": f"github:{index}",
        "source_url": f"https://example.test/issues/{index}",
        "published_at": "2026-09-01T00:00:00Z",
        "author_hash": f"author-{index}",
        "community": "github",
        "evidence_group_id": f"group-{index}",
        "kind": "problem",
        "quote": f"Observed problem {index}.",
        "interpretation": "A model-backed problem observation.",
        "confidence": 0.8,
    }
    card = build_vertical_slice([
        {
            "problem_key": f"problem-{index}",
            "observed_actor": "repository maintainer",
            "problem_statement": f"Observed problem {index}.",
            "productizable_scope": "Requires later actionability evidence.",
            "delivery_mode": "UNKNOWN",
            "evidence": evidence,
        }
    ])[0]
    card.update({
        "source_versions": {"github": "api-v1"},
        "model_version": "gpt-5.6",
        "prompt_version": "d" * 64,
        "policy_version": "model-backed-card-generation-v1",
        "generated_at": "2026-09-13T00:00:00Z",
        "uncertainties": ["Source eligibility is not complete."],
    })
    return card


def _run(**receipt_updates: object) -> ModelCalibrationRun:
    outputs = (
        {"document_id": "github:0", "problem": "SECRET RAW MODEL OUTPUT"},
        {"document_id": "github:1", "problem": "another sanitized output"},
        {"document_id": "github:2", "problem": "third sanitized output"},
    )
    receipt = {
        "schema_version": "model-calibration-run-receipt/v1",
        "status": "success",
        "requested_model": "gpt-5.6",
        "resolved_models": ["gpt-5.6"],
        "profile_sha256": "a" * 64,
        "prompt_sha256": "d" * 64,
        "output_schema_sha256": "c" * 64,
        "sources": ["github"],
        "output_count": 3,
        "valid_count": 3,
        "invalid_count": 0,
        "output_sha256": _digest(outputs),
        "outputs_persisted": False,
        "raw_responses_persisted": False,
    }
    receipt.update(receipt_updates)
    return ModelCalibrationRun(outputs, receipt)


def _preflight() -> dict[str, object]:
    snapshot = {"exists": False, "sha256": None, "mode": None, "size": None, "mtime_ns": None}
    return {
        "schema_version": "model-provider-preflight-receipt/v1",
        "status": "PASS",
        "termination_reason": "contract_valid",
        "profile_sha256": "a" * 64,
        "prompt_sha256": "d" * 64,
        "output_schema_sha256": "c" * 64,
        "requested_model": "gpt-5.6",
        "synthetic_document_sha256": "d" * 64,
        "preflight_policy_sha256": "e" * 64,
        "claim_sha256": "f" * 64,
        "resolved_model": "gpt-5.6",
        "request_count": 1,
        "retry_count": 0,
        "unknown_usage_request_count": 0,
        "input_tokens": 10,
        "output_tokens": 10,
        "observed_cost_usd": 0.01,
        "conservative_cost_upper_bound_usd": 0.01,
        "metric_claim_before": snapshot,
        "metric_claim_after": snapshot,
        "metric_claim_unchanged": True,
        "structured_output_valid": True,
        "semantic_sanity_valid": True,
        "calibration_scope": "development_only",
        "source_eligibility_required": False,
        "product_promotion_allowed": False,
        "raw_response_persisted": False,
        "structured_output_persisted": False,
        "request_id_persisted": False,
        "secret_persisted": False,
    }


def test_same_process_handoff_persists_only_cards_markdown_and_bound_receipt(
    tmp_path: Path,
) -> None:
    observed_outputs: object = None

    def build_cards(outputs: object, _receipt: object) -> list[dict[str, object]]:
        nonlocal observed_outputs
        observed_outputs = outputs
        return [_card(index) for index in range(3)]

    run = _run()
    result = execute_same_process_card_handoff(
        preflight_receipt=_preflight(),
        run_calibration=lambda: run,
        build_cards=build_cards,
        artifact_root=tmp_path / "candidate",
    )

    assert observed_outputs is run.outputs
    assert result["status"] == "CANDIDATE_ONLY"
    assert result["promotion_allowed"] is False
    assert result["model_output_sha256"] == run.receipt["output_sha256"]
    assert result["model_run_receipt_sha256"] == _digest(run.receipt)
    assert result["artifacts"] == ["cards.json", "cards.md"]
    assert sorted(path.name for path in (tmp_path / "candidate").iterdir()) == [
        "cards.json", "cards.md", "receipt.json"
    ]
    persisted = "".join(
        path.read_text() for path in (tmp_path / "candidate").iterdir()
    )
    assert "SECRET RAW MODEL OUTPUT" not in persisted
    assert "https://example.test/issues/0" in persisted
    assert "gpt-5.6 / model-backed-card-generation-v1" in persisted
    assert "Decision: HOLD" in persisted


def test_handoff_stops_before_calibration_when_preflight_is_not_pass(tmp_path: Path) -> None:
    called = False
    preflight = _preflight()
    preflight["status"] = "CONTRACT_FAIL"

    def run_calibration() -> ModelCalibrationRun:
        nonlocal called
        called = True
        return _run()

    with pytest.raises(HandoffBlocked, match="preflight_not_pass"):
        execute_same_process_card_handoff(
            preflight_receipt=preflight,
            run_calibration=run_calibration,
            build_cards=lambda *_args: [],
            artifact_root=tmp_path / "candidate",
        )
    assert called is False
    assert not (tmp_path / "candidate").exists()


def test_handoff_rejects_model_output_hash_mismatch_before_card_builder(
    tmp_path: Path,
) -> None:
    run = _run()
    run.receipt["output_sha256"] = "0" * 64

    with pytest.raises(HandoffBlocked, match="model_output_hash_mismatch"):
        execute_same_process_card_handoff(
            preflight_receipt=_preflight(),
            run_calibration=lambda: run,
            build_cards=lambda *_args: pytest.fail("builder must not run"),
            artifact_root=tmp_path / "candidate",
        )


def test_handoff_refuses_to_overwrite_existing_artifacts(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep")

    with pytest.raises(HandoffBlocked, match="artifact_destination_exists"):
        execute_same_process_card_handoff(
            preflight_receipt=_preflight(),
            run_calibration=_run,
            build_cards=lambda *_args: [_card(index) for index in range(3)],
            artifact_root=destination,
        )
    assert marker.read_text() == "keep"


def test_handoff_rejects_self_attested_pass_before_calibration(tmp_path: Path) -> None:
    called = False

    def run_calibration() -> ModelCalibrationRun:
        nonlocal called
        called = True
        return _run()

    with pytest.raises(HandoffBlocked, match="preflight_contract_invalid"):
        execute_same_process_card_handoff(
            preflight_receipt={"status": "PASS"},
            run_calibration=run_calibration,
            build_cards=lambda *_args: [],
            artifact_root=tmp_path / "candidate",
        )
    assert called is False


def test_handoff_reserves_destination_before_consuming_calibration(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"

    def run_calibration() -> ModelCalibrationRun:
        assert destination.is_dir()
        marker = json.loads((destination / "state-receipt.json").read_text())
        assert marker["status"] == "IN_PROGRESS"
        assert marker["preflight_receipt_sha256"] == _digest(_preflight())
        assert marker["owner_token"]
        return _run()

    execute_same_process_card_handoff(
        preflight_receipt=_preflight(),
        run_calibration=run_calibration,
        build_cards=lambda *_args: [_card(index) for index in range(3)],
        artifact_root=destination,
    )


def test_handoff_persists_terminal_receipt_after_consumed_run_failure(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"

    def fail_builder(*_args: object) -> list[dict[str, object]]:
        raise RuntimeError("SECRET RAW MODEL OUTPUT")

    with pytest.raises(HandoffBlocked, match="card_build_failed"):
        execute_same_process_card_handoff(
            preflight_receipt=_preflight(),
            run_calibration=_run,
            build_cards=fail_builder,
            artifact_root=destination,
        )
    failure = json.loads((destination / "failure-receipt.json").read_text())
    assert failure["status"] == "BLOCKED"
    assert failure["reason"] == "card_build_failed"
    assert failure["model_run_receipt_sha256"] == _digest(_run().receipt)
    assert "SECRET RAW MODEL OUTPUT" not in (destination / "failure-receipt.json").read_text()


def test_success_receipt_hashes_exact_persisted_artifact_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    receipt = execute_same_process_card_handoff(
        preflight_receipt=_preflight(),
        run_calibration=_run,
        build_cards=lambda *_args: [_card(index) for index in range(3)],
        artifact_root=destination,
    )
    assert receipt["cards_sha256"] == sha256((destination / "cards.json").read_bytes()).hexdigest()
    assert receipt["markdown_sha256"] == sha256((destination / "cards.md").read_bytes()).hexdigest()


def test_unexpected_calibration_error_is_sanitized_and_terminal(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"

    def fail_calibration() -> ModelCalibrationRun:
        raise RuntimeError("SECRET PROVIDER RESPONSE")

    with pytest.raises(HandoffBlocked, match="calibration_unexpected_failure"):
        execute_same_process_card_handoff(
            preflight_receipt=_preflight(),
            run_calibration=fail_calibration,
            build_cards=lambda *_args: [],
            artifact_root=destination,
        )
    persisted = (destination / "failure-receipt.json").read_text()
    assert "SECRET PROVIDER RESPONSE" not in persisted
    assert json.loads(persisted)["reason"] == "calibration_unexpected_failure"


def test_calibration_failure_receipt_is_hash_bound(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    model_failure_receipt = {"status": "failed", "termination_reason": "budget"}

    def fail_calibration() -> ModelCalibrationRun:
        raise ModelCalibrationFailure("failed", model_failure_receipt)

    with pytest.raises(HandoffBlocked, match="calibration_not_success"):
        execute_same_process_card_handoff(
            preflight_receipt=_preflight(),
            run_calibration=fail_calibration,
            build_cards=lambda *_args: [],
            artifact_root=destination,
        )
    receipt = json.loads((destination / "failure-receipt.json").read_text())
    assert receipt["model_run_receipt_sha256"] == _digest(model_failure_receipt)


def test_stale_in_progress_reservation_is_classified_as_orphaned(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    destination.mkdir()
    (destination / "state-receipt.json").write_text(json.dumps({
        "schema_version": "model-backed-card-generation-state-receipt/v1",
        "status": "IN_PROGRESS",
        "preflight_receipt_sha256": _digest(_preflight()),
        "owner_token": "a" * 32,
        "owner_host": socket.gethostname(),
        "created_at": "2026-09-13T00:00:00Z",
    }))
    (destination / ".handoff.lock").touch()

    with pytest.raises(HandoffBlocked, match="artifact_destination_orphaned"):
        execute_same_process_card_handoff(
            preflight_receipt=_preflight(),
            run_calibration=_run,
            build_cards=lambda *_args: [],
            artifact_root=destination,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("profile_sha256", "9" * 64),
        ("prompt_sha256", "9" * 64),
        ("output_schema_sha256", "9" * 64),
        ("resolved_models", ["different-model"]),
    ],
)
def test_handoff_rejects_preflight_calibration_lineage_mismatch(
    tmp_path: Path, field: str, value: object
) -> None:
    with pytest.raises(HandoffBlocked, match="model_run_not_eligible"):
        execute_same_process_card_handoff(
            preflight_receipt=_preflight(),
            run_calibration=lambda: _run(**{field: value}),
            build_cards=lambda *_args: pytest.fail("builder must not run"),
            artifact_root=tmp_path / field,
        )


def test_held_reservation_lock_is_classified_as_active(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    destination.mkdir()
    (destination / "state-receipt.json").write_text(json.dumps({
        "schema_version": "model-backed-card-generation-state-receipt/v1",
        "status": "IN_PROGRESS",
        "preflight_receipt_sha256": _digest(_preflight()),
        "owner_token": "b" * 32,
        "owner_host": socket.gethostname(),
        "created_at": "2026-09-13T00:00:00Z",
    }))
    lock_path = destination / ".handoff.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(HandoffBlocked, match="artifact_destination_active"):
            execute_same_process_card_handoff(
                preflight_receipt=_preflight(),
                run_calibration=_run,
                build_cards=lambda *_args: [],
                artifact_root=destination,
            )


def test_reservation_marker_failure_rolls_back_lock_and_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "candidate"
    called = False
    original_write = handoff._write_private

    def fail_marker(path: Path, payload: bytes) -> None:
        if path.name == "state-receipt.json":
            raise OSError("marker write failed")
        original_write(path, payload)

    def run_calibration() -> ModelCalibrationRun:
        nonlocal called
        called = True
        return _run()

    monkeypatch.setattr(handoff, "_write_private", fail_marker)
    with pytest.raises(HandoffBlocked, match="reservation_publication_failed"):
        execute_same_process_card_handoff(
            preflight_receipt=_preflight(),
            run_calibration=run_calibration,
            build_cards=lambda *_args: [],
            artifact_root=destination,
        )
    assert called is False
    assert not destination.exists()


def test_completed_destination_is_not_misclassified_as_orphaned(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    destination.mkdir()
    (destination / "state-receipt.json").write_text(json.dumps({
        "schema_version": "model-backed-card-generation-state-receipt/v1",
        "status": "IN_PROGRESS",
        "preflight_receipt_sha256": _digest(_preflight()),
        "owner_token": "c" * 32,
        "owner_host": socket.gethostname(),
        "created_at": "2026-09-13T00:00:00Z",
    }))
    (destination / "receipt.json").write_text("{}")

    with pytest.raises(HandoffBlocked, match="artifact_destination_exists"):
        execute_same_process_card_handoff(
            preflight_receipt=_preflight(),
            run_calibration=_run,
            build_cards=lambda *_args: [],
            artifact_root=destination,
        )
