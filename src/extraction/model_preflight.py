from __future__ import annotations

import json
import os
import sys
from hashlib import sha256
from pathlib import Path
from typing import Callable, Mapping

from jsonschema import Draft202012Validator, ValidationError

from src.extraction import model_runner
from src.extraction.development_slice import validate_extraction
from src.extraction.inference_profile import InferenceProfile, load_inference_profile
from src.extraction.model_runner import (
    ModelCallResult,
    ModelOutputError,
    OperationalModelError,
    ProviderContractError,
)
from src.extraction.openai_responses import (
    OpenAIResponsesTransport,
    build_response_request_body,
)


_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ROOT = _ROOT / "artifacts" / "extraction" / "calibration" / "audit-local"
_CLAIM_PATH = _LOCAL_ROOT / "provider-preflight.claim.json"
_RECEIPT_PATH = _LOCAL_ROOT / "provider-preflight.receipt.json"
_PUBLICATION_FAILURE_PATH = _LOCAL_ROOT / "provider-preflight.publication-failure.json"
_PROFILE_PATH = _ROOT / "configs" / "extraction" / "inference-profile-gpt-5.6-v1.json"
_SCHEMA = json.loads(
    (_ROOT / "schemas" / "model-provider-preflight-receipt.schema.json").read_text()
)
_MAX_ATTEMPTS = 3
_MAX_COST_USD = 0.10

SYNTHETIC_DOCUMENT: Mapping[str, object] = {
    "document_id": "preflight:synthetic-contract-v1",
    "source": "github",
    "title": "Synthetic contract check",
    "text": "The scheduled export fails before producing a file.",
    "published_at": "2026-01-01T00:00:00Z",
    "source_url": "https://research-auto.local/preflight",
}

