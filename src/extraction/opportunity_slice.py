"""Deterministic, fixture-only Opportunity Card vertical slice.

This module deliberately consumes caller-supplied fixture observations.  It is not
connected to a provider, a source-selection decision, or a production ranking run.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence

from src.contracts.validation import validate_contract


_ROOT = Path(__file__).resolve().parents[2]
_CARD_SCHEMA = json.loads((_ROOT / "schemas" / "opportunity-card.schema.json").read_text())
_POLICY_VERSION = "deterministic-vertical-slice-v1"
_FIXTURE_SOURCE_VERSIONS = {"fixture": "deterministic-v1"}
_FIXTURE_TIME = "2026-09-03T00:00:00Z"


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{sha256(value.encode()).hexdigest()[:16]}"


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _evidence(observation: Mapping[str, object]) -> dict[str, object]:
    value = observation.get("evidence")
    if not isinstance(value, Mapping):
        raise ValueError("fixture observation requires evidence")
    return dict(value)


def _grouped_observations(
    observations: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for observation in observations:
        if observation.get("claim_supported", True) is not True:
            raise ValueError("unsupported claim cannot enter deterministic ranking")
        key = _require_string(observation.get("problem_key"), "problem_key")
        grouped.setdefault(" ".join(key.casefold().split()), []).append(observation)
    if not grouped:
        raise ValueError("vertical slice requires at least one fixture observation")
    return grouped


def _evidence_by_kind(
    evidence: Sequence[dict[str, object]], name: str | tuple[str, ...]
) -> list[dict[str, object]]:
    kinds = {name} if isinstance(name, str) else set(name)
    return [value for value in evidence if value.get("kind") in kinds]


def _unique_strings(values: Sequence[object]) -> list[str]:
    return sorted({value for value in values if isinstance(value, str) and value})


def _cluster_string(
    observations: Sequence[Mapping[str, object]], field: str
) -> str:
    values = {_require_string(observation.get(field), field) for observation in observations}
    if len(values) != 1:
        raise ValueError(f"cluster {field} must be consistent")
    return values.pop()


def _cluster_delivery_mode(observations: Sequence[Mapping[str, object]]) -> str:
    values = {observation.get("delivery_mode", "UNKNOWN") for observation in observations}
    if values - {"SOFTWARE", "SERVICE", "HYBRID", "UNKNOWN"}:
        raise ValueError("delivery_mode is invalid")
    if len(values) != 1:
        raise ValueError("cluster delivery_mode must be consistent")
    return str(values.pop())


def _cluster_not_productizable(observations: Sequence[Mapping[str, object]]) -> bool:
    values = {observation["productizable"] for observation in observations if "productizable" in observation}
    if any(not isinstance(value, bool) for value in values):
        raise ValueError("productizable must be boolean when supplied")
    return False in values


def _conservative_group_count(observations: Sequence[Mapping[str, object]]) -> int:
    """Merge fixture evidence whenever an independence signal overlaps.

    A shared author, supplied source group, thread/event/window key, or identical
    quote is treated as one group.  The policy intentionally prefers under-counting
    over representing correlated observations as independent evidence.
    """
    candidates = [
        observation
        for observation in observations
        if _evidence(observation).get("kind") not in {"counter", "blocker"}
    ]
    parent = list(range(len(candidates)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    seen: dict[tuple[str, str], int] = {}
    for index, observation in enumerate(candidates):
        evidence = _evidence(observation)
        markers = [
            ("author", _require_string(evidence.get("author_hash"), "author_hash")),
            (
                "source_group",
                _require_string(evidence.get("evidence_group_id"), "evidence_group_id"),
            ),
            ("quote", " ".join(_require_string(evidence.get("quote"), "quote").casefold().split())),
        ]
        for field in ("thread_key", "event_key", "time_window_key"):
            value = observation.get(field)
            if isinstance(value, str) and value:
                markers.append((field, value))
        for marker in markers:
            previous = seen.setdefault(marker, index)
            union(index, previous)
    return len({find(index) for index in range(len(candidates))})


def _build_card(problem_key: str, observations: Sequence[Mapping[str, object]]) -> dict[str, object]:
    evidence = [_evidence(observation) for observation in observations]
    actor = _cluster_string(observations, "observed_actor")
    statement = _cluster_string(observations, "problem_statement")
    scope_summary = _cluster_string(observations, "productizable_scope")
    delivery_mode = _cluster_delivery_mode(observations)

    supporting = [
        value for value in evidence if value.get("kind") not in {"counter", "blocker"}
    ]
    counters = _evidence_by_kind(evidence, "counter")
    blockers = _evidence_by_kind(evidence, "blocker")
    loss = _evidence_by_kind(evidence, "loss")
    money = _evidence_by_kind(evidence, ("money", "willingness_to_pay"))
    alternatives = _evidence_by_kind(evidence, "alternative")
    channels = _evidence_by_kind(evidence, "customer_channel")
    gaps = _evidence_by_kind(evidence, "solution_gap")
    authors = _unique_strings([value.get("author_hash") for value in supporting])
    group_count = _conservative_group_count(observations)
    for observation, value in zip(observations, evidence, strict=True):
        if observation.get("counter_critical") is True and value.get("kind") != "counter":
            raise ValueError("counter_critical requires counter evidence")
    critical_counter = any(
        observation.get("counter_critical") is True and value.get("kind") == "counter"
        for observation, value in zip(observations, evidence, strict=True)
    )
    unknown_independence = any(
        observation.get("independence_unknown") is True for observation in observations
    )

    evidence_reasons: list[str] = []
    if critical_counter:
        evidence_status = "CONFLICTING_EVIDENCE"
        evidence_reasons.append("critical counter-evidence")
    elif unknown_independence:
        evidence_status = "NEEDS_REVIEW"
        evidence_reasons.append("independence is unknown")
    elif (
        len(authors) >= 5
        and group_count >= 3
        and len(supporting) >= 10
        and len(loss) >= 2
        and len(money) >= 2
    ):
        evidence_status = "EVIDENCE_BACKED"
        evidence_reasons.append("evidence thresholds passed")
    else:
        evidence_status = "INSUFFICIENT_EVIDENCE"
        evidence_reasons.append("evidence thresholds not met")

    explicit_not_productizable = _cluster_not_productizable(observations)
    if blockers or explicit_not_productizable:
        actionability_status = "NOT_ACTIONABLE"
        actionability_reason = "known blocker or non-productizable scope"
    elif alternatives and channels and len(gaps) >= 2 and delivery_mode != "UNKNOWN":
        actionability_status = "ACTIONABLE"
        actionability_reason = "actionability thresholds passed"
    else:
        actionability_status = "UNKNOWN"
        actionability_reason = "actionability evidence is incomplete"

    eligible = evidence_status == "EVIDENCE_BACKED" and actionability_status == "ACTIONABLE"
    if critical_counter or blockers or explicit_not_productizable:
        automatic_decision = "REJECT"
    elif eligible:
        automatic_decision = "REVIEW"
    else:
        automatic_decision = "HOLD"
    score = min(100, 10 * len(money) + 10 * len(loss) + 8 * len(gaps) + 4 * group_count) if eligible else 0
    uncertainties = ["Fixture-only output is not live product evidence."]
    if unknown_independence:
        uncertainties.append("Evidence independence is unknown.")
    if not eligible:
        uncertainties.append("Candidate is ineligible for review-value ranking.")

    card = {
        "card_id": _stable_id("card", problem_key),
        "cluster_id": _stable_id("cluster", problem_key),
        "observed_actor": actor,
        "inferred_customer_segment": None,
        "problem_statement": statement,
        "evidence_status": evidence_status,
        "actionability_status": actionability_status,
        "review_value_score": score,
        "independent_author_count": len(authors),
        "independent_evidence_group_count": group_count,
        "recent_case_count": len(supporting),
        "growth_status": "UNKNOWN",
        "loss_evidence": loss,
        "money_evidence": money,
        "current_alternatives": _unique_strings(
            [value.get("interpretation") for value in alternatives]
        ),
        "current_solution_evidence": alternatives,
        "customer_channel_evidence": channels,
        "productizable_scope": {
            "status": "NOT_PRODUCTIZABLE" if explicit_not_productizable else "PRODUCTIZABLE" if delivery_mode != "UNKNOWN" else "UNKNOWN",
            "delivery_mode": delivery_mode,
            "summary": scope_summary,
        },
        "known_blockers": blockers,
        "blocker_assessment": {
            "status": "BLOCKED" if blockers else "NONE_FOUND",
            "reasons": ["Fixture contains a blocker."] if blockers else ["No fixture blocker supplied."],
        },
        "solution_gap_evidence": gaps,
        "supporting_evidence": supporting,
        "counter_evidence": counters,
        "counter_assessment": {
            "status": "CRITICAL" if critical_counter else "NONE_CRITICAL",
            "reasons": ["Critical fixture counter-evidence supplied."] if critical_counter else ["No critical fixture counter-evidence supplied."],
        },
        "uncertainties": uncertainties,
        "automatic_decision": automatic_decision,
        "decision_reasons": evidence_reasons + [actionability_reason],
        "human_audit": None,
        "source_versions": _FIXTURE_SOURCE_VERSIONS,
        "model_version": "fixture-only",
        "prompt_version": "fixture-only",
        "policy_version": _POLICY_VERSION,
        "generated_at": _FIXTURE_TIME,
    }
    validate_contract(card, _CARD_SCHEMA)
    return card


def build_vertical_slice(
    observations: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Build deterministic fixture-only cards without a provider or source corpus."""
    return [
        _build_card(problem_key, values)
        for problem_key, values in sorted(_grouped_observations(observations).items())
    ]


