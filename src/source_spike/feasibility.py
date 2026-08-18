from __future__ import annotations

import json
from datetime import datetime
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


def policy_evidence_sha256(evidence: Sequence[Mapping[str, object]]) -> str:
    encoded = json.dumps(
        evidence, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def decision_basis_sha256(
    evidence: Sequence[Mapping[str, object]],
    requirements: Mapping[str, object],
    intended_use: Mapping[str, object],
) -> str:
    encoded = json.dumps(
        {
            "policy_evidence": evidence,
            "product_requirements": requirements,
            "intended_use": intended_use,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def decision_integrity_sha256(value: Mapping[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "decision_integrity_sha256"}
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
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
    evaluated_at = datetime.fromisoformat(str(value["evaluated_at"]).replace("Z", "+00:00"))
    for item in evidence:
        excerpt = str(item["captured_excerpt"])
        if sha256(excerpt.encode("utf-8")).hexdigest() != item["captured_excerpt_sha256"]:
            errors.append(f"{item['id']}: captured excerpt hash mismatch")
        revalidation_due_at = datetime.fromisoformat(
            str(item["manual_revalidation_due_at"]).replace("Z", "+00:00")
        )
        if revalidation_due_at < evaluated_at:
            errors.append(f"{item['id']}: policy evidence revalidation deadline has expired")

    requirements = value["product_requirements"]
    assert isinstance(requirements, Mapping)
    intended_use = value["intended_use"]
    assert isinstance(intended_use, Mapping)
    if decision_basis_sha256(evidence, requirements, intended_use) != value["decision_basis_sha256"]:
        errors.append("decision basis hash mismatch")
    if decision_integrity_sha256(value) != value["decision_integrity_sha256"]:
        errors.append("decision integrity hash mismatch")

    data_classes = value["data_classes"]
    gates = value["required_gates"]
    assert isinstance(data_classes, list) and isinstance(gates, list)
    data_by_name = {str(item["name"]): item for item in data_classes}
    gate_by_id = {str(item["id"]): item for item in gates}
    profile = value["evaluation_profile"]
    assert isinstance(profile, Mapping)
    required_roles = set(profile["required_data_roles"])
    observed_roles = [str(item["role"]) for item in data_classes]
    if len(data_by_name) != len(data_classes):
        errors.append("data class names must be unique")
    if len(observed_roles) != len(set(observed_roles)) or set(observed_roles) != required_roles:
        errors.append("required data role set mismatch")
    if len(gate_by_id) != len(gates) or set(gate_by_id) != set(profile["required_gate_ids"]):
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

    author = next((item for item in data_classes if item["role"] == "author_identity"), None)
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
    eligibility = value["eligibility"]
    assert isinstance(eligibility, Mapping)
    horizon_gate_ids = profile["horizon_gate_ids"]
    assert isinstance(horizon_gate_ids, Mapping)
    assigned_gate_ids = {
        gate_id for mapped_gate_ids in horizon_gate_ids.values() for gate_id in mapped_gate_ids
    }
    if set(profile["required_gate_ids"]) - assigned_gate_ids:
        errors.append("required gates must be assigned to at least one horizon")
    for horizon, mapped_gate_ids in horizon_gate_ids.items():
        unknown_gate_ids = set(mapped_gate_ids) - set(gate_by_id)
        if unknown_gate_ids:
            errors.append(f"{horizon}: horizon references unknown gates")
            continue
        mapped_gates_pass = all(
            gate_by_id[gate_id]["status"] == "pass" for gate_id in mapped_gate_ids
        )
        if eligibility[horizon] == "PASS" and not mapped_gates_pass:
            errors.append(f"{horizon} cannot pass with unresolved or failed gates")
        if (
            value["authorization_status"] == "verified"
            and eligibility[horizon] == "NOT_ELIGIBLE"
            and mapped_gates_pass
        ):
            errors.append(f"{horizon} must pass when all mapped gates pass")
    both_eligible = all(item == "PASS" for item in eligibility.values())
    if status == "PASS":
        if not all_pass or not both_eligible:
            errors.append("PASS requires every required gate to pass")
        if blockers:
            errors.append("PASS cannot retain blockers")
        if value["next_action"] not in {"probe_capacity", "implement_adapter"}:
            errors.append("PASS must route to capacity probe or adapter implementation")
    else:
        if not blockers:
            errors.append("NOT_ELIGIBLE requires at least one blocker")
        if value["next_action"] == "implement_adapter":
            errors.append("NOT_ELIGIBLE cannot route to adapter implementation")
        if value["next_action"] == "probe_capacity":
            errors.append("NOT_ELIGIBLE cannot route to capacity probe")
        if all_pass:
            errors.append("NOT_ELIGIBLE requires a failed or unresolved gate")
        if both_eligible:
            errors.append("NOT_ELIGIBLE requires an ineligible horizon")
    current_eligible = eligibility["current_collection"] == "PASS"
    operational_action = value["operational_next_action"]
    if not current_eligible and operational_action == "implement_adapter":
        errors.append("ineligible current collection cannot route to adapter")
    if not current_eligible and operational_action == "probe_capacity":
        errors.append("ineligible current collection cannot route to capacity probe")
    if current_eligible and operational_action not in {"probe_capacity", "implement_adapter"}:
        errors.append("eligible current collection must route to capacity probe or adapter")
    if (value["next_action"] == "probe_capacity") != (operational_action == "probe_capacity"):
        errors.append("capacity probe routing must be consistent")
    if value["authorization_status"] == "unverified":
        if current_eligible:
            errors.append("unverified authorization cannot pass current collection")
        if operational_action == "implement_adapter":
            errors.append("unverified authorization cannot route to adapter")
        if operational_action == "probe_capacity":
            errors.append("unverified authorization cannot route to capacity probe")
        if value["next_action"] == "implement_adapter":
            errors.append("unverified authorization cannot route to adapter implementation")
        if value["next_action"] == "probe_capacity":
            errors.append("unverified authorization cannot route to capacity probe")
    if value["next_action"] == "seek_compliance_clearance" and not value["recheck_conditions"]:
        errors.append("compliance clearance requires a recheck condition")
    return errors
