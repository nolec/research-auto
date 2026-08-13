from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence, cast

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER
from src.source_spike.protocol import content_sha256


_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas/stackexchange-capacity-manifest.schema.json").read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FORMAT_CHECKER)


def required_capacity(quota: int, multiplier: float) -> int:
    if quota < 1 or multiplier < 1:
        raise ValueError("capacity inputs must be positive and multiplier at least one")
    return math.ceil(quota * multiplier)


def validate_stackexchange_capacity_manifest(manifest: Mapping[str, object], analysis: Mapping[str, object], compliance: Mapping[str, object], filter_record: Mapping[str, object]) -> list[str]:
    errors = [f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}" for error in sorted(_VALIDATOR.iter_errors(manifest), key=lambda value: tuple(map(str, value.absolute_path)))]
    if errors:
        return errors
    sites = cast(Sequence[Mapping[str, object]], manifest["sites"])
    if any(count > 1 for count in Counter(str(site["name"]) for site in sites).values()): errors.append("sites must be unique")
    expected = required_capacity(int(manifest["analysis_quota_per_site"]), float(manifest["capacity_multiplier"]))
    if int(manifest["required_valid_per_site"]) != expected or any(int(site["quota"]) != expected for site in sites): errors.append("site capacity quota mismatch")
    if sum(int(site["quota"]) for site in sites) != int(manifest["target_valid_records"]): errors.append("site quotas must total target_valid_records")
    if content_sha256(analysis) != manifest["analysis_manifest_hash"]: errors.append("analysis manifest hash mismatch")
    if content_sha256(compliance) != manifest["compliance_hash"]: errors.append("compliance hash mismatch")
    if content_sha256(filter_record) != manifest["filter_hash"]: errors.append("filter hash mismatch")
    if manifest["published_after"] != analysis["published_after"] or manifest["published_before"] != analysis["published_before"]: errors.append("capacity window must match analysis window")
    after=datetime.fromisoformat(str(manifest["published_after"]).replace("Z","+00:00")); before=datetime.fromisoformat(str(manifest["published_before"]).replace("Z","+00:00"))
    if not 89 <= (before-after).total_seconds()/86400 <= 91: errors.append("published window must be 90 days")
    request=cast(Mapping[str,object],manifest["request"]); retry=cast(Mapping[str,object],manifest["retry"])
    if int(request["max_http_attempts"]) < int(request["max_requests"]): errors.append("max_http_attempts cannot be less than max_requests")
    if float(retry["base_backoff_seconds"]) > float(retry["max_backoff_seconds"]): errors.append("base_backoff_seconds cannot exceed max_backoff_seconds")
    return errors
