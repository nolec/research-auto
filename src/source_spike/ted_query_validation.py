from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence, cast

from src.source_spike.adapters.ted_http import (
    TedTransportFailure,
    TedTransportSuccess,
)
from src.source_spike.ted_capacity import TedRunBudget


QUERY_GENERATOR_VERSION = "1.0.0"
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
    )
