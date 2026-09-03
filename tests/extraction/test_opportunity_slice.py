from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.contracts.validation import validate_contract
from src.extraction.opportunity_slice import build_vertical_slice, render_card_markdown


ROOT = Path(__file__).resolve().parents[2]


def _evidence(
    kind: str,
    suffix: str,
    *,
    author: str | None = None,
    group: str | None = None,
) -> dict[str, object]:
    return {
        "evidence_id": f"ev-{suffix}",
        "document_id": f"document-{suffix}",
        "source_url": f"https://fixture.example.test/posts/{suffix}",
        "published_at": "2026-08-01T09:00:00Z",
        "author_hash": author or f"author-{suffix}",
        "community": "fixture-community",
        "evidence_group_id": group or f"group-{suffix}",
        "kind": kind,
        "quote": f"Fixture-backed {kind} observation {suffix}.",
        "interpretation": f"Fixture classifies this as {kind}.",
        "confidence": 0.9,
    }


def _actionable_fixture() -> list[dict[str, object]]:
    values = [
        _evidence("problem", "problem-1"),
        _evidence("problem", "problem-2"),
        _evidence("problem", "problem-3"),
        _evidence("loss", "loss-1"),
        _evidence("loss", "loss-2"),
        _evidence("money", "money-1"),
        _evidence("willingness_to_pay", "money-2"),
        _evidence("alternative", "alternative-1"),
        _evidence("customer_channel", "channel-1"),
        _evidence("solution_gap", "gap-1"),
        _evidence("solution_gap", "gap-2"),
    ]
    return [
        {
            "problem_key": "seller-profit-calculation",
            "observed_actor": "small online sellers",
            "problem_statement": "Sellers cannot reliably calculate product-level profit.",
            "productizable_scope": "A bounded profit-calculation workflow can be automated.",
            "delivery_mode": "SOFTWARE",
            "evidence": value,
        }
        for value in values
    ]


def _schema() -> dict[str, object]:
    return json.loads((ROOT / "schemas/opportunity-card.schema.json").read_text())


def test_vertical_slice_builds_schema_valid_fixture_card_and_markdown() -> None:
    cards = build_vertical_slice(_actionable_fixture())

    assert len(cards) == 1
    card = cards[0]
    validate_contract(card, _schema())
    assert card["evidence_status"] == "EVIDENCE_BACKED"
    assert card["actionability_status"] == "ACTIONABLE"
    assert card["automatic_decision"] == "REVIEW"
    assert card["review_value_score"] > 0
    assert card["source_versions"] == {"fixture": "deterministic-v1"}
    assert card["model_version"] == "fixture-only"
    markdown = render_card_markdown(card)
    assert "fixture-only" in markdown
    assert card["cluster_id"] in markdown
    assert card["decision_reasons"][0] in markdown
    assert card["uncertainties"][0] in markdown
    assert card["supporting_evidence"][0]["evidence_id"] in markdown
    assert card["supporting_evidence"][0]["source_url"] in markdown


def test_vertical_slice_does_not_count_same_author_and_group_as_independent() -> None:
    observations = _actionable_fixture()
    for value in observations:
        evidence = value["evidence"]
        assert isinstance(evidence, dict)
        evidence["author_hash"] = "same-author"
        evidence["evidence_group_id"] = "same-event"

    card = build_vertical_slice(observations)[0]

    assert card["independent_author_count"] == 1
    assert card["independent_evidence_group_count"] == 1
    assert card["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert card["review_value_score"] == 0


def test_vertical_slice_merges_shared_event_even_when_group_ids_differ() -> None:
    observations = _actionable_fixture()
    for index, value in enumerate(observations):
        evidence = value["evidence"]
        assert isinstance(evidence, dict)
        evidence["author_hash"] = f"different-author-{index}"
        evidence["evidence_group_id"] = f"different-group-{index}"
        value["event_key"] = "same-public-event"

    card = build_vertical_slice(observations)[0]

    assert card["independent_author_count"] == len(observations)
    assert card["independent_evidence_group_count"] == 1
    assert card["evidence_status"] == "INSUFFICIENT_EVIDENCE"


def test_vertical_slice_marks_unknown_independence_as_needs_review() -> None:
    observations = _actionable_fixture()
    observations[0]["independence_unknown"] = True

    card = build_vertical_slice(observations)[0]

    assert card["evidence_status"] == "NEEDS_REVIEW"
    assert card["review_value_score"] == 0


def test_vertical_slice_critical_counter_evidence_blocks_review_and_ranking() -> None:
    observations = _actionable_fixture()
    observations.append(
        {
            **observations[0],
            "evidence": _evidence("counter", "counter-1"),
            "counter_critical": True,
        }
    )

    card = build_vertical_slice(observations)[0]

    assert card["evidence_status"] == "CONFLICTING_EVIDENCE"
    assert card["automatic_decision"] == "REJECT"
    assert card["review_value_score"] == 0
    assert "critical counter-evidence" in card["decision_reasons"]


def test_vertical_slice_rejects_critical_counter_flag_without_counter_evidence() -> None:
    observations = _actionable_fixture()
    observations[0]["counter_critical"] = True

    with pytest.raises(ValueError, match="counter_critical requires counter evidence"):
        build_vertical_slice(observations)


def test_vertical_slice_uses_non_primary_non_productizable_scope_conservatively() -> None:
    observations = _actionable_fixture()
    observations[-1]["productizable"] = False

    card = build_vertical_slice(observations)[0]

    assert card["actionability_status"] == "NOT_ACTIONABLE"
    assert card["productizable_scope"]["status"] == "NOT_PRODUCTIZABLE"
    assert card["automatic_decision"] == "REJECT"


def test_vertical_slice_rejects_unsupported_claim_before_scoring() -> None:
    observations = _actionable_fixture()
    observations[0]["claim_supported"] = False

    with pytest.raises(ValueError, match="unsupported claim"):
        build_vertical_slice(observations)


def test_vertical_slice_keeps_fixture_provenance_out_of_live_product_claims() -> None:
    card = build_vertical_slice(_actionable_fixture())[0]

    assert card["source_versions"] == {"fixture": "deterministic-v1"}
    assert card["policy_version"] == "deterministic-vertical-slice-v1"
    assert card["human_audit"] is None
