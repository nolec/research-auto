from __future__ import annotations

import json
import os
import re
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER
from src.source_spike.review_packet import validate_review_packet_bundle


_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas/blind-source-label.schema.json").read_text(encoding="utf-8")
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FORMAT_CHECKER)
_CANONICAL_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas/source-label.schema.json").read_text(encoding="utf-8")
)
_CANONICAL_VALIDATOR = Draft202012Validator(
    _CANONICAL_SCHEMA, format_checker=FORMAT_CHECKER
)
_IDENTITY_PATTERNS = (
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(r"(?<!\w)@[A-Za-z0-9_-]+"),
    re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+(?=/|\s|$)", re.IGNORECASE),
)


def validate_blind_submission(value: Mapping[str, object]) -> list[str]:
    errors = sorted(
        _VALIDATOR.iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    messages = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in errors
    ]
    reason = value.get("label_reason")
    if isinstance(reason, str) and any(pattern.search(reason) for pattern in _IDENTITY_PATTERNS):
        messages.append("label_reason contains a prohibited identity pattern")
    return messages


def _canonical(
    submission: Mapping[str, object], assignment: Mapping[str, object], round_name: str
) -> dict[str, object]:
    label_id = sha256(
        f"{submission['assignment_id']}\0{submission['reviewer_id']}\0{round_name}".encode()
    ).hexdigest()
    value = {
        "label_id": label_id,
        "document_id": assignment["document_id"],
        "source": assignment["source"],
        "reviewer_id": submission["reviewer_id"],
        "assignment_split": assignment["split"],
        "review_round": round_name,
        "problem_signal": submission["problem_signal"],
        "money_signal": submission["money_signal"],
        "money_signal_type": submission["money_signal_type"],
        "structural_money_signal": submission["structural_money_signal"],
        "usable_evidence": submission["usable_evidence"],
        "noise": submission["noise"],
        "label_reason": submission["label_reason"],
        "labeled_at": submission["labeled_at"],
        "guide_version": "1.0.0",
    }
    errors = list(_CANONICAL_VALIDATOR.iter_errors(value))
    if errors:
        raise ValueError(f"canonical source label is invalid: {errors[0].message}")
    return value


def ingest_submissions(
    review_root: Path,
    *,
    primary: list[Mapping[str, object]],
    secondary: list[Mapping[str, object]],
) -> dict[str, int]:
    validate_review_packet_bundle(review_root)
    mapping_values = json.loads(
        (review_root / "internal/assignment-map.json").read_text(encoding="utf-8")
    )
    assignments = {value["assignment_id"]: value for value in mapping_values}
    expected_primary = set(assignments)
    expected_secondary = {
        key for key, value in assignments.items() if value["requires_second_review"]
    }

    def indexed(values: list[Mapping[str, object]], *, name: str) -> dict[str, Mapping[str, object]]:
        result: dict[str, Mapping[str, object]] = {}
        for value in values:
            errors = validate_blind_submission(value)
            if errors:
                raise ValueError(f"invalid {name} submission: {'; '.join(errors)}")
            assignment_id = str(value["assignment_id"])
            if assignment_id in result:
                raise ValueError(f"duplicate {name} assignment: {assignment_id}")
            result[assignment_id] = value
        return result

    primary_by_id = indexed(primary, name="primary")
    secondary_by_id = indexed(secondary, name="secondary")
    if set(primary_by_id) != expected_primary:
        raise ValueError("primary assignments must exactly match the frozen packet")
    if set(secondary_by_id) != expected_secondary:
        raise ValueError("secondary assignments must exactly match the frozen packet")
    for assignment_id, secondary_value in secondary_by_id.items():
        if secondary_value["reviewer_independence_asserted"] is not True:
            raise ValueError("secondary reviewer independence must be asserted")
        if secondary_value["reviewer_id"] == primary_by_id[assignment_id]["reviewer_id"]:
            raise ValueError("secondary reviewer independence requires a different reviewer_id")

    canonical: list[dict[str, object]] = []
    canonical.extend(
        _canonical(value, assignments[assignment_id], "primary")
        for assignment_id, value in primary_by_id.items()
    )
    canonical.extend(
        _canonical(value, assignments[assignment_id], "secondary")
        for assignment_id, value in secondary_by_id.items()
    )
    development = [value for value in canonical if value["assignment_split"] == "development"]
    holdout = [value for value in canonical if value["assignment_split"] == "holdout"]
    audit = []
    for round_name, values in (("primary", primary_by_id), ("secondary", secondary_by_id)):
        for assignment_id, submission in values.items():
            audit.append({
                "label_id": sha256(
                    f"{assignment_id}\0{submission['reviewer_id']}\0{round_name}".encode()
                ).hexdigest(),
                "assignment_id": assignment_id,
                "reviewer_id": submission["reviewer_id"],
                "review_round": round_name,
                "external_context_used": submission["external_context_used"],
                "reviewer_independence_asserted": submission["reviewer_independence_asserted"],
            })
    labels_root = review_root / "labels"
    temporary = review_root / ".labels.tmp"
    if labels_root.exists() or temporary.exists():
        raise ValueError("canonical label artifacts already exist")
    try:
        (temporary / "development").mkdir(parents=True)
        (temporary / "holdout-sealed").mkdir()
        for path, values in (
            (temporary / "development/canonical-labels.jsonl", development),
            (temporary / "holdout-sealed/canonical-labels.jsonl", holdout),
        ):
            path.write_text(
                "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values),
                encoding="utf-8",
            )
        ingestion_manifest = {
            "primary_count": len(primary),
            "secondary_count": len(secondary),
            "secondary_independence_asserted": sum(
                value["reviewer_independence_asserted"] is True for value in secondary
            ),
            "external_context_used": {
                "primary": sum(value["external_context_used"] is True for value in primary),
                "secondary": sum(value["external_context_used"] is True for value in secondary),
            },
        }
        audit_path = temporary / "review-audit.jsonl"
        audit_path.write_text(
            "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in audit),
            encoding="utf-8",
        )
        ingestion_manifest["review_audit_sha256"] = sha256(audit_path.read_bytes()).hexdigest()
        (temporary / "ingestion-manifest.json").write_text(
            json.dumps(ingestion_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, labels_root)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return {
        "primary": len(primary),
        "secondary": len(secondary),
        "development_primary": sum(
            value["review_round"] == "primary" for value in development
        ),
    }
