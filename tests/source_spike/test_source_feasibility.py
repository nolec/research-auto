from __future__ import annotations

import copy

from src.source_spike.feasibility import (
    decision_basis_sha256,
    policy_evidence_sha256,
    validate_feasibility_decision,
)


def decision() -> dict:
    value = {
        "decision_version": "1.0.0",
        "source": "example",
        "status": "PASS",
        "evaluated_at": "2026-08-17T00:00:00Z",
        "policy_evidence": [
            {
                "id": "policy-1",
                "url": "https://example.com/policy",
                "checked_at": "2026-08-17T00:00:00Z",
                "claim": "Stored public API data may be retained for the experiment.",
            }
        ],
        "policy_evidence_sha256": "",
        "product_requirements": {
            "evidence_window_days": 90,
            "stable_author_identity_required": True,
            "immutable_evidence_required": True,
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
            for name in (
                "comment_text",
                "comment_id",
                "video_id",
                "canonical_url",
                "author_derived_identifier",
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
        "next_action": "implement_adapter",
    }
    value["policy_evidence_sha256"] = policy_evidence_sha256(value["policy_evidence"])
    value["decision_basis_sha256"] = decision_basis_sha256(
        value["policy_evidence"], value["product_requirements"]
    )
    return value


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

    assert "required data class set mismatch" in validate_feasibility_decision(value)


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
