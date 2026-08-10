import json
from pathlib import Path

import jsonschema
import pytest

from src.contracts.validation import validate_contract


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas"


def load_schema(name: str) -> dict:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def validate(instance: dict, schema_name: str) -> None:
    validate_contract(instance, load_schema(schema_name))


def make_evidence(kind: str, suffix: str) -> dict:
    return {
        "evidence_id": f"ev-{suffix}",
        "document_id": f"document-{suffix}",
        "source_url": f"https://example.com/posts/{suffix}",
        "published_at": "2026-08-01T09:00:00Z",
        "author_hash": f"sha256:{suffix}",
        "community": f"community-{suffix}",
        "evidence_group_id": f"group-{suffix}",
        "kind": kind,
        "quote": f"Source-backed {kind} observation {suffix}.",
        "interpretation": f"The quotation is classified as {kind} evidence.",
        "confidence": 0.92,
    }


@pytest.fixture
def evidence() -> dict:
    return make_evidence("money", "001")


@pytest.fixture
def opportunity_card(evidence: dict) -> dict:
    loss_evidence = [make_evidence("loss", "loss-1"), make_evidence("loss", "loss-2")]
    money_evidence = [evidence, make_evidence("willingness_to_pay", "money-2")]
    gap_evidence = [
        make_evidence("solution_gap", "gap-1"),
        make_evidence("solution_gap", "gap-2"),
    ]
    return {
        "card_id": "card-001",
        "cluster_id": "cluster-001",
        "observed_actor": "small online sellers",
        "inferred_customer_segment": "Korean marketplace sellers",
        "problem_statement": "Sellers cannot reliably calculate product-level profit.",
        "evidence_status": "EVIDENCE_BACKED",
        "actionability_status": "ACTIONABLE",
        "review_value_score": 84.5,
        "independent_author_count": 7,
        "independent_evidence_group_count": 4,
        "recent_case_count": 13,
        "growth_status": "KNOWN",
        "loss_evidence": loss_evidence,
        "money_evidence": money_evidence,
        "current_alternatives": ["spreadsheets", "outsourced bookkeeping"],
        "solution_gap_evidence": gap_evidence,
        "current_solution_evidence": [make_evidence("alternative", "solution-1")],
        "customer_channel_evidence": [
            make_evidence("customer_channel", "channel-1")
        ],
        "productizable_scope": {
            "status": "PRODUCTIZABLE",
            "delivery_mode": "SOFTWARE",
            "summary": "A bounded profit-calculation workflow can be automated.",
        },
        "known_blockers": [],
        "blocker_assessment": {
            "status": "NONE_FOUND",
            "reasons": ["No known legal or platform-policy blocker in public evidence."],
        },
        "supporting_evidence": [
            make_evidence("problem", "problem-1"),
            make_evidence("problem", "problem-2"),
            make_evidence("problem", "problem-3"),
        ],
        "counter_evidence": [],
        "counter_assessment": {
            "status": "NONE_CRITICAL",
            "reasons": ["No critical counter-evidence found in the reviewed sources."],
        },
        "uncertainties": ["Cross-platform author identity is unknown."],
        "automatic_decision": "REVIEW",
        "decision_reasons": ["Evidence and actionability gates passed."],
        "human_audit": None,
        "source_versions": {"reddit": "api-v1"},
        "model_version": "model-v1",
        "prompt_version": "extract-v1",
        "policy_version": "provisional-v1",
        "generated_at": "2026-08-10T04:00:00Z",
    }


def test_schemas_are_valid_draft_2020_12() -> None:
    for name in ("evidence.schema.json", "opportunity-card.schema.json"):
        jsonschema.Draft202012Validator.check_schema(load_schema(name))


def test_valid_evidence_matches_contract(evidence: dict) -> None:
    validate(evidence, "evidence.schema.json")


def test_valid_opportunity_card_matches_contract(opportunity_card: dict) -> None:
    validate(opportunity_card, "opportunity-card.schema.json")


@pytest.mark.parametrize(
    "required_field",
    [
        "evidence_status",
        "actionability_status",
        "review_value_score",
        "supporting_evidence",
        "decision_reasons",
        "model_version",
        "prompt_version",
        "policy_version",
        "counter_assessment",
    ],
)
def test_card_rejects_missing_required_contract_field(
    opportunity_card: dict,
    required_field: str,
) -> None:
    opportunity_card.pop(required_field)

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


def test_card_rejects_unknown_decision_status(opportunity_card: dict) -> None:
    opportunity_card["evidence_status"] = "PROBABLY_FINE"

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


