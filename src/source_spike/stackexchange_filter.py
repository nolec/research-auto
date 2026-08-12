from __future__ import annotations

import json
from hashlib import sha256
from typing import Mapping, Sequence


REQUIRED_FIELDS = (
    ".backoff", ".error_id", ".error_message", ".error_name", ".has_more", ".items",
    ".quota_max", ".quota_remaining", "question.body", "question.content_license",
    "question.creation_date", "question.link", "question.owner", "question.question_id",
    "question.tags", "question.title", "shallow_user.user_id",
)


def included_fields_sha256(fields: Sequence[str]) -> str:
    canonical = json.dumps(sorted(fields), ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def validate_frozen_filter(value: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if value.get("api_version") != "2.3":
        errors.append("api_version must equal 2.3")
    if not isinstance(value.get("filter_id"), str) or not value.get("filter_id"):
        errors.append("filter_id must be non-empty")
    if value.get("filter_type") != "safe":
        errors.append("filter_type must equal safe")
    fields = value.get("included_fields")
    if not isinstance(fields, list) or any(not isinstance(field, str) for field in fields):
        errors.append("included_fields must be a string array")
    elif tuple(sorted(fields)) != tuple(sorted(REQUIRED_FIELDS)):
        errors.append("included_fields must exactly match the frozen field set")
    elif value.get("included_fields_sha256") != included_fields_sha256(fields):
        errors.append("included_fields_sha256 mismatch")
    for key in ("created_at", "verified_at"):
        if not isinstance(value.get(key), str) or not value.get(key):
            errors.append(f"{key} must be non-empty")
    return errors
