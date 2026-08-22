from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence, cast

from jsonschema import Draft202012Validator

from src.source_spike.protocol import content_sha256
from src.source_spike.ted_query_validation import build_query_set


_ROOT = Path(__file__).resolve().parents[2]
_VALIDATOR = Draft202012Validator(json.loads((_ROOT / "schemas/ted-analysis-manifest.schema.json").read_text()))
_STRATA = (("software_and_information_systems", "48", 25), ("business_services", "79", 25), ("health_and_social_services", "85", 25), ("repair_and_maintenance_services", "50", 25))
_REQUEST = {"page_size": 100, "max_pages_per_stratum": 3, "max_logical_requests": 12, "max_http_attempts": 24, "deadline_seconds": 180, "max_response_bytes": 31457280, "request_timeout_seconds": 10}
_RETRY = {"max_retries_per_logical_request": 1, "base_backoff_seconds": 1, "max_backoff_seconds": 4}
_PRIVACY = {"redaction_placeholder": "[REDACTED_CONTACT]", "persist_raw_payloads": False, "persist_raw_buyer_ids": False, "persist_contact_text": False}


def validate_ted_analysis_manifest(manifest: Mapping[str, object], capacity: Mapping[str, object]) -> list[str]:
    errors = [f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}" for error in _VALIDATOR.iter_errors(manifest)]
    strata = cast(Sequence[Mapping[str, object]], manifest.get("strata", []))
    if tuple((value.get("name"), value.get("cpv_prefix"), value.get("quota")) for value in strata) != _STRATA: errors.append("analysis strata mismatch")
    capacity_strata = cast(Sequence[Mapping[str, object]], capacity.get("strata", []))
    if tuple((value.get("name"), value.get("cpv_prefix")) for value in strata) != tuple((value.get("name"), value.get("cpv_prefix")) for value in capacity_strata): errors.append("capacity stratum identity mismatch")
    if manifest.get("request") != _REQUEST: errors.append("analysis request budget mismatch")
    if manifest.get("retry") != _RETRY: errors.append("analysis retry policy mismatch")
    if manifest.get("privacy") != _PRIVACY: errors.append("analysis privacy policy mismatch")
    if manifest.get("retention") != {"trigger": "source_spike_closed", "days_after_trigger": 30}: errors.append("retention policy mismatch")
    if manifest.get("target_valid_records") != 100 or manifest.get("max_items_per_buyer") != 2: errors.append("analysis target policy mismatch")
    for field in ("window", "fields"):
        if manifest.get(field) != capacity.get(field): errors.append(f"capacity {field} mismatch")
    if manifest.get("capacity_manifest_hash") != content_sha256(capacity): errors.append("capacity manifest hash mismatch")
    if manifest.get("query_set_sha256") != build_query_set(capacity).query_set_sha256: errors.append("query set mismatch")
    if manifest.get("redaction_policy_version") != "ted-contact-v1" or manifest.get("language_selection_version") != "ted-language-v1" or manifest.get("compound_buyer_identity_version") != "ted-buyers-v1": errors.append("analysis policy version mismatch")
    fixture = _ROOT / "tests/fixtures/ted-contact-redaction-v1.json"
    if manifest.get("redaction_test_corpus_sha256") != sha256(fixture.read_bytes()).hexdigest(): errors.append("redaction corpus hash mismatch")
    return errors
