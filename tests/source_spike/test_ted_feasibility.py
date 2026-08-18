from __future__ import annotations

import json
import socket
from pathlib import Path

from src.source_spike.feasibility import validate_feasibility_decision


ROOT = Path(__file__).resolve().parents[2]
DECISION_PATH = ROOT / "config/source-spike/feasibility/ted.json"
DOCUMENT_PATH = ROOT / "docs/decisions/ted-source-feasibility.md"


def load_decision() -> dict:
    return json.loads(DECISION_PATH.read_text(encoding="utf-8"))


def test_ted_passes_both_horizons_before_adapter_work() -> None:
    decision = load_decision()

    assert validate_feasibility_decision(decision) == []
    assert decision["source"] == "ted"
    assert decision["status"] == "PASS"
    assert decision["authorization_status"] == "verified"
    assert decision["eligibility"] == {
        "current_collection": "PASS",
        "future_commercial_reuse": "PASS",
    }
    assert decision["blockers"] == []
    assert decision["next_action"] == "probe_capacity"
    assert decision["operational_next_action"] == "probe_capacity"


def test_ted_ai_modes_and_contact_exclusion_are_explicit() -> None:
    decision = load_decision()
    modes = decision["intended_use"]["ai_processing"]

    assert modes == {
        "model_training": "not_used",
        "fine_tuning": "not_used",
        "embedding_or_indexing": "planned",
        "llm_inference_extraction": "planned",
        "derived_output_storage": "planned",
    }
    assert {item["name"] for item in decision["data_classes"]} == {
        "notice_title_and_description",
        "notice_identifier",
        "procedure_identifier",
        "canonical_notice_url",
        "buyer_organisation_derived_identifier",
    }


def test_ted_decision_load_is_network_free(monkeypatch) -> None:
    def reject_network(*args, **kwargs):
        raise AssertionError("feasibility validation must not open a socket")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    assert validate_feasibility_decision(load_decision()) == []


def test_ted_document_matches_conditional_selection_boundary() -> None:
    document = DOCUMENT_PATH.read_text(encoding="utf-8")

    assert "CURRENT COLLECTION: PASS" in document
    assert "FUTURE COMMERCIAL REUSE: PASS" in document
    assert "preferred candidate" in document
    assert "capacity probe" in document
    assert "does not authorize" in document
