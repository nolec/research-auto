from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from src.extraction import model_runner
from src.extraction.development_slice import DevelopmentInference
from src.extraction.inference_profile import load_inference_profile
from src.extraction.model_runner import (
    CalibrationRunLedger,
    ModelCalibrationFailure,
    ModelCallResult,
    ModelOutputError,
    OperationalModelError,
    ProviderContractError,
    run_model_calibration,
)


ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_inference_profile(
    ROOT / "configs/extraction/inference-profile-gpt-5.6-v1.json"
)


@pytest.fixture(autouse=True)
def isolate_calibration_run_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_runner,
        "_CALIBRATION_RUN_CLAIM_PATH",
        tmp_path / "custody" / "metric-run.claim.json",
    )


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _inference(count: int = 40) -> DevelopmentInference:
    sources = ("github", "stackexchange", "steam", "ted")
    corpus = tuple(
        {
            "document_id": f"{sources[index % 4]}:{index}",
            "source": sources[index % 4],
            "title": f"Title {index}",
            "text": f"The operation fails for document {index}.",
            "published_at": "2026-01-01T00:00:00Z",
            "source_url": f"https://example.com/{index}",
        }
        for index in range(count)
    )
    return DevelopmentInference(
        corpus,
        {
            "inference_corpus_sha256": _digest(corpus),
            "selected_count": count,
            "source_spike_reserved_emitted": 0,
        },
    )


def _output(document: dict[str, object]) -> dict[str, object]:
    text = str(document["text"])
    return {
        "document_id": document["document_id"],
        "observation_type": "user_problem",
        "actor": "source author",
        "problem": text,
        "context": str(document["title"]),
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


def test_runner_emits_only_sanitized_outputs_and_aggregate_receipt(tmp_path: Path) -> None:
    inference = _inference()

    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        return ModelCallResult(
            output=_output(document),
            resolved_model="gpt-5.6-2026-08-01",
            input_tokens=100,
            output_tokens=50,
            request_id="secret-provider-request-id",
        )

    run = run_model_calibration(
        inference,
        PROFILE,
        transport,
        monotonic=lambda: 0.0,
    )

    assert len(run.outputs) == 40
    assert run.receipt["status"] == "success"
    assert run.receipt["request_count"] == 40
    assert run.receipt["retry_count"] == 0
    assert run.receipt["input_tokens"] == 4000
    assert run.receipt["output_tokens"] == 2000
    assert run.receipt["outputs_persisted"] is False
    assert run.receipt["raw_responses_persisted"] is False
    assert run.receipt["source_role"] == "calibration_source"
    serialized = json.dumps(run.receipt)
    assert "secret-provider-request-id" not in serialized
    assert "The operation fails" not in serialized


def test_runner_retries_only_operational_failures(tmp_path: Path) -> None:
    inference = _inference()
    attempts: dict[str, int] = {}

    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        document_id = str(document["document_id"])
        attempts[document_id] = attempts.get(document_id, 0) + 1
        if attempts[document_id] == 1:
            raise OperationalModelError("timeout")
        return ModelCallResult(_output(document), "gpt-5.6", 10, 10, "hidden")

    run = run_model_calibration(
        inference,
        PROFILE,
        transport,
        monotonic=lambda: 0.0,
    )

    assert run.receipt["request_count"] == 80
    assert run.receipt["retry_count"] == 40
    assert run.receipt["operational_error_count"] == 40
    assert run.receipt["unknown_usage_request_count"] == 40
    assert run.receipt["usage_observation_complete"] is False
    assert run.receipt["estimated_cost_usd"] is None


def test_runner_fail_closes_on_membership_cost_and_wall_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="40 records"):
        run_model_calibration(
            _inference(39),
            PROFILE,
            lambda *_: None,
        )

    inference = _inference()

    def expensive(document: dict[str, object], _profile: object) -> ModelCallResult:
        return ModelCallResult(_output(document), "gpt-5.6", 10_000_000, 0, "hidden")

    with pytest.raises(ModelCalibrationFailure, match="cost ceiling") as cost_error:
        run_model_calibration(
            inference,
            PROFILE,
            expensive,
            monotonic=lambda: 0.0,
        )
    assert cost_error.value.receipt["status"] == "failed"
    assert cost_error.value.receipt["termination_reason"] == "cost_ceiling_exceeded"
    assert cost_error.value.receipt["request_count"] == 1
    assert cost_error.value.receipt["input_tokens"] == 10_000_000

    # Exercise an independent frozen-run scenario without weakening production custody.
    model_runner._CALIBRATION_RUN_CLAIM_PATH.unlink()
    times = iter((0.0, 1801.0))
    with pytest.raises(ModelCalibrationFailure, match="wall-time ceiling") as wall_error:
        run_model_calibration(
            inference,
            PROFILE,
            lambda document, _profile: ModelCallResult(
                _output(document), "gpt-5.6", 1, 1, "hidden"
            ),
            monotonic=lambda: next(times),
        )
    assert wall_error.value.receipt["termination_reason"] == "wall_time_exceeded"


