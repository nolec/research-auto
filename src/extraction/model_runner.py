from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable, Mapping

from src.extraction.development_slice import DevelopmentInference, validate_extraction
from src.extraction.inference_profile import InferenceProfile


_ROOT = Path(__file__).resolve().parents[2]
_CALIBRATION_RUN_CLAIM_PATH = (
    _ROOT
    / "artifacts"
    / "extraction"
    / "calibration"
    / "audit-local"
    / "run-ledger"
    / "metric-run.claim.json"
)


class OperationalModelError(RuntimeError):
    """A retryable provider or transport failure."""


class ProviderContractError(RuntimeError):
    """A non-retryable, sanitized provider response or request failure."""


class ModelOutputError(ValueError):
    """A non-retryable, sanitized model-output failure with billable usage."""

    def __init__(
        self,
        message: str,
        *,
        resolved_model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        super().__init__(message)
        self.resolved_model = resolved_model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class ModelCalibrationFailure(RuntimeError):
    """A failed or partial calibration run with an aggregate-only receipt."""

    def __init__(self, message: str, receipt: Mapping[str, object]) -> None:
        super().__init__(message)
        self.receipt = dict(receipt)


@dataclass(frozen=True)
class ModelCallResult:
    output: Mapping[str, object]
    resolved_model: str
    input_tokens: int
    output_tokens: int
    request_id: str | None = None


@dataclass(frozen=True)
class ModelCalibrationRun:
    outputs: tuple[dict[str, object], ...]
    receipt: dict[str, object]


@dataclass(frozen=True)
class CalibrationRunLedger:
    """Durable, local custody for the single authorized metric run."""

    def claim(self, profile: InferenceProfile, corpus_hash: str) -> bool:
        experiment_key = _digest(
            {
                "profile_sha256": profile.profile_sha256,
                "prompt_sha256": profile.prompt_sha256,
                "output_schema_sha256": profile.output_schema_sha256,
                "inference_corpus_sha256": corpus_hash,
            }
        )
        marker = _CALIBRATION_RUN_CLAIM_PATH
        marker.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "schema_version": "model-calibration-run-claim/v1",
                "experiment_sha256": experiment_key,
                "max_metric_runs": profile.max_metric_runs,
                "allow_calibration_retuning": profile.allow_calibration_retuning,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return True


ModelTransport = Callable[[dict[str, object], InferenceProfile], ModelCallResult]


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _validate_input(inference: DevelopmentInference, profile: InferenceProfile) -> str:
    corpus_hash = _digest(inference.corpus)
    if inference.receipt.get("inference_corpus_sha256") != corpus_hash:
        raise ValueError("inference corpus hash mismatch")
    if len(inference.corpus) != profile.input_count:
        raise ValueError(f"model calibration requires exactly {profile.input_count} records")
    if inference.receipt.get("selected_count") != profile.input_count:
        raise ValueError("selected_count does not match the frozen profile")
    if inference.receipt.get("source_spike_reserved_emitted") != 0:
        raise ValueError("source-spike-reserved records are not permitted")
    counts = {source: 0 for source in profile.sources}
    identifiers: set[object] = set()
    for document in inference.corpus:
        document_id = document.get("document_id")
        if document_id in identifiers:
            raise ValueError("duplicate inference document_id")
        identifiers.add(document_id)
        source = document.get("source")
        if source not in counts:
            raise ValueError("inference contains an unapproved calibration source")
        counts[str(source)] += 1
    if any(count != profile.input_count // len(profile.sources) for count in counts.values()):
        raise ValueError("calibration source membership must remain evenly stratified")
    return corpus_hash


def run_model_calibration(
    inference: DevelopmentInference,
    profile: InferenceProfile,
    transport: ModelTransport,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> ModelCalibrationRun:
    corpus_hash = _validate_input(inference, profile)
    started = monotonic()
    outputs: list[dict[str, object]] = []
    request_count = retry_count = operational_error_count = invalid_count = 0
    model_output_error_count = 0
    provider_contract_error_count = 0
    unknown_usage_request_count = 0
    input_tokens = output_tokens = 0
    resolved_models: set[str] = set()

    def fail(
        termination_reason: str, message: str, *, cause: BaseException | None = None
    ) -> None:
        receipt = _failure_receipt(
            profile=profile,
            corpus_hash=corpus_hash,
            outputs=outputs,
            request_count=request_count,
            retry_count=retry_count,
            operational_error_count=operational_error_count,
            model_output_error_count=model_output_error_count,
            provider_contract_error_count=provider_contract_error_count,
            unknown_usage_request_count=unknown_usage_request_count,
            invalid_count=invalid_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            resolved_models=resolved_models,
            termination_reason=termination_reason,
        )
        error = ModelCalibrationFailure(message, receipt)
        if cause is not None:
            raise error from cause
        raise error

    if profile.max_metric_runs != 1 or profile.allow_calibration_retuning:
        fail("experiment_policy_mismatch", "frozen experiment policy is not executable")
    if not CalibrationRunLedger().claim(profile, corpus_hash):
        fail(
            "metric_run_already_consumed",
            "calibration metric run authorization is already consumed",
        )

    for document in inference.corpus:
        if monotonic() - started > profile.max_wall_seconds:
            fail("wall_time_exceeded", "model calibration wall-time ceiling exceeded")
        result: ModelCallResult | None = None
        output_error: ModelOutputError | None = None
        for attempt in range(profile.max_retries_per_document + 1):
            request_count += 1
            try:
                result = transport(dict(document), profile)
            except ModelOutputError as error:
                output_error = error
                model_output_error_count += 1
                if monotonic() - started > profile.max_wall_seconds:
                    fail(
                        "wall_time_exceeded",
                        "model calibration wall-time ceiling exceeded",
                        cause=error,
                    )
                break
            except OperationalModelError as error:
                operational_error_count += 1
                unknown_usage_request_count += 1
                if monotonic() - started > profile.max_wall_seconds:
                    fail(
                        "wall_time_exceeded",
                        "model calibration wall-time ceiling exceeded",
                        cause=error,
                    )
                if attempt == profile.max_retries_per_document:
                    fail(
                        "retry_budget_exhausted",
                        "model calibration retry budget exhausted",
                        cause=error,
                    )
                retry_count += 1
                continue
            except ProviderContractError as error:
                provider_contract_error_count += 1
                unknown_usage_request_count += 1
                fail(
                    "provider_contract_error",
                    "provider contract validation failed",
                    cause=error,
                )
            break
        if output_error is not None:
            try:
                _validate_usage(output_error.input_tokens, output_error.output_tokens)
                resolved_model = _resolved_model(output_error.resolved_model)
            except ValueError as error:
                provider_contract_error_count += 1
                unknown_usage_request_count += 1
                fail(
                    "provider_contract_error",
                    "provider contract validation failed",
                    cause=error,
                )
            input_tokens += output_error.input_tokens
            output_tokens += output_error.output_tokens
            if _estimated_cost(profile, input_tokens, output_tokens) > profile.max_cost_usd:
                fail("cost_ceiling_exceeded", "model calibration cost ceiling exceeded")
            if not _approved_resolved_model(profile, resolved_model):
                fail(
                    "resolved_model_mismatch",
                    "provider resolved model does not match the frozen profile",
                )
            resolved_models.add(resolved_model)
            invalid_count += 1
            outputs.append(_invalid_output(document))
            if monotonic() - started > profile.max_wall_seconds:
                fail("wall_time_exceeded", "model calibration wall-time ceiling exceeded")
            continue
        if result is None:
            provider_contract_error_count += 1
            unknown_usage_request_count += 1
            fail("provider_contract_error", "provider contract validation failed")
        try:
            _validate_usage(result.input_tokens, result.output_tokens)
            resolved_model = _resolved_model(result.resolved_model)
        except ValueError as error:
            provider_contract_error_count += 1
            unknown_usage_request_count += 1
            fail(
                "provider_contract_error",
                "provider contract validation failed",
                cause=error,
            )
        input_tokens += result.input_tokens
        output_tokens += result.output_tokens
        if _estimated_cost(profile, input_tokens, output_tokens) > profile.max_cost_usd:
            fail("cost_ceiling_exceeded", "model calibration cost ceiling exceeded")
        if not _approved_resolved_model(profile, resolved_model):
            fail(
                "resolved_model_mismatch",
                "provider resolved model does not match the frozen profile",
            )
        resolved_models.add(resolved_model)
        output = dict(result.output)
        try:
            validate_extraction(document, output)
        except ValueError:
            invalid_count += 1
            output = _invalid_output(document)
        outputs.append(output)
        if monotonic() - started > profile.max_wall_seconds:
            fail("wall_time_exceeded", "model calibration wall-time ceiling exceeded")

    if monotonic() - started > profile.max_wall_seconds:
        fail("wall_time_exceeded", "model calibration wall-time ceiling exceeded")
    frozen_outputs = tuple(outputs)
    receipt = {
        "schema_version": "model-calibration-run-receipt/v1",
        "variant_id": profile.profile_id,
        "status": "success",
        "provider": profile.provider,
        "requested_model": profile.model,
        "resolved_models": sorted(resolved_models),
        "profile_sha256": profile.profile_sha256,
        "prompt_sha256": profile.prompt_sha256,
        "extraction_schema_version": profile.extraction_schema_version,
        "output_schema_sha256": profile.output_schema_sha256,
        "source_role": profile.source_role,
        "sources": list(profile.sources),
        "inference_corpus_sha256": corpus_hash,
        "input_count": len(inference.corpus),
        "output_count": len(frozen_outputs),
        "valid_count": len(frozen_outputs) - invalid_count,
        "invalid_count": invalid_count,
        "request_count": request_count,
        "retry_count": retry_count,
        "operational_error_count": operational_error_count,
        "model_output_error_count": model_output_error_count,
        "provider_contract_error_count": provider_contract_error_count,
        "unknown_usage_request_count": unknown_usage_request_count,
        "usage_observation_complete": unknown_usage_request_count == 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": (
            round(_estimated_cost(profile, input_tokens, output_tokens), 8)
            if unknown_usage_request_count == 0
            else None
        ),
        "output_sha256": _digest(frozen_outputs),
        "outputs_persisted": False,
        "raw_responses_persisted": False,
        "reverification_requires_local_custody": True,
    }
    return ModelCalibrationRun(frozen_outputs, receipt)


def _invalid_output(document: Mapping[str, object]) -> dict[str, object]:
    return {"document_id": document.get("document_id"), "invalid_output": True}


def _validate_usage(input_tokens: object, output_tokens: object) -> None:
    if (
        isinstance(input_tokens, bool)
        or not isinstance(input_tokens, int)
        or input_tokens < 0
    ):
        raise ValueError("provider input token usage must be a non-negative integer")
    if (
        isinstance(output_tokens, bool)
        or not isinstance(output_tokens, int)
        or output_tokens < 0
    ):
        raise ValueError("provider output token usage must be a non-negative integer")


def _estimated_cost(
    profile: InferenceProfile, input_tokens: int, output_tokens: int
) -> float:
    return (
        input_tokens * profile.input_usd_per_million
        + output_tokens * profile.output_usd_per_million
    ) / 1_000_000


def _resolved_model(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("provider resolved model must be a non-empty string")
    return value


def _approved_resolved_model(profile: InferenceProfile, value: str) -> bool:
    return value == profile.model or value.startswith(f"{profile.model}-")


def _failure_receipt(
    *,
    profile: InferenceProfile,
    corpus_hash: str,
    outputs: list[dict[str, object]],
    request_count: int,
    retry_count: int,
    operational_error_count: int,
    model_output_error_count: int,
    provider_contract_error_count: int,
    unknown_usage_request_count: int,
    invalid_count: int,
    input_tokens: int,
    output_tokens: int,
    resolved_models: set[str],
    termination_reason: str,
) -> dict[str, object]:
    frozen_outputs = tuple(outputs)
    return {
        "schema_version": "model-calibration-run-receipt/v1",
        "variant_id": profile.profile_id,
        "status": "partial" if outputs else "failed",
        "termination_reason": termination_reason,
        "provider": profile.provider,
        "requested_model": profile.model,
        "resolved_models": sorted(resolved_models),
        "profile_sha256": profile.profile_sha256,
        "prompt_sha256": profile.prompt_sha256,
        "extraction_schema_version": profile.extraction_schema_version,
        "output_schema_sha256": profile.output_schema_sha256,
        "source_role": profile.source_role,
        "sources": list(profile.sources),
        "inference_corpus_sha256": corpus_hash,
        "input_count": profile.input_count,
        "output_count": len(frozen_outputs),
        "valid_count": len(frozen_outputs) - invalid_count,
        "invalid_count": invalid_count,
        "request_count": request_count,
        "retry_count": retry_count,
        "operational_error_count": operational_error_count,
        "model_output_error_count": model_output_error_count,
        "provider_contract_error_count": provider_contract_error_count,
        "unknown_usage_request_count": unknown_usage_request_count,
        "usage_observation_complete": unknown_usage_request_count == 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": (
            round(_estimated_cost(profile, input_tokens, output_tokens), 8)
            if unknown_usage_request_count == 0
            else None
        ),
        "output_sha256": _digest(frozen_outputs),
        "outputs_persisted": False,
        "raw_responses_persisted": False,
        "reverification_requires_local_custody": True,
    }