Transport = Callable[[dict[str, object], InferenceProfile], ModelCallResult]


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _snapshot(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False, "sha256": None, "mode": None, "size": None, "mtime_ns": None}
    stat = path.stat()
    return {
        "exists": True,
        "sha256": _digest_bytes(path.read_bytes()),
        "mode": stat.st_mode & 0o777,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _atomic_create(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _upper_bound(profile: InferenceProfile) -> float:
    body = build_response_request_body(SYNTHETIC_DOCUMENT, profile)
    request_bytes = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
    per_attempt = (
        request_bytes * profile.input_usd_per_million
        + profile.max_output_tokens * profile.output_usd_per_million
    ) / 1_000_000
    return round(per_attempt * _MAX_ATTEMPTS, 8)


def _base_receipt(
    profile: InferenceProfile,
    upper: float,
    before: Mapping[str, object],
    *,
    synthetic_hash: str,
    policy_hash: str,
    claim_hash: str,
) -> dict[str, object]:
    return {
        "schema_version": "model-provider-preflight-receipt/v1",
        "status": "PREREQUISITE_FAIL",
        "termination_reason": "not_started",
        "profile_sha256": profile.profile_sha256,
        "prompt_sha256": profile.prompt_sha256,
        "output_schema_sha256": profile.output_schema_sha256,
        "requested_model": profile.model,
        "synthetic_document_sha256": synthetic_hash,
        "preflight_policy_sha256": policy_hash,
        "claim_sha256": claim_hash,
        "resolved_model": None,
        "request_count": 0,
        "retry_count": 0,
        "unknown_usage_request_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "observed_cost_usd": 0.0,
        "conservative_cost_upper_bound_usd": upper,
        "metric_claim_before": dict(before),
        "metric_claim_after": dict(before),
        "metric_claim_unchanged": True,
        "structured_output_valid": False,
        "raw_response_persisted": False,
        "structured_output_persisted": False,
        "request_id_persisted": False,
        "secret_persisted": False,
    }


def _publish(receipt: dict[str, object]) -> dict[str, object]:
    try:
        Draft202012Validator(_SCHEMA).validate(receipt)
    except ValidationError:
        return _publication_failure(receipt, "receipt_validation_failed", "validation")
    try:
        _atomic_create(_RECEIPT_PATH, receipt)
    except Exception:
        return _publication_failure(receipt, "receipt_publication_failed", "publication")
    return receipt


def _publication_failure(
    receipt: dict[str, object], termination_reason: str, failure_stage: str
) -> dict[str, object]:
    marker = {
        "schema_version": "model-provider-preflight-publication-failure/v1",
        "status": "PUBLICATION_FAIL",
        "failure_stage": failure_stage,
        "receipt_sha256": _digest_bytes(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        ),
    }
    try:
        _atomic_create(_PUBLICATION_FAILURE_PATH, marker)
    except Exception:
        pass
    receipt["status"] = "PUBLICATION_FAIL"
    receipt["termination_reason"] = termination_reason
    return receipt


def execute_provider_preflight(
    profile: InferenceProfile, transport: Transport
) -> dict[str, object]:
    metric_path = model_runner._CALIBRATION_RUN_CLAIM_PATH
    before = _snapshot(metric_path)
    upper = _upper_bound(profile)
    synthetic_hash = _digest_bytes(_canonical_bytes(SYNTHETIC_DOCUMENT))
    policy = {
        "max_attempts": _MAX_ATTEMPTS,
        "max_cost_usd": _MAX_COST_USD,
        "retry_class": "operational_only",
    }
    policy_hash = _digest_bytes(_canonical_bytes(policy))
    claim = {
        "schema_version": "model-provider-preflight-claim/v1",
        "profile_sha256": profile.profile_sha256,
        "prompt_sha256": profile.prompt_sha256,
        "output_schema_sha256": profile.output_schema_sha256,
        "synthetic_document_sha256": synthetic_hash,
        "policy": policy,
        "policy_sha256": policy_hash,
    }
    claim_hash = _digest_bytes(_canonical_bytes(claim))
    receipt = _base_receipt(
        profile,
        upper,
        before,
        synthetic_hash=synthetic_hash,
        policy_hash=policy_hash,
        claim_hash=claim_hash,
    )
    if upper > _MAX_COST_USD:
        receipt["termination_reason"] = "cost_upper_bound_exceeded"
        return receipt
    try:
        _atomic_create(_CLAIM_PATH, claim)
    except FileExistsError:
        receipt["status"] = "ALREADY_CONSUMED"
        receipt["termination_reason"] = "preflight_claim_exists"
        return receipt

    resolved_model: str | None = None
    output_valid = False
    for attempt in range(_MAX_ATTEMPTS):
        receipt["request_count"] = int(receipt["request_count"]) + 1
        try:
            result = transport(dict(SYNTHETIC_DOCUMENT), profile)
        except OperationalModelError:
            receipt["unknown_usage_request_count"] = int(
                receipt["unknown_usage_request_count"]
            ) + 1
            if attempt + 1 < _MAX_ATTEMPTS:
                receipt["retry_count"] = int(receipt["retry_count"]) + 1
                continue
            receipt["status"] = "OPERATIONAL_EXHAUSTED"
            receipt["termination_reason"] = "operational_retry_budget_exhausted"
            break
        except ProviderContractError:
            receipt["unknown_usage_request_count"] = int(
                receipt["unknown_usage_request_count"]
            ) + 1
            receipt["status"] = "CONTRACT_FAIL"
            receipt["termination_reason"] = "provider_contract_error"
            break
        except ModelOutputError as error:
            if (
                isinstance(error.input_tokens, bool)
                or not isinstance(error.input_tokens, int)
                or error.input_tokens < 0
                or isinstance(error.output_tokens, bool)
                or not isinstance(error.output_tokens, int)
                or error.output_tokens < 0
            ):
                receipt["status"] = "CONTRACT_FAIL"
                receipt["termination_reason"] = "response_validation_failed"
                receipt["unknown_usage_request_count"] = int(
                    receipt["unknown_usage_request_count"]
                ) + 1
                break
            receipt["input_tokens"] = int(receipt["input_tokens"]) + error.input_tokens
            receipt["output_tokens"] = int(receipt["output_tokens"]) + error.output_tokens
            resolved_model = error.resolved_model
            receipt["status"] = "CONTRACT_FAIL"
            receipt["termination_reason"] = "structured_output_error"
            break
        except (Exception, KeyboardInterrupt):
            receipt["unknown_usage_request_count"] = int(
                receipt["unknown_usage_request_count"]
            ) + 1
            receipt["status"] = "INTERNAL_FAIL"
            receipt["termination_reason"] = "unexpected_internal_error"
            break
        try:
            if result.resolved_model != profile.model and not result.resolved_model.startswith(
                f"{profile.model}-"
            ):
                raise ValueError("resolved model mismatch")
            if result.input_tokens < 0 or result.output_tokens < 0:
                raise ValueError("invalid usage")
            validate_extraction(SYNTHETIC_DOCUMENT, result.output)
        except (AttributeError, TypeError, ValueError):
            receipt["status"] = "CONTRACT_FAIL"
            receipt["termination_reason"] = "response_validation_failed"
            receipt["unknown_usage_request_count"] = int(
                receipt["unknown_usage_request_count"]
            ) + 1
            break
        resolved_model = result.resolved_model
        receipt["input_tokens"] = int(receipt["input_tokens"]) + result.input_tokens
        receipt["output_tokens"] = int(receipt["output_tokens"]) + result.output_tokens
        output_valid = True
        receipt["status"] = "PASS"
        receipt["termination_reason"] = "contract_validated"
        break

    receipt["resolved_model"] = resolved_model
    receipt["structured_output_valid"] = output_valid
    unknown = int(receipt["unknown_usage_request_count"])
    if unknown:
        receipt["observed_cost_usd"] = None
    else:
        receipt["observed_cost_usd"] = round(
            (
                int(receipt["input_tokens"]) * profile.input_usd_per_million
                + int(receipt["output_tokens"]) * profile.output_usd_per_million
            )
            / 1_000_000,
            8,
        )
    after = _snapshot(metric_path)
    receipt["metric_claim_after"] = after
    receipt["metric_claim_unchanged"] = before == after
    if before != after:
        receipt["status"] = "METRIC_CLAIM_DRIFT"
        receipt["termination_reason"] = "metric_claim_changed"
    return _publish(receipt)


_EXIT_CODES = {
    "PASS": 0,
    "CONTRACT_FAIL": 2,
    "PREREQUISITE_FAIL": 3,
    "OPERATIONAL_EXHAUSTED": 4,
    "PUBLICATION_FAIL": 5,
    "ALREADY_CONSUMED": 6,
    "METRIC_CLAIM_DRIFT": 7,
    "INTERNAL_FAIL": 8,
}


def main() -> int:
    try:
        profile = load_inference_profile(_PROFILE_PATH)
        transport = OpenAIResponsesTransport.from_environment(profile)
    except ValueError:
        return 3
    receipt = execute_provider_preflight(profile, transport)
    print(json.dumps({"status": receipt["status"]}, sort_keys=True))
    return _EXIT_CODES[str(receipt["status"])]


if __name__ == "__main__":
    sys.exit(main())
