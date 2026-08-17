from __future__ import annotations

import copy

from src.source_spike.feasibility import (
    decision_basis_sha256,
    decision_integrity_sha256,
    policy_evidence_sha256,
    validate_feasibility_decision,
)


def decision() -> dict:
    value = {
        "decision_version": "2.0.0",
        "source": "example",
        "status": "PASS",
        "evaluated_at": "2026-08-17T00:00:00Z",
        "policy_evidence": [
            {
                "id": "policy-1",
                "url": "https://example.com/policy",
                "checked_at": "2026-08-17T00:00:00Z",
                "claim": "Stored public API data may be retained for the experiment.",
                "effective_at": "2026-01-01",
                "section": "Retention",
                "captured_excerpt": "Public API data may be retained for this experiment.",
                "captured_excerpt_sha256": "",
                "manual_revalidation_due_at": "2026-11-17T00:00:00Z",
            }
        ],
        "policy_evidence_sha256": "",
        "product_requirements": {
            "evidence_window_days": 90,
            "stable_author_identity_required": True,
            "immutable_evidence_required": True,
        },
        "intended_use": {
            "current": {
                "purpose": "internal_source_calibration",
                "commercial_operation": False,
                "persistent_storage": True,
                "cross_run_author_identity": True,
            },
            "future": {
                "purpose": "commercial_demand_intelligence_product",
                "commercial_operation": True,
                "reuse_current_raw_data": "desired_but_not_assumed",
            },
            "ai_processing": {
                "model_training": "not_used",
                "fine_tuning": "not_used",
                "embedding_or_indexing": "planned",
                "llm_inference_extraction": "planned",
                "derived_output_storage": "planned",
            },
        },
        "authorization_status": "verified",
        "evaluation_profile": {
            "id": "example-v1",
            "required_gate_ids": [
                "retention", "provenance", "author_independence", "deletion", "reproducibility"
            ],
            "required_data_roles": [
                "content", "source_item_identity", "container_identity", "canonical_location", "author_identity"
            ],
            "horizon_gate_ids": {
                "current_collection": [
                    "retention", "provenance", "author_independence", "deletion", "reproducibility"
                ],
                "future_commercial_reuse": [
                    "retention", "provenance", "author_independence", "deletion", "reproducibility"
                ],
            },
        },
        "data_classes": [
            {
                "name": name,
                "policy_class": "public_api_data",
                "persisted": True,
                "max_retention_days": 90,
                "refresh_method": "Re-fetch the resource before the deadline.",
                "deletion_method": "Delete the local value when unavailable.",
                "stable_across_runs": name == "author_derived_identifier",
                "evidence_ids": ["policy-1"],
            }
            for name, role in (
                ("comment_text", "content"),
                ("comment_id", "source_item_identity"),
                ("video_id", "container_identity"),
                ("canonical_url", "canonical_location"),
                ("author_derived_identifier", "author_identity"),
            )
        ],
        "required_gates": [
            {"id": gate, "status": "pass", "evidence_ids": ["policy-1"], "reason": "The required capability is explicitly supported."}
            for gate in (
                "retention",
                "provenance",
                "author_independence",
                "deletion",
                "reproducibility",
            )
        ],
        "blockers": [],
        "recheck_conditions": [],
        "eligibility": {
            "current_collection": "PASS",
            "future_commercial_reuse": "PASS",
        },
        "next_action": "implement_adapter",
        "operational_next_action": "implement_adapter",
        "supersedes_decision_sha256": None,
        "decision_integrity_sha256": "",
    }
    for item in value["policy_evidence"]:
        item["captured_excerpt_sha256"] = __import__("hashlib").sha256(
            item["captured_excerpt"].encode("utf-8")
        ).hexdigest()
    for item, role in zip(value["data_classes"], value["evaluation_profile"]["required_data_roles"]):
        item["role"] = role
    value["policy_evidence_sha256"] = policy_evidence_sha256(value["policy_evidence"])
    value["decision_basis_sha256"] = decision_basis_sha256(
        value["policy_evidence"], value["product_requirements"], value["intended_use"]
    )
    value["decision_integrity_sha256"] = decision_integrity_sha256(value)
    return value


