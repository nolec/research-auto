from __future__ import annotations

import json
import socket
from pathlib import Path

from src.source_spike.feasibility import validate_feasibility_decision


ROOT = Path(__file__).resolve().parents[2]
DECISION_PATH = ROOT / "config/source-spike/feasibility/reddit.json"
DOCUMENT_PATH = ROOT / "docs/decisions/reddit-source-feasibility.md"


def load_decision() -> dict:
    return json.loads(DECISION_PATH.read_text(encoding="utf-8"))


def test_reddit_is_blocked_without_assuming_permanent_ineligibility() -> None:
    decision = load_decision()

    assert validate_feasibility_decision(decision) == []
    assert decision["authorization_status"] == "unverified"
    assert decision["eligibility"] == {
        "current_collection": "NOT_ELIGIBLE",
        "future_commercial_reuse": "NOT_ELIGIBLE",
    }
    assert decision["next_action"] == "seek_compliance_clearance"
    assert decision["operational_next_action"] == "select_replacement_source"
    assert decision["recheck_conditions"]


def test_reddit_ai_modes_are_not_collapsed() -> None:
    modes = load_decision()["intended_use"]["ai_processing"]

    assert modes["model_training"] == "not_used"
    assert modes["fine_tuning"] == "not_used"
    assert modes["embedding_or_indexing"] == "planned"
    assert modes["llm_inference_extraction"] == "planned"
    assert modes["derived_output_storage"] == "planned"


def test_reddit_decision_load_is_network_free(monkeypatch) -> None:
    def reject_network(*args, **kwargs):
        raise AssertionError("feasibility validation must not open a socket")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    assert validate_feasibility_decision(load_decision()) == []


def test_reddit_document_matches_dual_verdict() -> None:
    document = DOCUMENT_PATH.read_text(encoding="utf-8")

    assert "CURRENT COLLECTION: NOT_ELIGIBLE" in document
    assert "FUTURE COMMERCIAL REUSE: NOT_ELIGIBLE" in document
    assert "seek_compliance_clearance" in document
    assert "select_replacement_source" in document