def render_card_markdown(card: Mapping[str, object]) -> str:
    """Render the same decision surface carried by the machine-readable Card."""
    lines = [
        f"# {card['problem_statement']}",
        "",
        f"- Card: {card['card_id']}",
        f"- Cluster: {card['cluster_id']}",
        f"- Evidence: {card['evidence_status']}",
        f"- Actionability: {card['actionability_status']}",
        f"- Review value: {card['review_value_score']}",
        f"- Provenance: {card['model_version']} / {card['policy_version']}",
        f"- Decision: {card['automatic_decision']}",
        "",
        "## Decision reasons",
    ]
    lines.extend(f"- {reason}" for reason in card["decision_reasons"])
    lines.extend(("", "## Uncertainties"))
    lines.extend(f"- {uncertainty}" for uncertainty in card["uncertainties"])
    for heading, field in (
        ("Supporting evidence", "supporting_evidence"),
        ("Counter evidence", "counter_evidence"),
        ("Blocker evidence", "known_blockers"),
    ):
        lines.extend(("", f"## {heading}"))
        evidence = card[field]
        if not evidence:
            lines.append("- None")
            continue
        lines.extend(
            f"- {value['evidence_id']}: {value['source_url']}"
            for value in evidence
        )
    return "\n".join(lines)