def refresh_hashes(value: dict) -> None:
    value["policy_evidence_sha256"] = policy_evidence_sha256(value["policy_evidence"])
    value["decision_basis_sha256"] = decision_basis_sha256(
        value["policy_evidence"], value["product_requirements"], value["intended_use"]
    )
    value["decision_integrity_sha256"] = decision_integrity_sha256(value)


def test_valid_pass_decision_has_no_errors() -> None:
    assert validate_feasibility_decision(decision()) == []


def test_unresolved_gate_cannot_pass() -> None:
    value = decision()
    value["required_gates"][2]["status"] = "unresolved"

    errors = validate_feasibility_decision(value)

    assert "PASS requires every required gate to pass" in errors


def test_policy_evidence_drift_is_rejected() -> None:
    value = decision()
    value["policy_evidence"][0]["claim"] = "Changed after the decision was frozen."

    assert "policy evidence hash mismatch" in validate_feasibility_decision(value)


def test_product_requirement_drift_is_rejected() -> None:
    value = decision()
    value["product_requirements"] = {
        "evidence_window_days": 30,
        "stable_author_identity_required": False,
        "immutable_evidence_required": False,
    }

    assert "decision basis hash mismatch" in validate_feasibility_decision(value)


def test_missing_required_data_class_is_rejected() -> None:
    value = decision()
    value["data_classes"] = value["data_classes"][:-1]

    assert "required data role set mismatch" in validate_feasibility_decision(value)


def test_short_retention_without_refresh_cannot_pass_retention_gate() -> None:
    value = decision()
    value["data_classes"][0]["max_retention_days"] = 30
    value["data_classes"][0]["refresh_method"] = None

    assert "retention gate cannot pass without a refresh path" in validate_feasibility_decision(value)


def test_unstable_author_identity_cannot_pass_author_gate() -> None:
    value = decision()
    author = next(item for item in value["data_classes"] if item["name"] == "author_derived_identifier")
    author["stable_across_runs"] = False

    assert "author independence gate cannot pass without stable identity" in validate_feasibility_decision(value)


def test_not_eligible_requires_blocker_and_nonimplementation_route() -> None:
    value = decision()
    value["status"] = "NOT_ELIGIBLE"
    value["next_action"] = "implement_adapter"

    errors = validate_feasibility_decision(value)

    assert "NOT_ELIGIBLE requires at least one blocker" in errors
    assert "NOT_ELIGIBLE cannot route to adapter implementation" in errors


def test_schema_rejects_unknown_fields() -> None:
    value = copy.deepcopy(decision())
    value["silent_override"] = True

    assert any("silent_override" in error for error in validate_feasibility_decision(value))


def test_decision_integrity_covers_verdict_and_routing() -> None:
    value = decision()
    value["eligibility"]["future_commercial_reuse"] = "NOT_ELIGIBLE"
    value["next_action"] = "seek_compliance_clearance"

    assert "decision integrity hash mismatch" in validate_feasibility_decision(value)


def test_unverified_authorization_cannot_implement_adapter() -> None:
    value = decision()
    value["authorization_status"] = "unverified"
    value["decision_integrity_sha256"] = decision_integrity_sha256(value)

    assert "unverified authorization cannot route to adapter implementation" in validate_feasibility_decision(value)


def test_duplicate_data_role_is_rejected() -> None:
    value = decision()
    value["data_classes"][1]["role"] = "content"
    value["decision_integrity_sha256"] = decision_integrity_sha256(value)

    assert "required data role set mismatch" in validate_feasibility_decision(value)


def test_not_eligible_status_requires_at_least_one_ineligible_horizon() -> None:
    value = decision()
    value["status"] = "NOT_ELIGIBLE"
    value["blockers"] = ["TEMPORARY_BLOCKER"]
    value["required_gates"][0]["status"] = "unresolved"
    value["next_action"] = "seek_compliance_clearance"
    value["recheck_conditions"] = ["Verify the temporary authorization blocker."]
    refresh_hashes(value)

    assert "NOT_ELIGIBLE requires an ineligible horizon" in validate_feasibility_decision(value)


