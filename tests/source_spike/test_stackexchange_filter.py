from __future__ import annotations

from src.source_spike.stackexchange_filter import validate_frozen_filter


FIELDS = [
    ".backoff", ".error_id", ".error_message", ".error_name", ".has_more", ".items",
    ".quota_max", ".quota_remaining", "question.body", "question.content_license",
    "question.creation_date", "question.link", "question.owner", "question.question_id",
    "question.tags", "question.title", "shallow_user.user_id",
]


def record() -> dict[str, object]:
    return {
        "api_version": "2.3", "filter_id": "!frozen-filter-id", "filter_type": "safe",
        "included_fields": FIELDS, "included_fields_sha256": "pending",
        "created_at": "2026-08-13T00:00:00Z", "verified_at": "2026-08-13T00:00:00Z",
    }


def test_filter_requires_safe_exact_fields_and_matching_hash() -> None:
    value = record()
    errors = validate_frozen_filter(value)
    assert errors == ["included_fields_sha256 mismatch"]
    value["filter_type"] = "unsafe"
    assert any("filter_type" in error for error in validate_frozen_filter(value))
    value["included_fields"] = FIELDS[:-1]
    assert any("included_fields" in error for error in validate_frozen_filter(value))
