from __future__ import annotations

import hashlib
import json
import time
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence, cast
from uuid import uuid4

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER

from src.source_spike.adapters.ted_http import (
    HttpTedTransport,
    TedTransportFailure,
    TedTransportSuccess,
)
from src.source_spike.ted_capacity import TedRunBudget
from src.source_spike.protocol import content_sha256
from src.source_spike.ted_capacity_manifest import validate_ted_capacity_manifest


QUERY_GENERATOR_VERSION = "1.0.0"
VALIDATION_CONTRACT_VERSION = "1.0.0"
TRANSPORT_VERSION = "ted-http/1.0.0"
_ROOT = Path(__file__).resolve().parents[2]
_RECEIPT_SCHEMA = json.loads(
    (_ROOT / "schemas/ted-query-validation-receipt.schema.json").read_text(encoding="utf-8")
)
_RECEIPT_VALIDATOR = Draft202012Validator(_RECEIPT_SCHEMA, format_checker=FORMAT_CHECKER)
_EXPECTED_STRATA = (
    "software_and_information_systems",
    "business_services",
    "health_and_social_services",
    "repair_and_maintenance_services",
)
_EXPECTED_SORT = (
    ("publication-date", "DESC"),
    ("publication-number", "ASC"),
)
_SORT_CLAUSE = "SORT BY publication-date DESC, publication-number ASC"
_REQUEST_CONTRACT = {
    "endpoint": "/v3/notices/search",
    "method": "POST",
    "check_query_syntax": True,
    "fields": ["publication-number"],
    "page": 1,
    "limit": 1,
    "scope": "ALL",
    "pagination_mode": "PAGE_NUMBER",
}


@dataclass(frozen=True)
class TedQueryCandidate:
    stratum: str
    query: str
    query_sha256: str


@dataclass(frozen=True)
class TedQuerySet:
    generator_version: str
    query_set_sha256: str
    candidates: tuple[TedQueryCandidate, ...]


@dataclass(frozen=True)
class TedQueryValidationOutcome:
    stratum: str
    query_sha256: str
    syntax_valid: bool
    error_code: str | None


@dataclass(frozen=True)
class TedQueryValidationResult:
    status: str
    termination_reason: str
    generator_version: str
    query_set_sha256: str
    strata: tuple[TedQueryValidationOutcome, ...]
    logical_requests: int
    http_attempts: int
    retries: int
    response_bytes: int
    max_logical_requests: int
    max_http_attempts: int
    deadline_seconds: float
    max_response_bytes: int


@dataclass(frozen=True)
class TedQueryValidationExecution:
    exit_code: int
    run_id: str
    status: str
    receipt_path: Path | None
    error_code: str | None