def test_ineligible_current_collection_cannot_route_to_adapter() -> None:
    value = decision()
    value["status"] = "NOT_ELIGIBLE"
    value["eligibility"]["current_collection"] = "NOT_ELIGIBLE"
    value["blockers"] = ["CURRENT_COLLECTION_BLOCKED"]
    value["required_gates"][0]["status"] = "unresolved"
    value["next_action"] = "seek_compliance_clearance"
    value["operational_next_action"] = "implement_adapter"
    value["recheck_conditions"] = ["Clear current collection authorization."]
    refresh_hashes(value)

    assert "ineligible current collection cannot route to adapter" in validate_feasibility_decision(value)


def test_evidence_revalidation_deadline_cannot_precede_evaluation() -> None:
    value = decision()
    value["policy_evidence"][0]["manual_revalidation_due_at"] = "2026-08-16T23:59:59Z"
    refresh_hashes(value)

    assert any(
        "policy evidence revalidation deadline has expired" in error
        for error in validate_feasibility_decision(value)
    )


def test_unverified_authorization_cannot_pass_current_collection() -> None:
    value = decision()
    value["status"] = "NOT_ELIGIBLE"
    value["authorization_status"] = "unverified"
    value["eligibility"]["future_commercial_reuse"] = "NOT_ELIGIBLE"
    value["required_gates"][0]["status"] = "unresolved"
    value["blockers"] = ["AUTHORIZATION_UNVERIFIED"]
    value["next_action"] = "seek_compliance_clearance"
    value["recheck_conditions"] = ["Verify collection authorization."]
    refresh_hashes(value)

    errors = validate_feasibility_decision(value)
    assert "unverified authorization cannot pass current collection" in errors
    assert "unverified authorization cannot route to adapter" in errors


def test_horizon_cannot_pass_with_unresolved_mapped_gate() -> None:
    value = decision()
    value["required_gates"][0]["status"] = "unresolved"
    refresh_hashes(value)

    errors = validate_feasibility_decision(value)
    assert "current_collection cannot pass with unresolved or failed gates" in errors
    assert "future_commercial_reuse cannot pass with unresolved or failed gates" in errors


def add_future_only_gate(value: dict, *, map_to_future: bool) -> None:
    value["required_gates"].append(
        {
            "id": "future_only",
            "status": "unresolved",
            "evidence_ids": ["policy-1"],
            "reason": "Future commercial permission remains unresolved for this example.",
        }
    )
    value["evaluation_profile"]["required_gate_ids"].append("future_only")
    if map_to_future:
        value["evaluation_profile"]["horizon_gate_ids"]["future_commercial_reuse"] = [
            "future_only"
        ]
    value["status"] = "NOT_ELIGIBLE"
    value["eligibility"]["future_commercial_reuse"] = "NOT_ELIGIBLE"
    value["blockers"] = ["FUTURE_PERMISSION_UNRESOLVED"]
    value["next_action"] = "seek_compliance_clearance"
    value["recheck_conditions"] = ["Verify future commercial permission."]


def test_every_required_gate_must_be_assigned_to_a_horizon() -> None:
    value = decision()
    add_future_only_gate(value, map_to_future=False)
    value["eligibility"]["current_collection"] = "NOT_ELIGIBLE"
    value["operational_next_action"] = "select_replacement_source"
    refresh_hashes(value)

    assert "required gates must be assigned to at least one horizon" in validate_feasibility_decision(value)


def test_horizon_must_pass_when_all_mapped_gates_pass() -> None:
    value = decision()
    add_future_only_gate(value, map_to_future=True)
    value["eligibility"]["current_collection"] = "NOT_ELIGIBLE"
    value["operational_next_action"] = "select_replacement_source"
    refresh_hashes(value)

    assert "current_collection must pass when all mapped gates pass" in validate_feasibility_decision(value)


def test_current_pass_future_not_eligible_is_valid_when_gate_sets_diverge() -> None:
    value = decision()
    add_future_only_gate(value, map_to_future=True)
    refresh_hashes(value)

    assert validate_feasibility_decision(value) == []
