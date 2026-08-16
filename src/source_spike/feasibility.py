from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas/source-feasibility-decision.schema.json")
    .read_text(encoding="utf-8")
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FORMAT_CHECKER)
_REQUIRED_GATES = {
    "retention",
    "provenance",
    "author_independence",
    "deletion",
    "reproducibility",
}
_REQUIRED_DATA_CLASSES = {
    "comment_text",
    "comment_id",
    "video_id",
    "canonical_url",
    "author_derived_identifier",
}


def policy_evidence_sha256(evidence: Sequence[Mapping[str, object]]) -> str:
    encoded = json.dumps(
        evidence, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def decision_basis_sha256(
    evidence: Sequence[Mapping[str, object]], requirements: Mapping[str, object]
) -> str:
    encoded = json.dumps(
        {"policy_evidence": evidence, "product_requirements": requirements},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _schema_errors(value: Mapping[str, object]) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in sorted(
            _VALIDATOR.iter_errors(value),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
    ]


def validate_feasibility_decision(value: Mapping[str, object]) -> list[str]:
    errors = _schema_errors(value)
    if errors:
        return errors

    evidence = value["policy_evidence"]
    assert isinstance(evidence, list)
    evidence_ids = [str(item["id"]) for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("policy evidence ids must be unique")
    if policy_evidence_sha256(evidence) != value["policy_evidence_sha256"]:
        errors.append("policy evidence hash mismatch")

    requirements = value["product_requirements"]
    assert isinstance(requirements, Mapping)
    if decision_basis_sha256(evidence, requirements) != value["decision_basis_sha256"]:
        errors.append("decision basis hash mismatch")

    data_classes = value["data_classes"]
    gates = value["required_gates"]
    assert isinstance(data_classes, list) and isinstance(gates, list)
    data_by_name = {str(item["name"]): item for item in data_classes}
    gate_by_id = {str(item["id"]): item for item in gates}
    if len(data_by_name) != len(data_classes) or set(data_by_name) != _REQUIRED_DATA_CLASSES:
        errors.append("required data class set mismatch")
    if len(gate_by_id) != len(gates) or set(gate_by_id) != _REQUIRED_GATES:
        errors.append("required gate set mismatch")

    known_evidence = set(evidence_ids)
    for item in (*data_classes, *gates):
        if not set(item["evidence_ids"]).issubset(known_evidence):
            errors.append(f"{item.get('name', item.get('id'))}: unknown policy evidence reference")

    window = int(requirements["evidence_window_days"])
    retention_gate = gate_by_id.get("retention")
    if retention_gate and retention_gate["status"] == "pass":
        for item in data_classes:
            limit = item["max_retention_days"]
            if item["persisted"] and isinstance(limit, int) and limit < window and item["refresh_method"] is None:
                errors.append("retention gate cannot pass without a refresh path")
                break

    author = data_by_name.get("author_derived_identifier")
    author_gate = gate_by_id.get("author_independence")
    if (
        requirements["stable_author_identity_required"] is True
        and author is not None
        and author["stable_across_runs"] is False
        and author_gate is not None
        and author_gate["status"] == "pass"
    ):
        errors.append("author independence gate cannot pass without stable identity")

    status = value["status"]
    blockers = value["blockers"]
    assert isinstance(blockers, list)
    all_pass = all(item["status"] == "pass" for item in gates)
    if status == "PASS":
        if not all_pass:
            errors.append("PASS requires every required gate to pass")
        if blockers:
            errors.append("PASS cannot retain blockers")
        if value["next_action"] != "implement_adapter":
            errors.append("PASS must route to adapter implementation")
    else:
        if not blockers:
            errors.append("NOT_ELIGIBLE requires at least one blocker")
        if value["next_action"] == "implement_adapter":
            errors.append("NOT_ELIGIBLE cannot route to adapter implementation")
        if all_pass:
            errors.append("NOT_ELIGIBLE requires a failed or unresolved gate")
    return errors
