"""Synthetic handoff contract; no model or customer-value claim."""
from copy import deepcopy
import importlib
import importlib.util

import pytest

from src.extraction import development_slice, opportunity_slice, model_card_handoff

TEXT = (
    "An editor exports a transcript. The exporter drops speaker labels. "
    "The editor restores the labels manually before delivery. Time spent is not stated."
)
MISSING = [
    "problem_key", "productizable_scope", "evidence.evidence_id",
    "evidence.author_hash", "evidence.community", "evidence.evidence_group_id",
    "evidence.kind", "evidence.interpretation",
]


def _inputs():
    document = {
        "document_id": "local:observation-001", "source": "local_fixture",
        "title": "Transcript export fixture", "text": TEXT,
        "published_at": "2026-11-06T00:00:00Z",
        "source_url": "https://example.invalid/observation-001",
    }
    extraction = {
        "document_id": "local:observation-001", "observation_type": "user_problem",
        "actor": "An editor", "problem": "The exporter drops speaker labels.",
        "context": "An editor exports a transcript.",
        "consequence": "The editor restores the labels manually before delivery.",
        "evidence_quote": TEXT, "evidence_start": 0, "evidence_end": 149,
        "problem_signal": True, "money_signal": False, "money_signal_type": None,
        "usable_evidence": True, "confidence": 0.8, "abstention_reason": None,
    }
    return document, extraction


def _snapshot():
    return {
        "status": "OBSERVATION", "document_id": "local:observation-001",
        "observation": {
            "source_metadata": {
                "source": "local_fixture", "title": "Transcript export fixture",
                "source_url": "https://example.invalid/observation-001",
                "published_at": "2026-11-06T00:00:00Z",
            },
            "extracted": {
                "actor": "An editor", "problem": "The exporter drops speaker labels.",
                "context": "An editor exports a transcript.",
                "consequence": "The editor restores the labels manually before delivery.",
            },
            "evidence": {"quote": TEXT, "start": 0, "end": 149},
            "annotations": {
                "observation_type": "user_problem", "problem_signal": True,
                "money_signal": False, "money_signal_type": None,
                "usable_evidence": True, "confidence": 0.8,
            },
            "unknowns": {
                "time_spent_seconds": None, "independent_author_count": None,
                "recurrence_count": None, "actual_payment": None,
                "willingness_to_pay": None,
            },
        },
        "abstention_reason": None,
    }


def _api(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("downstream cluster/judgment/render/publish was called")

    # Install before importing the new module, including potential imported aliases.
    for module, names in [
        (opportunity_slice, (
            "build_vertical_slice", "_grouped_observations", "_build_card",
            "evaluate_product_promotion", "render_card_markdown",
        )),
        (model_card_handoff, (
            "execute_same_process_card_handoff", "_execute_reserved_handoff",
            "_publish_artifacts",
        )),
    ]:
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    name = "src.extraction.observation_handoff"
    assert importlib.util.find_spec(name) is not None, "public handoff module is not implemented"
    module = importlib.import_module(name)
    # Reload under the sentinels on subsequent tests as well.
    module = importlib.reload(module)
    api = getattr(module, "prepare_cluster_handoff", None)
    assert callable(api), "public prepare_cluster_handoff is not implemented"
    return module, api


def _record_conversion(monkeypatch, module):
    original = development_slice.extraction_to_observation
    captured = []

    def recorded(document, extraction):
        value = original(document, extraction)
        captured.append(value)
        return value

    monkeypatch.setattr(development_slice, "extraction_to_observation", recorded)
    if hasattr(module, "extraction_to_observation"):
        monkeypatch.setattr(module, "extraction_to_observation", recorded)
    return captured


def test_missing_information_preserves_snapshot_without_downstream(monkeypatch):
    module, api = _api(monkeypatch)
    captured = _record_conversion(monkeypatch, module)
    document, extraction = _inputs()
    before = deepcopy((document, extraction))
    result = api(document, extraction)
    expected = {
        "status": "NEEDS_INFORMATION", "document_id": "local:observation-001",
        "input_snapshot": _snapshot(), "consumer_input": None, "cards": None,
        "missing_fields": MISSING, "downstream_status": "NOT_RUN",
    }
    assert result == expected
    assert set(result) == set(expected)
    assert result["consumer_input"] is None and result["cards"] is None
    assert len(captured) == 1
    assert captured[0] == _snapshot()
    assert result["input_snapshot"] is not captured[0]
    obs = result["input_snapshot"]["observation"]
    assert all(value is None for value in obs["unknowns"].values())
    assert obs["annotations"]["money_signal"] is False
    assert obs["annotations"]["money_signal_type"] is None
    assert type(obs["evidence"]["start"]) is int
    assert type(obs["evidence"]["end"]) is int
    assert type(obs["annotations"]["confidence"]) is float
    assert document["text"][obs["evidence"]["start"]:obs["evidence"]["end"]] == obs["evidence"]["quote"]
    assert (document, extraction) == before
    obs["unknowns"]["actual_payment"] = 1
    obs["evidence"]["quote"] = "changed only in returned snapshot"
    assert captured[0] == _snapshot()
    assert (document, extraction) == before
    result["missing_fields"].append("caller-only")
    again = api(document, extraction)
    assert again["missing_fields"] == MISSING
    assert again["input_snapshot"] == _snapshot()


def test_abstention_is_distinct_and_never_calls_downstream(monkeypatch):
    module, api = _api(monkeypatch)
    captured = _record_conversion(monkeypatch, module)
    document, normal = _inputs()
    extraction = {key: None for key in normal}
    extraction.update(document_id=document["document_id"], abstention_reason=" Insufficient evidence. ")
    before = deepcopy((document, extraction))
    snapshot = {
        "status": "ABSTAINED", "document_id": "local:observation-001",
        "observation": None, "abstention_reason": " Insufficient evidence. ",
    }
    assert api(document, extraction) == {
        "status": "ABSTAINED", "document_id": "local:observation-001",
        "input_snapshot": snapshot, "consumer_input": None, "cards": None,
        "missing_fields": [], "downstream_status": "NOT_RUN",
    }
    assert captured == [snapshot]
    assert (document, extraction) == before


def test_invalid_quote_propagates_and_never_calls_downstream(monkeypatch):
    module, api = _api(monkeypatch)
    document, extraction = _inputs()
    extraction["evidence_quote"] = "X" + TEXT[1:]
    before = deepcopy((document, extraction))
    with pytest.raises(development_slice.ExtractionValidationError) as error:
        api(document, extraction)
    assert error.value.rule == "SPAN_MISMATCH"
    assert error.value.field == "evidence_quote"
    assert (document, extraction) == before
