from __future__ import annotations

import json
import math
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Mapping, Sequence, cast

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER
from src.source_spike.protocol import content_sha256


_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas/ted-capacity-manifest.schema.json").read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FORMAT_CHECKER)
_STRATA = (
    ("software_and_information_systems", 1, "48"),
    ("business_services", 2, "79"),
    ("health_and_social_services", 3, "85"),
    ("repair_and_maintenance_services", 4, "50"),
)
_SORT = (
    {"field": "publication-date", "direction": "DESC"},
    {"field": "publication-number", "direction": "ASC"},
)
_WINDOW = {
    "published_from": "2026-05-20T00:00:00Z",
    "published_before": "2026-08-18T00:00:00Z",
    "query_from_date": "20260520",
    "query_to_date": "20260817",
    "from_inclusive": True,
    "before_exclusive": True,
}
_FIELDS = (
    "publication-number",
    "notice-identifier",
    "procedure-identifier",
    "publication-date",
    "notice-type",
    "form-type",
    "classification-cpv",
    "buyer-identifier",
    "notice-title",
    "description-proc",
    "change-notice-version-identifier",
)
_FORBIDDEN_CONTACT_FIELDS = (
    "buyer-contact-point",
    "buyer-email",
    "buyer-tel",
    "buyer-touchpoint-contact-point",
    "buyer-touchpoint-email",
    "buyer-touchpoint-tel",
)
_THRESHOLDS = {
    "procedure_completeness_min": 0.95,
    "buyer_completeness_min": 0.8,
    "text_completeness_min": 0.8,
    "acceptance_yield_min": 0.25,
    "processed_max_per_stratum": 300,
}
_PAGINATION = {
    "page_size": 100,
    "max_logical_requests_per_stratum": 3,
    "max_logical_requests_total": 12,
    "max_attempts_per_logical_request": 2,
    "max_http_attempts_total": 24,
    "request_timeout_seconds": 10,
    "deadline_seconds": 60,
    "max_response_bytes_total": 10485760,
}
_RETRY = {
    "retryable_statuses": [429, 502, 503, 504],
    "max_retries_per_logical_request": 1,
    "base_backoff_seconds": 1,
    "max_backoff_seconds": 4,
}
_QUERY_KEYS = (
    "api", "window", "notice_scope", "fields", "forbidden_contact_fields",
    "sort", "strata", "thresholds", "pagination", "retry", "privacy",
)


def required_capacity(quota: int, multiplier: float) -> int:
    if quota < 1 or multiplier < 1:
        raise ValueError("capacity inputs must be positive and multiplier at least one")
    return math.ceil(quota * multiplier)


def allocation_sha256(allocation: Mapping[str, object]) -> str:
    return content_sha256(allocation)


def window_sha256(window: Mapping[str, object]) -> str:
    return content_sha256(window)


def query_contract_sha256(manifest: Mapping[str, object]) -> str:
    return content_sha256({key: manifest[key] for key in _QUERY_KEYS})


def _expected_query(manifest: Mapping[str, object], cpv_prefix: str) -> str:
    window = cast(Mapping[str, object], manifest["window"])
    scope = cast(Mapping[str, object], manifest["notice_scope"])
    notice_types = " ".join(cast(Sequence[str], scope["allowed_notice_types"]))
    return (
        f"publication-date = ({window['query_from_date']} <> {window['query_to_date']}) "
        f"AND form-type = {scope['form_type']} AND notice-type IN ({notice_types}) "
        f"AND classification-cpv = {cpv_prefix}*"
    )


