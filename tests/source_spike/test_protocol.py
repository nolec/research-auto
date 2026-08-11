from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.source_spike.protocol import (
    Label,
    MoneySignalType,
    agreement_result,
    content_sha256,
    money_density,
    select_primary_sources,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parents[2]


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def valid_compliance(source: str = "github") -> dict:
    return {
        "source": source,
        "access_method": "official_api",
        "authentication": "optional_token",
        "official_api": True,
        "rate_limit": "60 requests/hour without authentication",
        "allowed_usage": "Public repository metadata access",
        "raw_text_retention": "local_only",
        "redistribution": "derived_metrics_only",
        "deletion_handling": "remove_on_refresh",
        "attribution": "source URL retained",
        "commercial_use_risk": "low",
        "robots_or_automated_access_policy": "Official REST API only",
        "decision": "allowed",
        "checked_at": "2026-08-11T00:00:00Z",
        "source_references": [
            "https://docs.github.com/en/rest/issues/issues",
            "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service",
        ],
    }


def valid_compliance_records() -> dict[str, dict]:
    return {
        f"compliance/{source}.json": valid_compliance(source)
        for source in ["github", "stackexchange", "steam", "youtube", "reddit"]
    }


def valid_manifest() -> dict:
    compliance_records = valid_compliance_records()
    return {
        "manifest_version": "1.0.0",
        "random_seed": 20260811,
        "target_valid_records": 100,
        "sources": [
            {
                "source": source,
                "archetype": archetype,
                "compliance_decision": "allowed",
                "compliance_ref": f"compliance/{source}.json",
                "compliance_hash": content_sha256(
                    compliance_records[f"compliance/{source}.json"]
                ),
                "strata": [
                    {"name": "large", "target": f"{source}/a", "quota": 33},
                    {"name": "medium", "target": f"{source}/b", "quota": 33},
                    {"name": "small", "target": f"{source}/c", "quota": 34},
                ],
            }
            for source, archetype in [
                ("github", "professional_issue"),
                ("stackexchange", "question_answer"),
                ("steam", "purchase_review"),
                ("youtube", "product_feedback"),
                ("reddit", "complaint_community"),
            ]
        ],
    }


def test_compliance_requires_automated_access_policy_and_multiple_references() -> None:
    schema = load_schema("source-compliance.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    assert not list(validator.iter_errors(valid_compliance()))

    missing_policy = valid_compliance()
    missing_policy.pop("robots_or_automated_access_policy")
    assert list(validator.iter_errors(missing_policy))

    one_reference = valid_compliance()
    one_reference["source_references"] = one_reference["source_references"][:1]
    assert list(validator.iter_errors(one_reference))


@pytest.mark.parametrize("decision", ["allowed", "conditional"])
def test_blocked_commercial_risk_requires_blocked_decision(decision: str) -> None:
    validator = Draft202012Validator(load_schema("source-compliance.schema.json"))
    compliance = valid_compliance()
    compliance["commercial_use_risk"] = "blocked"
    compliance["decision"] = decision

    assert list(validator.iter_errors(compliance))


def test_high_commercial_risk_cannot_be_marked_allowed() -> None:
    validator = Draft202012Validator(load_schema("source-compliance.schema.json"))
    compliance = valid_compliance()
    compliance["commercial_use_risk"] = "high"

    assert list(validator.iter_errors(compliance))


def test_manifest_requires_three_strata_whose_quotas_total_target() -> None:
    schema = load_schema("source-spike-manifest.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    assert not list(validator.iter_errors(valid_manifest()))

    too_few = valid_manifest()
    too_few["sources"][0]["strata"] = too_few["sources"][0]["strata"][:2]
    assert list(validator.iter_errors(too_few))

    wrong_total = valid_manifest()
    wrong_total["sources"][0]["strata"][2]["quota"] = 33
    assert validate_manifest(wrong_total, valid_compliance_records()) == [
        "github: stratum quotas must total target_valid_records (99 != 100)"
    ]


def test_manifest_requires_exactly_five_unique_sources() -> None:
    validator = Draft202012Validator(load_schema("source-spike-manifest.schema.json"))
    too_few = valid_manifest()
    too_few["sources"].pop()
    assert list(validator.iter_errors(too_few))

    duplicate = valid_manifest()
    duplicate["sources"][4]["source"] = "github"
    errors = validate_manifest(duplicate, valid_compliance_records())
    assert "sources must have unique source names: github" in errors


def test_manifest_validation_composes_schema_and_semantic_errors() -> None:
    malformed = valid_manifest()
    malformed["sources"] = "not-an-array"

    errors = validate_manifest(malformed, valid_compliance_records())

    assert errors
    assert "sources" in errors[0]


@pytest.mark.parametrize("field", ["name", "target"])
def test_manifest_rejects_duplicate_stratum_identity(field: str) -> None:
    manifest = valid_manifest()
    manifest["sources"][0]["strata"][1][field] = manifest["sources"][0]["strata"][0][field]

    errors = validate_manifest(manifest, valid_compliance_records())

    assert errors == [f"github: strata must have unique {field} values"]


def test_manifest_requires_matching_compliance_record_and_hash() -> None:
    records = valid_compliance_records()
    manifest = valid_manifest()
    ref = manifest["sources"][0]["compliance_ref"]
    records[ref]["decision"] = "conditional"

    errors = validate_manifest(manifest, records)

    assert f"github: compliance hash mismatch for {ref}" in errors
    assert f"github: manifest decision allowed does not match compliance decision conditional" in errors


def test_manifest_rejects_missing_or_wrong_source_compliance_record() -> None:
    records = valid_compliance_records()
    manifest = valid_manifest()
    ref = manifest["sources"][0]["compliance_ref"]
    del records[ref]
    assert validate_manifest(manifest, records) == [
        f"github: missing compliance record {ref}"
    ]

    records = valid_compliance_records()
    records[ref]["source"] = "someone-else"
    manifest["sources"][0]["compliance_hash"] = content_sha256(records[ref])
    assert validate_manifest(manifest, records) == [
        "github: compliance source does not match someone-else"
    ]


@pytest.mark.parametrize(
    ("field", "value", "expected_fragment"),
    [
        ("checked_at", "yesterday", "is not a 'date-time'"),
        ("source_references", ["not-a-uri", "still-not-a-uri"], "is not a 'uri'"),
    ],
)
def test_manifest_enforces_compliance_formats_at_runtime(
    field: str, value: object, expected_fragment: str
) -> None:
    records = valid_compliance_records()
    manifest = valid_manifest()
    ref = manifest["sources"][0]["compliance_ref"]
    records[ref][field] = value
    manifest["sources"][0]["compliance_hash"] = content_sha256(records[ref])

    errors = validate_manifest(manifest, records)

    assert any(expected_fragment in error for error in errors)


def test_structural_money_is_excluded_from_adjusted_density() -> None:
    labels = [
        Label(money_signal=True, money_signal_type="purchase", structural_money_signal=True),
        Label(money_signal=True, money_signal_type="loss", structural_money_signal=False),
        Label(money_signal=False),
        Label(money_signal=False),
    ]

    result = money_density(labels)

    assert result.raw == pytest.approx(0.5)
    assert result.adjusted == pytest.approx(0.25)


def test_money_signal_requires_a_type() -> None:
    with pytest.raises(ValueError, match="money_signal_type"):
        Label(money_signal=True)


def test_money_signal_rejects_an_unknown_runtime_type() -> None:
    with pytest.raises(ValueError, match="unsupported money_signal_type"):
        Label(money_signal=True, money_signal_type="unknown")  # type: ignore[arg-type]


def test_money_signal_normalizes_strings_to_the_single_enum_definition() -> None:
    label = Label(money_signal=True, money_signal_type="purchase")

    assert label.money_signal_type is MoneySignalType.PURCHASE


def test_prevalence_limited_agreement_uses_raw_threshold() -> None:
    result = agreement_result(
        reviewer_a=[False, False, False, False, False],
        reviewer_b=[False, False, False, False, True],
    )

    assert result.kappa_status == "prevalence_limited"
    assert result.raw_agreement == pytest.approx(0.8)
    assert result.passed is True


def test_balanced_agreement_requires_kappa() -> None:
    result = agreement_result(
        reviewer_a=[True, True, False, False, True],
        reviewer_b=[True, True, False, False, False],
    )

    assert result.kappa_status == "calculated"
    assert result.kappa is not None
    assert result.kappa >= 0.6
    assert result.passed is True


def test_provisional_sources_never_enter_primary_selection() -> None:
    candidates = [
        {"source": "github", "eligibility": "pass", "score": 90.0},
        {"source": "steam", "eligibility": "provisional", "score": 99.0},
        {"source": "youtube", "eligibility": "fail", "score": 100.0},
        {"source": "stackexchange", "eligibility": "pass", "score": 80.0},
    ]

    result = select_primary_sources(candidates, limit=3)

    assert result.primary == ["github", "stackexchange"]
    assert result.fallback == ["steam"]
    assert result.success is False


def test_selection_rejects_duplicate_source_candidates() -> None:
    candidates = [
        {"source": "github", "eligibility": "pass", "score": 90.0},
        {"source": "github", "eligibility": "pass", "score": 80.0},
        {"source": "steam", "eligibility": "pass", "score": 70.0},
    ]

    with pytest.raises(ValueError, match="duplicate source candidates: github"):
        select_primary_sources(candidates, limit=3)
