from __future__ import annotations

from src.source_spike.protocol import content_sha256
from src.source_spike.stackexchange_filter import REQUIRED_FIELDS, included_fields_sha256
from src.source_spike.stackexchange_smoke_manifest import validate_stackexchange_smoke_manifest


def values() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    compliance = {"source": "stackexchange", "decision": "conditional"}
    filter_record = {
        "api_version": "2.3", "filter_id": "!filter", "filter_type": "safe",
        "included_fields": list(REQUIRED_FIELDS), "included_fields_sha256": included_fields_sha256(REQUIRED_FIELDS),
        "created_at": "2026-08-13T00:00:00Z", "verified_at": "2026-08-13T00:00:00Z",
    }
    manifest = {
        "manifest_version": "0.1.0", "source": "stackexchange", "adapter_version": "0.1.0",
        "target_valid_records": 10, "max_items_per_author": 2,
        "published_after": "2026-05-15T00:00:00Z", "published_before": "2026-08-13T00:00:00Z",
        "sites": [
            {"name": "stackoverflow", "quota": 3}, {"name": "superuser", "quota": 3},
            {"name": "serverfault", "quota": 2}, {"name": "softwareengineering", "quota": 2},
        ],
        "request": {"endpoint": "/2.3/questions", "sort": "creation", "order": "desc", "page_size": 30,
                    "max_pages_total": 8, "max_requests": 12, "max_http_attempts": 18,
                    "request_timeout_seconds": 10, "max_total_elapsed_seconds": 60,
                    "max_backoff_wait_seconds": 10, "quota_reserve": 100},
        "retry": {"max_retries": 2, "base_backoff_seconds": 1, "max_backoff_seconds": 8},
        "filter_ref": "stackexchange-filter.json", "filter_hash": content_sha256(filter_record),
        "compliance_ref": "compliance/stackexchange.json", "compliance_hash": content_sha256(compliance),
        "compliance_decision": "conditional",
    }
    return manifest, compliance, filter_record


def test_manifest_freezes_four_coverage_strata_filter_and_ninety_day_window() -> None:
    manifest, compliance, filter_record = values()
    assert validate_stackexchange_smoke_manifest(manifest, compliance, filter_record) == []
    manifest["sites"] = list(manifest["sites"])[:-1]
    assert any("quota" in error for error in validate_stackexchange_smoke_manifest(manifest, compliance, filter_record))
