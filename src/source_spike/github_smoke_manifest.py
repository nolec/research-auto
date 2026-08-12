from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence, cast

from jsonschema import Draft202012Validator

from src.source_spike.protocol import content_sha256


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "schemas"
    / "github-smoke-manifest.schema.json"
)
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))


def validate_github_smoke_manifest(
    manifest: Mapping[str, object], compliance_record: Mapping[str, object]
) -> list[str]:
    schema_errors = sorted(
        _VALIDATOR.iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if schema_errors:
        return [
            f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: "
            f"{error.message}"
            for error in schema_errors
        ]

    errors: list[str] = []
    repositories = cast(Sequence[Mapping[str, object]], manifest["repositories"])
    names = [str(repository["name"]).casefold() for repository in repositories]
    if any(count > 1 for count in Counter(names).values()):
        errors.append("repositories must be unique")

    quota_total = sum(int(repository["quota"]) for repository in repositories)
    target = int(manifest["target_valid_records"])
    if quota_total != target:
        errors.append(
            "repository quotas must total target_valid_records "
            f"({quota_total} != {target})"
        )

    if content_sha256(compliance_record) != manifest["compliance_hash"]:
        errors.append("compliance hash mismatch")
    elif compliance_record.get("source") != manifest["source"]:
        errors.append("compliance source mismatch")
    elif compliance_record.get("decision") != manifest["compliance_decision"]:
        errors.append("compliance decision mismatch")

    request = cast(Mapping[str, object], manifest["request"])
    retry = cast(Mapping[str, object], manifest["retry"])
    if int(retry["max_retries"]) >= int(request["max_requests"]):
        errors.append("max_retries must be less than max_requests")
    if float(retry["base_backoff_seconds"]) > float(
        retry["max_backoff_seconds"]
    ):
        errors.append("base_backoff_seconds cannot exceed max_backoff_seconds")
    return errors
