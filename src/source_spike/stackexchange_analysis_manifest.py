from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence, cast

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER
from src.source_spike.protocol import content_sha256
from src.source_spike.stackexchange_filter import validate_frozen_filter


_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas/stackexchange-analysis-manifest.schema.json").read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FORMAT_CHECKER)


def validate_stackexchange_analysis_manifest(manifest: Mapping[str, object], compliance: Mapping[str, object], filter_record: Mapping[str, object]) -> list[str]:
    errors = [f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}" for error in sorted(_VALIDATOR.iter_errors(manifest), key=lambda value: tuple(map(str, value.absolute_path)))]
    if errors:
        return errors
    sites = cast(Sequence[Mapping[str, object]], manifest["sites"])
    if any(value > 1 for value in Counter(str(site["name"]) for site in sites).values()): errors.append("sites must be unique")
    if any(value > 1 for value in Counter(str(site["stratum"]) for site in sites).values()): errors.append("strata must be unique")
    if sum(int(site["quota"]) for site in sites) != int(manifest["target_valid_records"]): errors.append("site quotas must total target_valid_records")
    after = datetime.fromisoformat(str(manifest["published_after"]).replace("Z", "+00:00")); before = datetime.fromisoformat(str(manifest["published_before"]).replace("Z", "+00:00"))
    if not 89 <= (before-after).total_seconds()/86400 <= 91: errors.append("published window must be 90 days")
    if validate_frozen_filter(filter_record) or content_sha256(filter_record) != manifest["filter_hash"]: errors.append("filter hash mismatch")
    if content_sha256(compliance) != manifest["compliance_hash"]: errors.append("compliance hash mismatch")
    elif compliance.get("source") != "stackexchange" or compliance.get("decision") != manifest["compliance_decision"]: errors.append("compliance decision mismatch")
    request=cast(Mapping[str,object],manifest["request"]); retry=cast(Mapping[str,object],manifest["retry"])
    if int(request["max_http_attempts"]) < int(request["max_requests"]): errors.append("max_http_attempts cannot be less than max_requests")
    if float(retry["base_backoff_seconds"]) > float(retry["max_backoff_seconds"]): errors.append("base_backoff_seconds cannot exceed max_backoff_seconds")
    return errors