class TedQueryValidationTransport(Protocol):
    def validate_query_syntax(
        self,
        *,
        query: str,
        max_http_attempts: int,
        request_timeout_seconds: float,
        deadline_seconds: float,
        max_response_bytes: int,
        max_retries: int,
        base_backoff_seconds: float,
        max_backoff_seconds: float,
    ) -> TedTransportSuccess | TedTransportFailure: ...


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_query_set(manifest: Mapping[str, object]) -> TedQuerySet:
    sort_values = cast(Sequence[Mapping[str, object]], manifest.get("sort", ()))
    actual_sort = tuple(
        (str(value.get("field", "")), str(value.get("direction", "")))
        for value in sort_values
        if isinstance(value, Mapping)
    )
    if actual_sort != _EXPECTED_SORT:
        raise ValueError("TED query sort contract mismatch")
    strata = manifest.get("strata")
    if not isinstance(strata, list) or tuple(
        value.get("name") if isinstance(value, Mapping) else None for value in strata
    ) != _EXPECTED_STRATA:
        raise ValueError("TED query strata contract mismatch")
    candidates: list[TedQueryCandidate] = []
    for value in strata:
        assert isinstance(value, Mapping)
        base_query = value.get("query")
        if not isinstance(base_query, str) or not base_query.strip() or "SORT BY" in base_query.upper():
            raise ValueError("TED base query contract mismatch")
        query = f"{base_query.strip()} {_SORT_CLAUSE}"
        candidates.append(
            TedQueryCandidate(str(value["name"]), query, _sha256(query))
        )
    query_set_payload = [
        {"stratum": value.stratum, "query_sha256": value.query_sha256}
        for value in candidates
    ]
    query_set_sha256 = hashlib.sha256(
        json.dumps(
            query_set_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return TedQuerySet(
        QUERY_GENERATOR_VERSION,
        query_set_sha256,
        tuple(candidates),
    )


def run_query_validation(
    manifest: Mapping[str, object],
    transport: TedQueryValidationTransport,
    *,
    max_logical_requests: int = 4,
    max_http_attempts: int = 8,
    deadline_seconds: float = 30,
    max_response_bytes: int = 2_097_152,
    monotonic: Callable[[], float] = time.monotonic,
) -> TedQueryValidationResult:
    query_set = build_query_set(manifest)
    budget = TedRunBudget(
        max_logical_requests=max_logical_requests,
        max_http_attempts=max_http_attempts,
        deadline_seconds=deadline_seconds,
        max_response_bytes=max_response_bytes,
        monotonic=monotonic,
    )
    outcomes: list[TedQueryValidationOutcome] = []
    retries = 0
    termination_reason = "validated"
    for candidate in query_set.candidates:
        allowance = budget.begin_request(max_attempts_per_request=2)
        if not allowance.allowed:
            termination_reason = allowance.termination_reason or "budget_exhausted"
            break
        response = transport.validate_query_syntax(
            query=candidate.query,
            max_http_attempts=allowance.max_http_attempts,
            request_timeout_seconds=10,
            deadline_seconds=allowance.deadline_seconds,
            max_response_bytes=allowance.max_response_bytes,
            max_retries=max(0, allowance.max_http_attempts - 1),
            base_backoff_seconds=1,
            max_backoff_seconds=4,
        )
        retries += response.retry_count
        budget_reason = budget.record(
            http_attempts=response.http_attempt_count,
            response_bytes=response.response_bytes,
        )
        syntax_valid = isinstance(response, TedTransportSuccess)
        error_code = None if syntax_valid else response.error_code
        outcomes.append(
            TedQueryValidationOutcome(
                candidate.stratum,
                candidate.query_sha256,
                syntax_valid,
                error_code,
            )
        )
        if budget_reason is not None:
            termination_reason = budget_reason
            break
        if not syntax_valid:
            termination_reason = error_code or "query_validation_failed"
            break
    passed = len(outcomes) == len(query_set.candidates) and all(
        value.syntax_valid for value in outcomes
    ) and termination_reason == "validated"
    return TedQueryValidationResult(
        "PASS" if passed else "FAIL",
        termination_reason,
        query_set.generator_version,
        query_set.query_set_sha256,
        tuple(outcomes),
        budget.logical_requests,
        budget.http_attempts,
        retries,
        budget.response_bytes,
        max_logical_requests,
        max_http_attempts,
        deadline_seconds,
        max_response_bytes,
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def build_validation_receipt(
    result: TedQueryValidationResult,
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    elapsed_ms: int,
    capacity_manifest_hash: str,
    feasibility_hash: str,
    compliance_hash: str,
) -> dict[str, object]:
    request_contract = dict(_REQUEST_CONTRACT)
    request_contract["request_shape_sha256"] = _canonical_hash(_REQUEST_CONTRACT)
    return {
        "schema_version": 1,
        "validation_contract_version": VALIDATION_CONTRACT_VERSION,
        "transport_version": TRANSPORT_VERSION,
        "run_id": run_id,
        "status": result.status,
        "termination_reason": result.termination_reason,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_ms": elapsed_ms,
        "capacity_manifest_hash": capacity_manifest_hash,
        "feasibility_hash": feasibility_hash,
        "compliance_hash": compliance_hash,
        "generator_version": result.generator_version,
        "query_set_sha256": result.query_set_sha256,
        "request_contract": request_contract,
        "budget": {
            "max_logical_requests": result.max_logical_requests,
            "max_http_attempts": result.max_http_attempts,
            "deadline_seconds": result.deadline_seconds,
            "max_response_bytes": result.max_response_bytes,
        },
        "retained_queries": 0,
        "retained_response_bodies": 0,
        "strata": [
            {
                "stratum": value.stratum,
                "query_sha256": value.query_sha256,
                "syntax_valid": value.syntax_valid,
                "error_code": value.error_code,
            }
            for value in result.strata
        ],
        "metrics": {
            "logical_requests": result.logical_requests,
            "http_attempts": result.http_attempts,
            "retries": result.retries,
            "response_bytes": result.response_bytes,
        },
    }


def validate_validation_receipt(
    receipt: Mapping[str, object],
    *,
    capacity_manifest_hash: str,
    feasibility_hash: str,
    compliance_hash: str,
    query_set_sha256: str,
) -> list[str]:
    errors = [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in sorted(
            _RECEIPT_VALIDATOR.iter_errors(receipt),
            key=lambda value: tuple(map(str, value.absolute_path)),
        )
    ]
    for key, expected, label in (
        ("capacity_manifest_hash", capacity_manifest_hash, "capacity manifest hash"),
        ("feasibility_hash", feasibility_hash, "feasibility hash"),
        ("compliance_hash", compliance_hash, "compliance hash"),
        ("query_set_sha256", query_set_sha256, "query set hash"),
    ):
        if receipt.get(key) != expected:
            errors.append(f"{label} mismatch")
    request = receipt.get("request_contract")
    if not isinstance(request, Mapping) or any(
        request.get(key) != value for key, value in _REQUEST_CONTRACT.items()
    ) or request.get("request_shape_sha256") != _canonical_hash(_REQUEST_CONTRACT):
        errors.append("request contract mismatch")
    strata = receipt.get("strata")
    if (
        isinstance(strata, list)
        and len(strata) == len(_EXPECTED_STRATA)
        and all(isinstance(value, Mapping) for value in strata)
    ):
        observed_query_set_hash = _canonical_hash([
            {
                "stratum": value.get("stratum"),
                "query_sha256": value.get("query_sha256"),
            }
            for value in strata
        ])
        if observed_query_set_hash != receipt.get("query_set_sha256"):
            errors.append("receipt query set hash mismatch")
    if receipt.get("status") == "PASS" and (
        not isinstance(strata, list)
        or tuple(value.get("stratum") if isinstance(value, Mapping) else None for value in strata) != _EXPECTED_STRATA
        or not all(isinstance(value, Mapping) and value.get("syntax_valid") is True for value in strata)
    ):
        errors.append("PASS receipt requires four valid strata")
    budget = receipt.get("budget")
    metrics = receipt.get("metrics")
    if isinstance(budget, Mapping) and isinstance(metrics, Mapping):
        checks = (
            ("logical_requests", "max_logical_requests", "receipt logical request budget exceeded"),
            ("http_attempts", "max_http_attempts", "receipt HTTP attempt budget exceeded"),
            ("response_bytes", "max_response_bytes", "receipt response byte budget exceeded"),
        )
        for observed_key, limit_key, message in checks:
            observed = metrics.get(observed_key)
            limit = budget.get(limit_key)
            if (
                isinstance(observed, int)
                and not isinstance(observed, bool)
                and isinstance(limit, int)
                and not isinstance(limit, bool)
                and observed > limit
            ):
                errors.append(message)
        logical_requests = metrics.get("logical_requests")
        http_attempts = metrics.get("http_attempts")
        retries = metrics.get("retries")
        if all(isinstance(value, int) and not isinstance(value, bool) for value in (logical_requests, http_attempts, retries)) and not (
            retries <= http_attempts <= logical_requests + retries
        ):
            errors.append("receipt transport arithmetic mismatch")
    if receipt.get("status") == "PASS":
        if receipt.get("termination_reason") != "validated":
            errors.append("PASS receipt termination mismatch")
        if isinstance(strata, list) and any(
            not isinstance(value, Mapping) or value.get("error_code") is not None
            for value in strata
        ):
            errors.append("PASS receipt contains an outcome error")
        if isinstance(metrics, Mapping):
            logical_requests = metrics.get("logical_requests")
            http_attempts = metrics.get("http_attempts")
            retries = metrics.get("retries")
            response_bytes = metrics.get("response_bytes")
            if logical_requests != len(_EXPECTED_STRATA):
                errors.append("PASS receipt logical request count mismatch")
            if (
                not isinstance(http_attempts, int)
                or isinstance(http_attempts, bool)
                or not isinstance(retries, int)
                or isinstance(retries, bool)
                or http_attempts != len(_EXPECTED_STRATA) + retries
            ):
                errors.append("PASS receipt HTTP attempt arithmetic mismatch")
            if (
                not isinstance(response_bytes, int)
                or isinstance(response_bytes, bool)
                or response_bytes <= 0
            ):
                errors.append("PASS receipt requires positive response bytes")
    return errors


def _output_root_ready(output_root: Path) -> bool:
    if output_root.is_symlink() or (output_root.exists() and not output_root.is_dir()):
        return False
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return output_root.is_dir() and not output_root.is_symlink()


def _atomic_json_write(path: Path, value: Mapping[str, object], *, run_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{run_id}.tmp")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def execute_query_validation(
    manifest: Mapping[str, object],
    transport: TedQueryValidationTransport,
    *,
    output_root: Path,
    capacity_manifest_hash: str,
    feasibility_hash: str,
    compliance_hash: str,
    run_id: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    elapsed_ms: int | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> TedQueryValidationExecution:
    execution_started = monotonic()
    actual_started_at = started_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        query_set = build_query_set(manifest)
    except ValueError:
        return TedQueryValidationExecution(3, run_id, "FAIL", None, "prerequisite_failed")
    if not _output_root_ready(output_root):
        return TedQueryValidationExecution(3, run_id, "FAIL", None, "prerequisite_failed")
    result = run_query_validation(manifest, transport)
    actual_finished_at = finished_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    actual_elapsed_ms = elapsed_ms if elapsed_ms is not None else max(0, int((monotonic() - execution_started) * 1000))
    receipt = build_validation_receipt(
        result,
        run_id=run_id,
        started_at=actual_started_at,
        finished_at=actual_finished_at,
        elapsed_ms=actual_elapsed_ms,
        capacity_manifest_hash=capacity_manifest_hash,
        feasibility_hash=feasibility_hash,
        compliance_hash=compliance_hash,
    )
    errors = validate_validation_receipt(
        receipt,
        capacity_manifest_hash=capacity_manifest_hash,
        feasibility_hash=feasibility_hash,
        compliance_hash=compliance_hash,
        query_set_sha256=query_set.query_set_sha256,
    )
    if errors:
        return TedQueryValidationExecution(3, run_id, "FAIL", None, "receipt_validation_failed")
    receipt_path = output_root / "runs" / run_id / "receipt.json"
    try:
        _atomic_json_write(receipt_path, receipt, run_id=run_id)
        _atomic_json_write(output_root / "latest.json", receipt, run_id=run_id)
    except OSError:
        return TedQueryValidationExecution(4, run_id, result.status, None, "receipt_persistence_failed")
    return TedQueryValidationExecution(
        0 if result.status == "PASS" else 2,
        run_id,
        result.status,
        receipt_path,
        None if result.status == "PASS" else result.termination_reason,
    )


def main(
    argv: list[str] | None = None,
    *,
    transport_factory: Callable[[], TedQueryValidationTransport] = HttpTedTransport,
) -> int:
    parser = argparse.ArgumentParser(description="Validate frozen TED query syntax")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_ROOT / "config/source-spike/ted-capacity.json",
    )
    parser.add_argument(
        "--feasibility",
        type=Path,
        default=_ROOT / "config/source-spike/feasibility/ted.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_ROOT / "artifacts/source-spike/ted-query-validation",
    )
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        feasibility = json.loads(args.feasibility.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"status": "FAIL", "error_code": "prerequisite_failed"}))
        return 3
    if not isinstance(manifest, Mapping) or not isinstance(feasibility, Mapping):
        print(json.dumps({"status": "FAIL", "error_code": "prerequisite_failed"}))
        return 3
    if validate_ted_capacity_manifest(manifest, feasibility):
        print(json.dumps({"status": "FAIL", "error_code": "prerequisite_failed"}))
        return 3
    execution = execute_query_validation(
        manifest,
        transport_factory(),
        output_root=args.output_root,
        capacity_manifest_hash=content_sha256(manifest),
        feasibility_hash=content_sha256(feasibility),
        compliance_hash=str(feasibility["decision_basis_sha256"]),
        run_id=str(uuid4()),
    )
    print(json.dumps({
        "status": execution.status,
        "run_id": execution.run_id,
        "error_code": execution.error_code,
    }, sort_keys=True))
    return execution.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
