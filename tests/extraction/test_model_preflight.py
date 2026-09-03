from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.extraction import model_preflight, model_runner
from src.extraction.inference_profile import load_inference_profile
from src.extraction.model_preflight import execute_provider_preflight
from src.extraction.model_runner import (
    ModelCallResult,
    ModelOutputError,
    OperationalModelError,
    ProviderContractError,
)
from src.extraction.openai_responses import build_response_request_body


ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_inference_profile(
    ROOT / "configs/extraction/inference-profile-gpt-5.6-v1.json"
)


@pytest.fixture(autouse=True)
def isolate_custody(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        model_preflight, "_CLAIM_PATH", tmp_path / "provider-preflight.claim.json"
    )
    monkeypatch.setattr(
        model_preflight, "_RECEIPT_PATH", tmp_path / "provider-preflight.receipt.json"
    )
    monkeypatch.setattr(
        model_preflight,
        "_PUBLICATION_FAILURE_PATH",
        tmp_path / "provider-preflight.publication-failure.json",
    )
    monkeypatch.setattr(
        model_runner, "_CALIBRATION_RUN_CLAIM_PATH", tmp_path / "metric-run.claim.json"
    )


def _valid_output(document: dict[str, object]) -> dict[str, object]:
    text = str(document["text"])
    return {
        "document_id": document["document_id"],
        "observation_type": "user_problem",
        "actor": "operator",
        "problem": text,
        "context": "synthetic contract preflight",
        "consequence": text,
        "evidence_quote": text,
        "evidence_start": 0,
        "evidence_end": len(text),
        "problem_signal": True,
        "money_signal": False,
        "money_signal_type": None,
        "usable_evidence": True,
        "confidence": 0.8,
        "abstention_reason": None,
    }


def test_request_builder_is_frozen_and_excludes_source_url() -> None:
    document = dict(model_preflight.SYNTHETIC_DOCUMENT)
    body = build_response_request_body(document, PROFILE)

    assert body["model"] == "gpt-5.6"
    assert body["store"] is False
    assert body["text"]["format"]["schema"] == PROFILE.output_schema
    assert "source_url" not in json.dumps(body)