@pytest.mark.parametrize("status", ["CRITICAL", "UNKNOWN"])
def test_evidence_backed_card_rejects_unresolved_critical_counter_evidence(
    opportunity_card: dict,
    status: str,
) -> None:
    opportunity_card["counter_assessment"] = {
        "status": status,
        "reasons": ["A critical counter-signal requires resolution."],
    }

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


def test_evidence_backed_card_rejects_empty_evidence(opportunity_card: dict) -> None:
    opportunity_card.update(
        independent_author_count=0,
        independent_evidence_group_count=0,
        recent_case_count=0,
        loss_evidence=[],
        money_evidence=[],
        supporting_evidence=[],
    )

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("independent_author_count", 4),
        ("independent_evidence_group_count", 2),
        ("recent_case_count", 9),
    ],
)
def test_evidence_backed_card_rejects_count_below_policy_threshold(
    opportunity_card: dict,
    field: str,
    invalid_value: int,
) -> None:
    opportunity_card[field] = invalid_value

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


@pytest.mark.parametrize("field", ["loss_evidence", "money_evidence"])
def test_evidence_backed_card_requires_two_economic_observations(
    opportunity_card: dict,
    field: str,
) -> None:
    opportunity_card[field] = opportunity_card[field][:1]

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


def test_actionable_card_requires_current_alternative(opportunity_card: dict) -> None:
    opportunity_card["current_alternatives"] = []

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


def test_actionable_card_requires_two_solution_gap_observations(
    opportunity_card: dict,
) -> None:
    opportunity_card["solution_gap_evidence"] = opportunity_card[
        "solution_gap_evidence"
    ][:1]

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


@pytest.mark.parametrize(
    "required_field",
    [
        "current_solution_evidence",
        "customer_channel_evidence",
        "productizable_scope",
        "blocker_assessment",
    ],
)
def test_actionable_card_rejects_missing_actionability_contract(
    opportunity_card: dict,
    required_field: str,
) -> None:
    opportunity_card.pop(required_field)

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


@pytest.mark.parametrize(
    "field",
    ["loss_evidence", "money_evidence", "supporting_evidence"],
)
def test_card_rejects_exact_duplicate_evidence(
    opportunity_card: dict,
    field: str,
) -> None:
    opportunity_card[field] = [opportunity_card[field][0]] * len(
        opportunity_card[field]
    )

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


@pytest.mark.parametrize(
    ("field", "invalid_evidence"),
    [
        ("loss_evidence", make_evidence("money", "wrong-loss")),
        ("money_evidence", make_evidence("loss", "wrong-money")),
        ("solution_gap_evidence", make_evidence("problem", "wrong-gap")),
        ("counter_evidence", make_evidence("solution_gap", "wrong-counter")),
    ],
)
def test_card_rejects_evidence_in_wrong_semantic_bucket(
    opportunity_card: dict,
    field: str,
    invalid_evidence: dict,
) -> None:
    if opportunity_card[field]:
        opportunity_card[field][0] = invalid_evidence
    else:
        opportunity_card[field] = [invalid_evidence]

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


@pytest.mark.parametrize(
    ("schema_name", "instance", "field", "invalid_value"),
    [
        ("evidence.schema.json", make_evidence("problem", "bad-url"), "source_url", "not-a-url"),
        ("evidence.schema.json", make_evidence("problem", "bad-date"), "published_at", "yesterday"),
    ],
)
def test_evidence_rejects_invalid_formats(
    schema_name: str,
    instance: dict,
    field: str,
    invalid_value: str,
) -> None:
    instance[field] = invalid_value

    with pytest.raises(jsonschema.ValidationError):
        validate(instance, schema_name)


def test_card_rejects_invalid_generated_at(opportunity_card: dict) -> None:
    opportunity_card["generated_at"] = "2026-99-99T99:99:99Z"

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")


def test_embedded_evidence_contract_stays_in_sync() -> None:
    standalone = load_schema("evidence.schema.json")
    embedded = load_schema("opportunity-card.schema.json")["$defs"]["evidence"]

    for key in ("type", "additionalProperties", "required", "properties"):
        assert embedded[key] == standalone[key]


def test_inferred_customer_segment_cannot_be_used_as_evidence(
    opportunity_card: dict,
) -> None:
    opportunity_card["supporting_evidence"] = [
        {
            "evidence_id": "ev-inferred",
            "document_id": "generated",
            "source_url": "https://example.com/generated",
            "published_at": "2026-08-10T04:00:00Z",
            "author_hash": "sha256:generated",
            "community": "generated",
            "evidence_group_id": "generated",
            "kind": "inferred_customer_segment",
            "quote": "Generated segment",
            "interpretation": "LLM inference",
            "confidence": 0.5,
        }
    ]

    with pytest.raises(jsonschema.ValidationError):
        validate(opportunity_card, "opportunity-card.schema.json")