def test_runner_preserves_retry_failure_receipt(tmp_path: Path) -> None:
    inference = _inference()

    def unavailable(*_args: object) -> ModelCallResult:
        raise OperationalModelError("timeout")

    with pytest.raises(ModelCalibrationFailure, match="retry budget") as error:
        run_model_calibration(
            inference,
            PROFILE,
            unavailable,
            monotonic=lambda: 0.0,
        )

    assert error.value.receipt["status"] == "failed"
    assert error.value.receipt["termination_reason"] == "retry_budget_exhausted"
    assert error.value.receipt["request_count"] == 3
    assert error.value.receipt["retry_count"] == 2
    assert error.value.receipt["operational_error_count"] == 3
    assert error.value.receipt["unknown_usage_request_count"] == 3
    assert error.value.receipt["estimated_cost_usd"] is None


def test_runner_marks_malformed_structured_output_invalid_without_retry(
    tmp_path: Path,
) -> None:
    inference = _inference()

    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        return ModelCallResult(
            output={
                "document_id": document["document_id"],
                "unexpected": "malicious source text must be discarded",
            },
            resolved_model="gpt-5.6",
            input_tokens=10,
            output_tokens=10,
            request_id="hidden",
        )

    run = run_model_calibration(
        inference,
        PROFILE,
        transport,
        monotonic=lambda: 0.0,
    )

    assert run.receipt["invalid_count"] == 40
    assert run.receipt["request_count"] == 40
    assert run.receipt["retry_count"] == 0
    assert run.outputs[0] == {
        "document_id": inference.corpus[0]["document_id"],
        "invalid_output": True,
    }
    assert "malicious source text" not in json.dumps(run.outputs)


def test_runner_converts_sanitized_model_output_errors_to_invalid_without_retry(
    tmp_path: Path,
) -> None:
    inference = _inference()

    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        raise ModelOutputError(
            "provider refusal",
            resolved_model="gpt-5.6",
            input_tokens=10,
            output_tokens=2,
        )

    run = run_model_calibration(
        inference,
        PROFILE,
        transport,
        monotonic=lambda: 0.0,
    )

    assert run.receipt["invalid_count"] == 40
    assert run.receipt["model_output_error_count"] == 40
    assert run.receipt["request_count"] == 40
    assert run.receipt["retry_count"] == 0
    assert all(
        output
        == {"document_id": document["document_id"], "invalid_output": True}
        for document, output in zip(inference.corpus, run.outputs, strict=True)
    )


def test_runner_checks_wall_time_after_a_model_call(tmp_path: Path) -> None:
    inference = _inference()
    times = iter((0.0, 0.0, 1801.0))

    with pytest.raises(ModelCalibrationFailure, match="wall-time ceiling"):
        run_model_calibration(
            inference,
            PROFILE,
            lambda document, _profile: ModelCallResult(
                _output(document), "gpt-5.6", 1, 1, "hidden"
            ),
            monotonic=lambda: next(times),
        )


