from __future__ import annotations

from typing import Mapping, Sequence, cast

from src.source_spike.protocol import content_sha256
from src.source_spike.ted_query_validation import build_query_set


_QUOTAS = (("48", 3), ("79", 3), ("85", 2), ("50", 2))
_REQUEST = {"page_size": 100, "max_pages_per_stratum": 2, "max_logical_requests": 8, "max_http_attempts": 16, "deadline_seconds": 45, "max_response_bytes": 10485760, "request_timeout_seconds": 10}


def validate_ted_smoke_manifest(manifest: Mapping[str, object], authorization: Mapping[str, object], capacity: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if manifest.get("manifest_version") != "1.0.0" or manifest.get("source") != "ted": errors.append("manifest identity mismatch")
    if manifest.get("target_valid_records") != 10: errors.append("target must equal 10")
    strata = cast(Sequence[Mapping[str, object]], manifest.get("strata", []))
    if tuple((x.get("cpv_prefix"), x.get("quota")) for x in strata) != _QUOTAS: errors.append("stratum quota mismatch")
    capacity_strata = cast(Sequence[Mapping[str, object]], capacity.get("strata", []))
    if tuple((x.get("name"), x.get("cpv_prefix")) for x in strata) != tuple((x.get("name"), x.get("cpv_prefix")) for x in capacity_strata): errors.append("stratum query identity mismatch")
    if manifest.get("request") != _REQUEST: errors.append("request budget mismatch")
    for field in ("capacity_manifest_hash", "feasibility_hash", "compliance_hash", "query_set_sha256"):
        if manifest.get(field) != authorization.get(field): errors.append(f"{field} authorization mismatch")
    if manifest.get("capacity_manifest_hash") != content_sha256(capacity): errors.append("capacity manifest hash mismatch")
    if manifest.get("query_set_sha256") != build_query_set(capacity).query_set_sha256: errors.append("query set mismatch")
    if manifest.get("fields") != capacity.get("fields"): errors.append("field allowlist mismatch")
    if manifest.get("window") != capacity.get("window"): errors.append("window mismatch")
    if manifest.get("max_items_per_buyer") != 2: errors.append("buyer limit mismatch")
    if manifest.get("canonical_url_template") != "https://ted.europa.eu/en/notice/-/detail/{publication-number}": errors.append("canonical URL template mismatch")
    return errors
