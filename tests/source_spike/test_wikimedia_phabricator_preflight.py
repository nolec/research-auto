from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.source_spike.wikimedia_phabricator_preflight import (
    PreflightLimits,
    StaticResponse,
    execute_preflight,
    validate_preflight_receipt,
)


NOW = datetime(2026, 8, 19, 13, 0, tzinfo=timezone.utc)


def response_payload(*, missing_author: bool = False, extra_root: bool = False) -> bytes:
    fields = {
        "name": "Example task text must never enter the receipt",
        "dateCreated": 1787140000,
        "authorPHID": None if missing_author else "PHID-USER-secret-value",
        "policy": {"view": "public"},
    }
    payload = {
        "result": {
            "data": [{"id": 123, "phid": "PHID-TASK-secret-value", "fields": fields}],
            "maps": {},
            "query": {"queryKey": None},
            "cursor": {"limit": 5, "after": "opaque-secret-cursor", "before": None},
        },
        "error_code": None,
        "error_info": None,
    }
    if extra_root:
        payload["unexpected"] = "must fail closed"
    return json.dumps(payload).encode()


def test_pass_receipt_contains_only_aggregate_shape_evidence() -> None:
    receipt = execute_preflight(
        api_response=StaticResponse(200, response_payload()),
        canonical_responses=[StaticResponse(200, b"")],
        limits=PreflightLimits(),
        clock=lambda: NOW,
    )

    assert receipt["status"] == "PASS"
    assert receipt["observed_task_count"] == 1
    assert receipt["completeness"] == {
        "task_id": 1.0,
        "created_timestamp": 1.0,
        "author_phid": 1.0,
        "public_visibility": 1.0,
    }
    assert receipt["request_count"] == 2
    assert validate_preflight_receipt(receipt) == []
    encoded = json.dumps(receipt)
    for forbidden in (
        "Example task text",
        "PHID-USER-secret-value",
        "PHID-TASK-secret-value",
        "opaque-secret-cursor",
        "queryKey",
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    ("status_code", "body", "reason"),
    [
        (401, b"{}", "authentication_required"),
        (403, b"{}", "authentication_required"),
        (200, response_payload(missing_author=True), "required_field_incomplete"),
        (200, response_payload(extra_root=True), "unexpected_wrapper"),
        (200, b"not-json", "malformed_response"),
    ],
)
def test_api_failures_are_fail_closed(status_code: int, body: bytes, reason: str) -> None:
    receipt = execute_preflight(
        api_response=StaticResponse(status_code, body),
        canonical_responses=[],
        limits=PreflightLimits(),
        clock=lambda: NOW,
    )

    assert receipt["status"] == "FAIL"
    assert receipt["termination_reason"] == reason
    assert validate_preflight_receipt(receipt) == []


def test_canonical_anonymous_read_is_required() -> None:
    receipt = execute_preflight(
        api_response=StaticResponse(200, response_payload()),
        canonical_responses=[StaticResponse(403, b"")],
        limits=PreflightLimits(),
        clock=lambda: NOW,
    )

    assert receipt["status"] == "FAIL"
    assert receipt["termination_reason"] == "canonical_anonymous_read_failed"


def test_conduit_session_error_is_classified_as_authentication_required() -> None:
    body = json.dumps(
        {
            "result": None,
            "error_code": "ERR-INVALID-SESSION",
            "error_info": "sensitive server message must not enter the receipt",
        }
    ).encode()

    receipt = execute_preflight(
        api_response=StaticResponse(200, body),
        canonical_responses=[],
        limits=PreflightLimits(),
        clock=lambda: NOW,
    )

    assert receipt["status"] == "FAIL"
    assert receipt["termination_reason"] == "authentication_required"
    assert "sensitive server message" not in json.dumps(receipt)


def test_byte_budget_and_zero_request_pass_are_rejected() -> None:
    oversized = execute_preflight(
        api_response=StaticResponse(200, response_payload()),
        canonical_responses=[],
        limits=PreflightLimits(max_response_bytes=10),
        clock=lambda: NOW,
    )
    assert oversized["termination_reason"] == "response_byte_budget_exhausted"

    receipt = execute_preflight(
        api_response=None,
        canonical_responses=[],
        limits=PreflightLimits(),
        clock=lambda: NOW,
    )
    assert receipt["status"] == "FAIL"
    assert receipt["termination_reason"] == "no_request_executed"


def test_canonical_response_bytes_share_the_frozen_budget() -> None:
    receipt = execute_preflight(
        api_response=StaticResponse(200, response_payload()),
        canonical_responses=[StaticResponse(200, b"x" * 1_048_577)],
        limits=PreflightLimits(),
        clock=lambda: NOW,
    )

    assert receipt["status"] == "FAIL"
    assert receipt["termination_reason"] == "response_byte_budget_exhausted"
    assert receipt["response_bytes"] > receipt["limits"]["max_response_bytes"]


def test_receipt_validation_rejects_privacy_and_metric_tampering() -> None:
    receipt = execute_preflight(
        api_response=StaticResponse(200, response_payload()),
        canonical_responses=[StaticResponse(200, b"")],
        limits=PreflightLimits(),
        clock=lambda: NOW,
    )
    receipt["privacy"]["persisted_author_identifiers"] = 1
    receipt["completeness"]["author_phid"] = float("nan")

    errors = validate_preflight_receipt(receipt)
    assert "persisted sensitive fields must remain zero" in errors
    assert "completeness metrics must be finite" in errors


def test_receipt_validation_rejects_inconsistent_pass_evidence() -> None:
    receipt = execute_preflight(
        api_response=StaticResponse(200, response_payload()),
        canonical_responses=[StaticResponse(200, b"")],
        limits=PreflightLimits(),
        clock=lambda: NOW,
    )
    receipt["shape"] = {
        "wrapper_exact": False,
        "cursor_present": False,
        "cursor_after_key_present": False,
    }
    receipt["canonical_checks"] = 0
    receipt["canonical_successes"] = 0
    receipt["request_count"] = 2

    errors = validate_preflight_receipt(receipt)

    assert "PASS requires exact wrapper and cursor shape" in errors
    assert "PASS requires one canonical check per observed task" in errors
    assert "request count must equal API plus canonical checks" in errors
