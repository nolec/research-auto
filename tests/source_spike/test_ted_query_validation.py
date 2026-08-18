from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.source_spike.adapters.ted_http import (
    TedPage,
    TedTransportFailure,
    TedTransportSuccess,
)
from src.source_spike.ted_query_validation import (
    build_query_set,
    run_query_validation,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/source-spike/ted-capacity.json"


def manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def success(page: int = 1) -> TedTransportSuccess:
    return TedTransportSuccess(
        TedPage((), 0, page, False, "a" * 64, None),
        http_attempt_count=1,
        retry_count=0,
        response_bytes=100,
    )


class RecordingTransport:
    def __init__(self, results: list[object] | None = None) -> None:
        self.results = iter(results or [success(), success(), success(), success()])
        self.calls: list[dict[str, object]] = []

    def validate_query_syntax(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return next(self.results)


def test_query_set_is_deterministic_and_contains_frozen_sort_order() -> None:
    first = build_query_set(manifest())
    second = build_query_set(manifest())

    assert first == second
    assert [candidate.stratum for candidate in first.candidates] == [
        "software_and_information_systems",
        "business_services",
        "health_and_social_services",
        "repair_and_maintenance_services",
    ]
    assert all(
        candidate.query.endswith(
            " SORT BY publication-date DESC, publication-number ASC"
        )
        for candidate in first.candidates
    )
    assert len(first.query_set_sha256) == 64
    assert all(len(candidate.query_sha256) == 64 for candidate in first.candidates)


def test_query_generator_rejects_sort_or_stratum_drift() -> None:
    sort_drift = manifest()
    sort_drift["sort"] = [
        {"field": "publication-number", "direction": "ASC"},
        {"field": "publication-date", "direction": "DESC"},
    ]
    with pytest.raises(ValueError, match="sort contract"):
        build_query_set(sort_drift)

    stratum_drift = manifest()
    strata = copy.deepcopy(stratum_drift["strata"])
    assert isinstance(strata, list)
    strata.pop()
    stratum_drift["strata"] = strata
    with pytest.raises(ValueError, match="strata contract"):
        build_query_set(stratum_drift)


def test_validation_checks_all_strata_with_separate_bounded_contract() -> None:
    transport = RecordingTransport()

    result = run_query_validation(manifest(), transport)

    assert result.status == "PASS"
    assert result.termination_reason == "validated"
    assert result.logical_requests == 4
    assert result.http_attempts == 4
    assert result.response_bytes == 400
    assert len(result.strata) == 4
    assert all(outcome.syntax_valid for outcome in result.strata)
    assert all("query" not in outcome.__dict__ for outcome in result.strata)
    assert all(call["max_http_attempts"] <= 2 for call in transport.calls)
    assert all(call["deadline_seconds"] <= 30 for call in transport.calls)
    assert all(call["max_response_bytes"] <= 2_097_152 for call in transport.calls)


def test_partial_failure_fails_closed_without_validating_later_strata() -> None:
    transport = RecordingTransport(
        [
            success(),
            TedTransportFailure("malformed_wrapper", 1, 0, 50),
            success(),
            success(),
        ]
    )

    result = run_query_validation(manifest(), transport)

    assert result.status == "FAIL"
    assert result.termination_reason == "malformed_wrapper"
    assert result.logical_requests == 2
    assert len(result.strata) == 2
    assert result.strata[-1].syntax_valid is False
    assert len(transport.calls) == 2


def test_global_attempt_budget_stops_before_next_query() -> None:
    retried = TedTransportSuccess(
        TedPage((), 0, 1, False, "b" * 64, None),
        http_attempt_count=2,
        retry_count=1,
        response_bytes=100,
    )
    transport = RecordingTransport([retried, retried, retried, retried])

    result = run_query_validation(
        manifest(), transport, max_http_attempts=3
    )

    assert result.status == "FAIL"
    assert result.termination_reason == "attempt_budget_exhausted"
    assert result.logical_requests == 2
    assert result.http_attempts == 4
    assert len(transport.calls) == 2