def test_preflight_retries_operational_errors_and_preserves_metric_claim(
    tmp_path: Path,
) -> None:
    metric_claim = model_runner._CALIBRATION_RUN_CLAIM_PATH
    metric_claim.write_text("frozen metric claim", encoding="utf-8")
    attempts = 0

    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalModelError("timeout")
        return ModelCallResult(_valid_output(document), "gpt-5.6", 20, 10, "hidden")

    receipt = execute_provider_preflight(PROFILE, transport)

    assert receipt["status"] == "PASS"
    assert receipt["request_count"] == 3
    assert receipt["retry_count"] == 2
    assert receipt["metric_claim_unchanged"] is True
    assert metric_claim.read_text() == "frozen metric claim"
    assert receipt["conservative_cost_upper_bound_usd"] <= 0.10
    assert len(str(receipt["synthetic_document_sha256"])) == 64
    assert len(str(receipt["preflight_policy_sha256"])) == 64
    assert len(str(receipt["claim_sha256"])) == 64
    assert receipt["observed_cost_usd"] is None
    assert (tmp_path / "provider-preflight.claim.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "provider-preflight.receipt.json").stat().st_mode & 0o777 == 0o600
    serialized = json.dumps(receipt)
    assert "hidden" not in serialized
    assert str(model_preflight.SYNTHETIC_DOCUMENT["text"]) not in serialized


def test_preflight_does_not_retry_contract_failure() -> None:
    attempts = 0

    def transport(*_args: object) -> ModelCallResult:
        nonlocal attempts
        attempts += 1
        raise ProviderContractError("HTTP 401")

    receipt = execute_provider_preflight(PROFILE, transport)

    assert receipt["status"] == "CONTRACT_FAIL"
    assert receipt["request_count"] == 1
    assert attempts == 1


def test_preflight_accepts_schema_valid_abstention() -> None:
    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        output = {key: None for key in _valid_output(document)}
        output["document_id"] = document["document_id"]
        output["abstention_reason"] = "insufficient evidence"
        return ModelCallResult(output, "gpt-5.6", 10, 10, "hidden")

    assert execute_provider_preflight(PROFILE, transport)["status"] == "PASS"


def test_preflight_rejects_invalid_evidence_span() -> None:
    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        output = _valid_output(document)
        output["evidence_end"] = 1
        return ModelCallResult(output, "gpt-5.6", 10, 10, "hidden")

    assert execute_provider_preflight(PROFILE, transport)["status"] == "CONTRACT_FAIL"


def test_preflight_blocks_second_execution_before_transport() -> None:
    calls = 0

    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        nonlocal calls
        calls += 1
        return ModelCallResult(_valid_output(document), "gpt-5.6", 10, 10, "hidden")

    assert execute_provider_preflight(PROFILE, transport)["status"] == "PASS"
    assert execute_provider_preflight(PROFILE, transport)["status"] == "ALREADY_CONSUMED"
    assert calls == 1


def test_preflight_reports_orphaned_claim_without_calling_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_publish = model_preflight._publish

    def interrupt_publication(_receipt: dict[str, object]) -> dict[str, object]:
        raise SystemExit("simulated process interruption")

    monkeypatch.setattr(model_preflight, "_publish", interrupt_publication)
    with pytest.raises(SystemExit, match="process interruption"):
        execute_provider_preflight(
            PROFILE,
            lambda document, _profile: ModelCallResult(
                _valid_output(document), "gpt-5.6", 10, 10, "hidden"
            ),
        )

    monkeypatch.setattr(model_preflight, "_publish", real_publish)
    monkeypatch.setattr(model_preflight, "_process_is_alive", lambda _pid: False)
    calls = 0

    def transport(*_args: object) -> ModelCallResult:
        nonlocal calls
        calls += 1
        raise AssertionError("orphan recovery must not call the provider")

    receipt = execute_provider_preflight(PROFILE, transport)

    assert receipt["status"] == "ORPHANED_CLAIM"
    assert receipt["termination_reason"] == "preflight_claim_without_terminal_artifact"
    assert calls == 0


def test_preflight_reports_live_claim_as_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_publish = model_preflight._publish

    def interrupt_publication(_receipt: dict[str, object]) -> dict[str, object]:
        raise SystemExit("leave active claim")

    monkeypatch.setattr(model_preflight, "_publish", interrupt_publication)
    with pytest.raises(SystemExit, match="active claim"):
        execute_provider_preflight(
            PROFILE,
            lambda document, _profile: ModelCallResult(
                _valid_output(document), "gpt-5.6", 10, 10, "hidden"
            ),
        )
    monkeypatch.setattr(model_preflight, "_publish", real_publish)
    monkeypatch.setattr(model_preflight, "_process_is_alive", lambda _pid: True)

    result = execute_provider_preflight(
        PROFILE,
        lambda *_args: pytest.fail("active claim must not call the provider twice"),
    )

    assert result["status"] == "IN_PROGRESS"
    assert result["termination_reason"] == "preflight_execution_in_progress"


def test_preflight_rejects_receipt_not_bound_to_existing_claim() -> None:
    transport = lambda document, _profile: ModelCallResult(  # noqa: E731
        _valid_output(document), "gpt-5.6", 10, 10, "hidden"
    )
    assert execute_provider_preflight(PROFILE, transport)["status"] == "PASS"
    receipt_path = model_preflight._RECEIPT_PATH
    receipt = json.loads(receipt_path.read_text())
    receipt["claim_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    result = execute_provider_preflight(PROFILE, transport)

    assert result["status"] == "CONTRACT_FAIL"
    assert result["termination_reason"] == "terminal_artifact_claim_mismatch"


def test_preflight_replays_hash_bound_publication_failure_without_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_atomic_create = model_preflight._atomic_create

    def fail_receipt(path: Path, value: dict[str, object]) -> None:
        if path == model_preflight._RECEIPT_PATH:
            raise OSError("disk failure")
        real_atomic_create(path, value)

    monkeypatch.setattr(model_preflight, "_atomic_create", fail_receipt)
    first = execute_provider_preflight(
        PROFILE,
        lambda document, _profile: ModelCallResult(
            _valid_output(document), "gpt-5.6", 10, 10, "hidden"
        ),
    )
    assert first["status"] == "PUBLICATION_FAIL"
    monkeypatch.setattr(model_preflight, "_atomic_create", real_atomic_create)

    calls = 0

    def transport(*_args: object) -> ModelCallResult:
        nonlocal calls
        calls += 1
        raise AssertionError("terminal publication failure must not call the provider")

    replay = execute_provider_preflight(PROFILE, transport)

    assert replay["status"] == "PUBLICATION_FAIL"
    assert replay["termination_reason"] == "receipt_publication_failed"
    assert calls == 0


def test_preflight_rejects_conflicting_terminal_artifacts() -> None:
    transport = lambda document, _profile: ModelCallResult(  # noqa: E731
        _valid_output(document), "gpt-5.6", 10, 10, "hidden"
    )
    receipt = execute_provider_preflight(PROFILE, transport)
    model_preflight._PUBLICATION_FAILURE_PATH.write_text(
        json.dumps(
            {
                "schema_version": "model-provider-preflight-publication-failure/v1",
                "status": "PUBLICATION_FAIL",
                "failure_stage": "publication",
                "termination_reason": "receipt_publication_failed",
                "claim_sha256": receipt["claim_sha256"],
                "receipt_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    result = execute_provider_preflight(PROFILE, transport)

    assert result["status"] == "CONTRACT_FAIL"
    assert result["termination_reason"] == "conflicting_terminal_artifacts"


def test_preflight_rejects_publication_marker_not_bound_to_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_atomic_create = model_preflight._atomic_create

    def fail_receipt(path: Path, value: dict[str, object]) -> None:
        if path == model_preflight._RECEIPT_PATH:
            raise OSError("disk failure")
        real_atomic_create(path, value)

    monkeypatch.setattr(model_preflight, "_atomic_create", fail_receipt)
    execute_provider_preflight(
        PROFILE,
        lambda document, _profile: ModelCallResult(
            _valid_output(document), "gpt-5.6", 10, 10, "hidden"
        ),
    )
    marker = json.loads(model_preflight._PUBLICATION_FAILURE_PATH.read_text())
    marker["claim_sha256"] = "0" * 64
    model_preflight._PUBLICATION_FAILURE_PATH.write_text(
        json.dumps(marker), encoding="utf-8"
    )
    monkeypatch.setattr(model_preflight, "_atomic_create", real_atomic_create)

    result = execute_provider_preflight(
        PROFILE,
        lambda *_args: pytest.fail("invalid marker must not call the provider"),
    )

    assert result["status"] == "CONTRACT_FAIL"
    assert result["termination_reason"] == "terminal_artifact_claim_mismatch"


def test_preflight_rejects_malformed_publication_marker_receipt_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_atomic_create = model_preflight._atomic_create

    def fail_receipt(path: Path, value: dict[str, object]) -> None:
        if path == model_preflight._RECEIPT_PATH:
            raise OSError("disk failure")
        real_atomic_create(path, value)

    monkeypatch.setattr(model_preflight, "_atomic_create", fail_receipt)
    execute_provider_preflight(
        PROFILE,
        lambda document, _profile: ModelCallResult(
            _valid_output(document), "gpt-5.6", 10, 10, "hidden"
        ),
    )
    marker = json.loads(model_preflight._PUBLICATION_FAILURE_PATH.read_text())
    marker["receipt_sha256"] = "not-a-sha256"
    model_preflight._PUBLICATION_FAILURE_PATH.write_text(
        json.dumps(marker), encoding="utf-8"
    )
    monkeypatch.setattr(model_preflight, "_atomic_create", real_atomic_create)

    result = execute_provider_preflight(
        PROFILE,
        lambda *_args: pytest.fail("invalid marker must not call the provider"),
    )

    assert result["status"] == "CONTRACT_FAIL"
    assert result["termination_reason"] == "terminal_artifact_claim_mismatch"


def test_preflight_rejects_mismatched_publication_failure_stage_and_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_atomic_create = model_preflight._atomic_create

    def fail_receipt(path: Path, value: dict[str, object]) -> None:
        if path == model_preflight._RECEIPT_PATH:
            raise OSError("disk failure")
        real_atomic_create(path, value)

    monkeypatch.setattr(model_preflight, "_atomic_create", fail_receipt)
    execute_provider_preflight(
        PROFILE,
        lambda document, _profile: ModelCallResult(
            _valid_output(document), "gpt-5.6", 10, 10, "hidden"
        ),
    )
    marker = json.loads(model_preflight._PUBLICATION_FAILURE_PATH.read_text())
    marker["failure_stage"] = "validation"
    model_preflight._PUBLICATION_FAILURE_PATH.write_text(
        json.dumps(marker), encoding="utf-8"
    )
    monkeypatch.setattr(model_preflight, "_atomic_create", real_atomic_create)

    result = execute_provider_preflight(
        PROFILE,
        lambda *_args: pytest.fail("invalid marker must not call the provider"),
    )

    assert result["status"] == "CONTRACT_FAIL"
    assert result["termination_reason"] == "terminal_artifact_claim_mismatch"


def test_preflight_cost_ceiling_stops_before_transport() -> None:
    calls = 0

    def transport(*_args: object) -> ModelCallResult:
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be called")

    expensive = replace(PROFILE, output_usd_per_million=1_000_000)
    receipt = execute_provider_preflight(expensive, transport)

    assert receipt["status"] == "PREREQUISITE_FAIL"
    assert receipt["termination_reason"] == "cost_upper_bound_exceeded"
    assert calls == 0


def test_preflight_reports_operational_exhaustion_after_three_attempts() -> None:
    calls = 0

    def transport(*_args: object) -> ModelCallResult:
        nonlocal calls
        calls += 1
        raise OperationalModelError("timeout")

    receipt = execute_provider_preflight(PROFILE, transport)

    assert receipt["status"] == "OPERATIONAL_EXHAUSTED"
    assert receipt["request_count"] == 3
    assert receipt["retry_count"] == 2
    assert receipt["unknown_usage_request_count"] == 3
    assert receipt["observed_cost_usd"] is None
    assert calls == 3


def test_preflight_publishes_internal_failure_after_unexpected_transport_error(
    tmp_path: Path,
) -> None:
    calls = 0

    def transport(*_args: object) -> ModelCallResult:
        nonlocal calls
        calls += 1
        raise RuntimeError("unexpected provider integration failure")

    receipt = execute_provider_preflight(PROFILE, transport)

    assert receipt["status"] == "INTERNAL_FAIL"
    assert receipt["termination_reason"] == "unexpected_internal_error"
    assert receipt["request_count"] == 1
    assert receipt["unknown_usage_request_count"] == 1
    assert calls == 1
    assert (tmp_path / "provider-preflight.receipt.json").exists()


def test_preflight_rejects_invalid_usage_attached_to_model_output_error() -> None:
    def transport(*_args: object) -> ModelCallResult:
        raise ModelOutputError(
            "invalid structured output",
            resolved_model="gpt-5.6",
            input_tokens=-1,
            output_tokens=10,
        )

    receipt = execute_provider_preflight(PROFILE, transport)

    assert receipt["status"] == "CONTRACT_FAIL"
    assert receipt["termination_reason"] == "response_validation_failed"
    assert receipt["unknown_usage_request_count"] == 1
    assert receipt["input_tokens"] == 0
    assert receipt["output_tokens"] == 0


def test_preflight_detects_metric_claim_drift() -> None:
    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        model_runner._CALIBRATION_RUN_CLAIM_PATH.write_text("unexpected drift")
        return ModelCallResult(_valid_output(document), "gpt-5.6", 10, 10, "hidden")

    receipt = execute_provider_preflight(PROFILE, transport)

    assert receipt["status"] == "METRIC_CLAIM_DRIFT"
    assert receipt["metric_claim_unchanged"] is False


def test_preflight_writes_publication_failure_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_atomic_create = model_preflight._atomic_create

    def fail_receipt(path: Path, value: dict[str, object]) -> None:
        if path == model_preflight._RECEIPT_PATH:
            raise OSError("disk failure")
        real_atomic_create(path, value)

    monkeypatch.setattr(model_preflight, "_atomic_create", fail_receipt)

    receipt = execute_provider_preflight(
        PROFILE,
        lambda document, _profile: ModelCallResult(
            _valid_output(document), "gpt-5.6", 10, 10, "hidden"
        ),
    )

    assert receipt["status"] == "PUBLICATION_FAIL"
    marker = json.loads(model_preflight._PUBLICATION_FAILURE_PATH.read_text())
    assert marker["status"] == "PUBLICATION_FAIL"
    assert marker["claim_sha256"] == receipt["claim_sha256"]
    assert marker["termination_reason"] == "receipt_publication_failed"
    assert model_preflight._PUBLICATION_FAILURE_PATH.stat().st_mode & 0o777 == 0o600


def test_publish_distinguishes_receipt_validation_failure() -> None:
    receipt = model_preflight._publish({"status": "PASS"})

    assert receipt["status"] == "PUBLICATION_FAIL"
    assert receipt["termination_reason"] == "receipt_validation_failed"
    marker = json.loads(model_preflight._PUBLICATION_FAILURE_PATH.read_text())
    assert marker["failure_stage"] == "validation"


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [
        ("PASS", 0),
        ("CONTRACT_FAIL", 2),
        ("PREREQUISITE_FAIL", 3),
        ("OPERATIONAL_EXHAUSTED", 4),
        ("PUBLICATION_FAIL", 5),
        ("ALREADY_CONSUMED", 6),
        ("METRIC_CLAIM_DRIFT", 7),
        ("INTERNAL_FAIL", 8),
        ("ORPHANED_CLAIM", 9),
        ("IN_PROGRESS", 10),
    ],
)
def test_preflight_cli_exit_codes(
    status: str, exit_code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_preflight, "load_inference_profile", lambda _path: PROFILE)
    monkeypatch.setattr(
        model_preflight.OpenAIResponsesTransport,
        "from_environment",
        lambda _profile: object(),
    )
    monkeypatch.setattr(
        model_preflight,
        "execute_provider_preflight",
        lambda _profile, _transport: {
            "status": status,
            "termination_reason": "test_reason",
        },
    )

    assert model_preflight.main() == exit_code


def test_preflight_cli_exposes_publication_failure_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(model_preflight, "load_inference_profile", lambda _path: PROFILE)
    monkeypatch.setattr(
        model_preflight.OpenAIResponsesTransport,
        "from_environment",
        lambda _profile: object(),
    )
    monkeypatch.setattr(
        model_preflight,
        "execute_provider_preflight",
        lambda _profile, _transport: {
            "status": "PUBLICATION_FAIL",
            "termination_reason": "receipt_validation_failed",
        },
    )

    assert model_preflight.main() == 5
    assert json.loads(capsys.readouterr().out) == {
        "status": "PUBLICATION_FAIL",
        "termination_reason": "receipt_validation_failed",
    }
