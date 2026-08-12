from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence, cast

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER
from src.source_spike.protocol import content_sha256


_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas/github-analysis-manifest.schema.json"
_VALIDATOR = Draft202012Validator(
    json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FORMAT_CHECKER
)


def validate_github_analysis_manifest(
    manifest: Mapping[str, object], compliance_record: Mapping[str, object]
) -> list[str]:
    schema_errors = sorted(
        _VALIDATOR.iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if schema_errors:
        return [
            f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
            for error in schema_errors
        ]

    errors: list[str] = []
    repositories = cast(Sequence[Mapping[str, object]], manifest["repositories"])
    names = [str(value["name"]).casefold() for value in repositories]
    archetypes = [str(value["archetype"]) for value in repositories]
    if any(count > 1 for count in Counter(names).values()):
        errors.append("repositories must be unique")
    if any(count > 1 for count in Counter(archetypes).values()):
        errors.append("archetypes must be unique")
    quota_total = sum(int(value["quota"]) for value in repositories)
    if quota_total != int(manifest["target_valid_records"]):
        errors.append("repository quotas must total target_valid_records")
    if content_sha256(compliance_record) != manifest["compliance_hash"]:
        errors.append("compliance hash mismatch")
    elif compliance_record.get("source") != manifest["source"]:
        errors.append("compliance source mismatch")
    elif compliance_record.get("decision") != manifest["compliance_decision"]:
        errors.append("compliance decision mismatch")
    request = cast(Mapping[str, object], manifest["request"])
    retry = cast(Mapping[str, object], manifest["retry"])
    if int(request["max_http_attempts"]) < int(request["max_requests"]):
        errors.append("max_http_attempts cannot be less than max_requests")
    if float(retry["base_backoff_seconds"]) > float(retry["max_backoff_seconds"]):
        errors.append("base_backoff_seconds cannot exceed max_backoff_seconds")
    return errors
