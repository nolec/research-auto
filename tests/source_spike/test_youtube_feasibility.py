from __future__ import annotations

import json
from pathlib import Path

from src.source_spike.feasibility import validate_feasibility_decision


ROOT = Path(__file__).resolve().parents[2]
DECISION_PATH = ROOT / "config/source-spike/feasibility/youtube.json"
DOCUMENT_PATH = ROOT / "docs/decisions/youtube-source-feasibility.md"


def load_decision() -> dict:
    return json.loads(DECISION_PATH.read_text(encoding="utf-8"))


def test_youtube_decision_is_valid_and_not_eligible() -> None:
    decision = load_decision()

    assert validate_feasibility_decision(decision) == []
    assert decision["source"] == "youtube"
    assert decision["status"] == "NOT_ELIGIBLE"
    assert decision["next_action"] == "replace_source"
    assert decision["decision_version"] == "2.0.0"
    assert decision["supersedes_decision_sha256"] == (
        "65419f96c7858d5455b01305270c1afd529d9ed460f0cb81e7314bc092a214a3"
    )
    assert [item["name"] for item in decision["data_classes"]] == [
        "comment_text",
        "comment_id",
        "video_id",
        "canonical_url",
        "author_derived_identifier",
    ]


def test_youtube_decision_preserves_all_blocking_boundaries() -> None:
    decision = load_decision()
    gates = {item["id"]: item["status"] for item in decision["required_gates"]}

    assert gates == {
        "retention": "fail",
        "provenance": "fail",
        "author_independence": "unresolved",
        "deletion": "unresolved",
        "reproducibility": "fail",
    }
    assert set(decision["blockers"]) == {
        "B1_30_DAY_RETENTION_CONFLICTS_WITH_90_DAY_EVIDENCE",
        "B2_STABLE_AUTHOR_DERIVATION_NOT_EXPLICITLY_ALLOWED",
        "B3_REFRESH_CHANGES_OR_REMOVES_FROZEN_EVIDENCE",
        "B4_NO_EXECUTABLE_DELETION_AND_REFRESH_PATH",
    }


def test_youtube_policy_uses_only_official_google_sources() -> None:
    evidence = load_decision()["policy_evidence"]
    youtube_evidence = [item for item in evidence if item["id"].startswith("YT-POLICY-")]

    assert len(evidence) >= 3
    assert len(youtube_evidence) == 3
    assert all(item["url"].startswith("https://developers.google.com/youtube/") for item in youtube_evidence)
    assert all(item["checked_at"] == "2026-08-17T00:00:00Z" for item in evidence)


def test_youtube_document_matches_machine_verdict_and_blockers() -> None:
    decision = load_decision()
    document = DOCUMENT_PATH.read_text(encoding="utf-8")

    assert "VERDICT: NOT_ELIGIBLE" in document
    assert "YouTube adapter를 구현하지 않는다" in document
    for blocker in decision["blockers"]:
        assert blocker in document
    labels = {
        "retention": "Retention",
        "provenance": "Provenance",
        "author_independence": "Author independence",
        "deletion": "Deletion",
        "reproducibility": "Reproducibility",
    }
    for gate in decision["required_gates"]:
        assert f"| {labels[gate['id']]} | {gate['status']} |" in document
