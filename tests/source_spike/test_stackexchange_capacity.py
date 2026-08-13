from __future__ import annotations

import json
from types import SimpleNamespace

from src.source_spike.adapters.base import SegmentResult
from src.source_spike.stackexchange_capacity import build_capacity_receipt, capacity_summary, validate_capacity_receipt


def test_capacity_summary_requires_thirty_eight_per_site_and_contains_no_items() -> None:
    value = capacity_summary({"stackoverflow": 39, "superuser": 38, "serverfault": 37, "softwareengineering": 60})
    assert value["passed"] is False
    assert value["sites"]["serverfault"]["capacity_pass"] is False
    assert "items" not in value and "text" not in str(value)


def test_capacity_receipt_is_hash_bound_and_privacy_safe() -> None:
    receipt = {
        "schema_version": 1,
        "status": "PASS",
        "capacity_manifest_hash": "a" * 64,
        "analysis_manifest_hash": "b" * 64,
        "compliance_hash": "c" * 64,
        "filter_hash": "d" * 64,
        "required_per_site": 38,
        "retained_items": 0,
        "sites": {
            site: {
                "fetched": 50, "processed": 45, "accepted": 38, "rejected": 7,
                "rejection_reason_counts": {"short_text": 7}, "capacity_pass": True,
            }
            for site in ("stackoverflow", "superuser", "serverfault", "softwareengineering")
        },
        "transport": {"requests": 4, "attempts": 4, "retries": 0, "backoffs": 0, "quota_remaining": 250},
    }
    assert validate_capacity_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        analysis_manifest_hash="b" * 64,
        compliance_hash="c" * 64,
        filter_hash="d" * 64,
    ) == []
    assert not any(key in json.dumps(receipt) for key in ("author_hash", "source_url", "question_id", "raw payload"))


def test_capacity_receipt_rejects_nested_shape_arithmetic_and_metric_types() -> None:
    hashes = dict(capacity_manifest_hash="a" * 64, analysis_manifest_hash="b" * 64, compliance_hash="c" * 64, filter_hash="d" * 64)
    base = {
        "schema_version": 1, "status": "PASS", **hashes, "required_per_site": 38, "retained_items": 0,
        "sites": {site: {"fetched": 50, "processed": 45, "accepted": 38, "rejected": 7, "rejection_reason_counts": {"short_text": 7}, "capacity_pass": True} for site in ("stackoverflow", "superuser", "serverfault", "softwareengineering")},
        "transport": {"requests": 4, "attempts": 4, "retries": 0, "backoffs": 0, "quota_remaining": 250},
    }
    assert validate_capacity_receipt(base, **hashes) == []
    malformed = json.loads(json.dumps(base)); malformed["sites"]["stackoverflow"]["processed"] = 46
    malformed["transport"]["requests"] = True
    errors = validate_capacity_receipt(malformed, **hashes)
    assert "capacity receipt site arithmetic mismatch: stackoverflow" in errors
    assert "capacity receipt transport metric invalid: requests" in errors


def test_capacity_receipt_rejects_inconsistent_transport_arithmetic() -> None:
    hashes = dict(capacity_manifest_hash="a" * 64, analysis_manifest_hash="b" * 64, compliance_hash="c" * 64, filter_hash="d" * 64)
    receipt = {
        "schema_version": 1, "status": "PASS", **hashes, "required_per_site": 38, "retained_items": 0,
        "sites": {site: {"fetched": 38, "processed": 38, "accepted": 38, "rejected": 0, "rejection_reason_counts": {}, "capacity_pass": True} for site in ("stackoverflow", "superuser", "serverfault", "softwareengineering")},
        "transport": {"requests": 4, "attempts": 7, "retries": 0, "backoffs": 0, "quota_remaining": 250},
    }

    assert "capacity receipt transport arithmetic mismatch" in validate_capacity_receipt(receipt, **hashes)


def test_capacity_receipt_fails_when_an_expected_site_segment_is_missing() -> None:
    sites = ("stackoverflow", "superuser", "serverfault", "softwareengineering")
    result = SimpleNamespace(
        items=tuple({"community": site} for site in sites for _ in range(38)), invalid_items=(),
        segment_results=tuple(SegmentResult("site", site, 38, 38, 38, 38, 0) for site in sites[:-1]),
        request_count=4, http_attempt_count=4, retry_count=0, rate_limit_events=0,
    )
    receipt = build_capacity_receipt(
        result, manifest={}, analysis={}, compliance={}, filter_record={}, quota_remaining=200
    )

    assert receipt["status"] == "FAIL"
    assert receipt["sites"]["softwareengineering"]["capacity_pass"] is False