def validate_ted_capacity_manifest(
    manifest: Mapping[str, object], feasibility: Mapping[str, object]
) -> list[str]:
    errors = [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in sorted(
            _VALIDATOR.iter_errors(manifest),
            key=lambda value: tuple(map(str, value.absolute_path)),
        )
    ]
    if errors:
        return errors

    if (
        feasibility.get("status") != "PASS"
        or cast(Mapping[str, object], feasibility.get("eligibility", {})).get("current_collection") != "PASS"
        or feasibility.get("next_action") != "probe_capacity"
        or feasibility.get("operational_next_action") != "probe_capacity"
    ):
        errors.append("TED feasibility must route to probe_capacity")
    if content_sha256(feasibility) != manifest["feasibility_hash"]:
        errors.append("feasibility hash mismatch")

    allocation = cast(Mapping[str, object], manifest["allocation"])
    expected_capacity = required_capacity(
        int(allocation["provisional_quota_per_stratum"]),
        float(allocation["oversampling_factor"]),
    )
    if (
        int(allocation["required_unique_per_stratum"]) != expected_capacity
        or int(allocation["target_unique_total"]) != expected_capacity * len(_STRATA)
    ):
        errors.append("capacity allocation mismatch")
    if allocation_sha256(allocation) != manifest["allocation_hash"]:
        errors.append("allocation hash mismatch")

    window = cast(Mapping[str, object], manifest["window"])
    if dict(window) != _WINDOW:
        errors.append("TED frozen window mismatch")
    start = datetime.fromisoformat(str(window["published_from"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(window["published_before"]).replace("Z", "+00:00"))
    if (end - start).total_seconds() != 90 * 86400:
        errors.append("published window must be exactly 90 days")
    expected_query_from = start.strftime("%Y%m%d")
    expected_query_to = (end - timedelta(days=1)).strftime("%Y%m%d")
    if (
        start.utcoffset() != timedelta(0)
        or end.utcoffset() != timedelta(0)
        or start.timetz().replace(tzinfo=None) != time.min
        or end.timetz().replace(tzinfo=None) != time.min
        or window["query_from_date"] != expected_query_from
        or window["query_to_date"] != expected_query_to
    ):
        errors.append("query dates must match the declared exclusive window")
    if window_sha256(window) != manifest["window_hash"]:
        errors.append("window hash mismatch")

    strata = cast(Sequence[Mapping[str, object]], manifest["strata"])
    for value, (name, priority, prefix) in zip(strata, _STRATA, strict=True):
        if (
            value["name"] != name
            or int(value["priority"]) != priority
            or value["cpv_prefix"] != prefix
            or int(value["quota"]) != expected_capacity
        ):
            errors.append(f"stratum allocation mismatch: {name}")
        if value["query"] != _expected_query(manifest, prefix):
            errors.append(f"stratum query mismatch: {name}")

    if list(cast(Sequence[object], manifest["sort"])) != list(_SORT):
        errors.append("capacity sort contract mismatch")
    fields = cast(Sequence[str], manifest["fields"])
    forbidden_fields = cast(Sequence[str], manifest["forbidden_contact_fields"])
    if list(fields) != list(_FIELDS):
        errors.append("TED field allowlist mismatch")
    if list(forbidden_fields) != list(_FORBIDDEN_CONTACT_FIELDS):
        errors.append("TED forbidden contact fields mismatch")
    forbidden = set(_FORBIDDEN_CONTACT_FIELDS)
    for field in fields:
        if field in forbidden:
            errors.append(f"contact field is forbidden: {field}")

    thresholds = cast(Mapping[str, object], manifest["thresholds"])
    pagination = cast(Mapping[str, object], manifest["pagination"])
    retry = cast(Mapping[str, object], manifest["retry"])
    if dict(thresholds) != _THRESHOLDS:
        errors.append("TED thresholds contract mismatch")
    if dict(pagination) != _PAGINATION:
        errors.append("TED pagination contract mismatch")
    if dict(retry) != _RETRY:
        errors.append("TED retry contract mismatch")
    expected_logical_requests = int(pagination["max_logical_requests_per_stratum"]) * len(_STRATA)
    expected_http_attempts = (
        int(pagination["max_logical_requests_total"])
        * int(pagination["max_attempts_per_logical_request"])
    )
    if int(pagination["max_logical_requests_total"]) != expected_logical_requests:
        errors.append("logical request budget arithmetic mismatch")
    if int(pagination["max_http_attempts_total"]) != expected_http_attempts:
        errors.append("HTTP attempt budget arithmetic mismatch")
    if int(retry["max_retries_per_logical_request"]) + 1 != int(pagination["max_attempts_per_logical_request"]):
        errors.append("retry attempt budget arithmetic mismatch")
    if int(pagination["max_http_attempts_total"]) < int(pagination["max_logical_requests_total"]):
        errors.append("max_http_attempts_total cannot be less than max_logical_requests_total")
    if float(retry["base_backoff_seconds"]) > float(retry["max_backoff_seconds"]):
        errors.append("base_backoff_seconds cannot exceed max_backoff_seconds")
    if query_contract_sha256(manifest) != manifest["query_contract_hash"]:
        errors.append("query contract hash mismatch")
    return errors