def test_runner_rejects_unapproved_resolved_model_with_failure_receipt(
    tmp_path: Path,
) -> None:
    inference = _inference()

    def wrong_model(document: dict[str, object], _profile: object) -> ModelCallResult:
        return ModelCallResult(_output(document), "gpt-4o", 10, 10, "hidden")

    with pytest.raises(ModelCalibrationFailure, match="resolved model") as error:
        run_model_calibration(
            inference,
            PROFILE,
            wrong_model,
            monotonic=lambda: 0.0,
        )

    assert error.value.receipt["termination_reason"] == "resolved_model_mismatch"
    assert error.value.receipt["request_count"] == 1
    assert error.value.receipt["input_tokens"] == 10


def test_runner_converts_provider_contract_error_to_failure_receipt(tmp_path: Path) -> None:
    inference = _inference()

    def invalid_provider_response(*_args: object) -> ModelCallResult:
        raise ProviderContractError("provider response usage is missing")

    with pytest.raises(ModelCalibrationFailure, match="provider contract") as error:
        run_model_calibration(
            inference,
            PROFILE,
            invalid_provider_response,
            monotonic=lambda: 0.0,
        )

    assert error.value.receipt["termination_reason"] == "provider_contract_error"
    assert error.value.receipt["request_count"] == 1
    assert error.value.receipt["provider_contract_error_count"] == 1
    assert error.value.receipt["unknown_usage_request_count"] == 1
    assert error.value.receipt["usage_observation_complete"] is False
    assert error.value.receipt["estimated_cost_usd"] is None
    assert "usage is missing" not in json.dumps(error.value.receipt)


def test_runner_atomically_rejects_second_metric_run(tmp_path: Path) -> None:
    inference = _inference()

    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        return ModelCallResult(_output(document), "gpt-5.6", 1, 1, "hidden")

    first = run_model_calibration(
        inference,
        PROFILE,
        transport,
        monotonic=lambda: 0.0,
    )
    assert first.receipt["status"] == "success"
    claim = tmp_path / "custody" / "metric-run.claim.json"
    assert claim.stat().st_mode & 0o777 == 0o600
    claim_payload = json.loads(claim.read_text())
    assert claim_payload["max_metric_runs"] == 1
    assert claim_payload["allow_calibration_retuning"] is False
    assert "The operation fails" not in claim.read_text()

    with pytest.raises(ModelCalibrationFailure, match="already consumed") as error:
        run_model_calibration(
            inference,
            PROFILE,
            transport,
            monotonic=lambda: 0.0,
        )

    assert error.value.receipt["termination_reason"] == "metric_run_already_consumed"
    assert error.value.receipt["request_count"] == 0


def test_run_ledger_does_not_accept_a_caller_selected_path(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        CalibrationRunLedger(tmp_path / "bypass")


def test_runner_does_not_accept_an_injected_ledger() -> None:
    class BypassLedger:
        def claim(self, *_args: object) -> bool:
            return True

    with pytest.raises(TypeError):
        run_model_calibration(
            _inference(),
            PROFILE,
            lambda document, _profile: ModelCallResult(
                _output(document), "gpt-5.6", 1, 1, "hidden"
            ),
            run_ledger=BypassLedger(),
            monotonic=lambda: 0.0,
        )


@pytest.mark.parametrize("failure_kind", ["none", "invalid_result", "invalid_output_error"])
def test_runner_marks_every_untrusted_usage_path_unknown(failure_kind: str) -> None:
    def transport(document: dict[str, object], _profile: object) -> ModelCallResult:
        if failure_kind == "none":
            return None  # type: ignore[return-value]
        if failure_kind == "invalid_result":
            return ModelCallResult(_output(document), "gpt-5.6", -1, 1, "hidden")
        raise ModelOutputError(
            "invalid usage",
            resolved_model="gpt-5.6",
            input_tokens=-1,
            output_tokens=1,
        )

    with pytest.raises(ModelCalibrationFailure) as error:
        run_model_calibration(
            _inference(),
            PROFILE,
            transport,
            monotonic=lambda: 0.0,
        )

    assert error.value.receipt["termination_reason"] == "provider_contract_error"
    assert error.value.receipt["unknown_usage_request_count"] == 1
    assert error.value.receipt["usage_observation_complete"] is False
    assert error.value.receipt["estimated_cost_usd"] is None
