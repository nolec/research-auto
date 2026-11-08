"""Controlled adapter contract; fixture annotations are not model/customer evidence."""
from copy import deepcopy
import pytest
from src.extraction import development_slice

TEXT = (
    "An editor exports a transcript. The exporter drops speaker labels. "
    "The editor restores the labels manually before delivery. Time spent is not stated."
)


def test_observation_adapter_contract():
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
    expected = {
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
    original_document, original_extraction = deepcopy(document), deepcopy(extraction)
    converter = getattr(development_slice, "extraction_to_observation", None)
    assert callable(converter), "public extraction_to_observation API is not implemented"
    result = converter(document, extraction)
    assert result == expected
    observation = result["observation"]
    assert observation["annotations"]["money_signal"] is False
    assert observation["annotations"]["problem_signal"] is True
    assert observation["annotations"]["usable_evidence"] is True
    assert observation["annotations"]["money_signal_type"] is None
    assert all(value is None for value in observation["unknowns"].values())
    assert type(observation["evidence"]["start"]) is int
    assert type(observation["evidence"]["end"]) is int
    assert type(observation["annotations"]["confidence"]) is float
    assert document["text"][0:149] == observation["evidence"]["quote"]
    assert document == original_document and extraction == original_extraction

    abstained = {key: None for key in extraction}
    abstained.update(document_id=document["document_id"], abstention_reason=" Insufficient evidence. ")
    original_abstained = deepcopy(abstained)
    assert converter(document, abstained) == {
        "status": "ABSTAINED", "document_id": "local:observation-001",
        "observation": None, "abstention_reason": " Insufficient evidence. ",
    }
    assert abstained == original_abstained and document == original_document

    invalid = {**extraction, "evidence_quote": "X" + TEXT[1:]}
    original_invalid = deepcopy(invalid)
    with pytest.raises(development_slice.ExtractionValidationError) as error:
        converter(document, invalid)
    assert error.value.rule == "SPAN_MISMATCH"
    assert error.value.field == "evidence_quote"
    assert invalid == original_invalid and document == original_document


@pytest.fixture
def metadata_adapter_input():
    document = dict(document_id="local:metadata", source="local_fixture", title="Unicode α😀",
                    text="α😀 editor restores labels", published_at="2026-11-06T00:00:00Z",
                    source_url="https://example.invalid/metadata")
    extraction = dict(document_id=document["document_id"], observation_type="user_problem",
                      actor="editor", problem="labels missing", context="export",
                      consequence="restores labels", evidence_quote=document["text"][2:],
                      evidence_start=2, evidence_end=len(document["text"]), problem_signal=True,
                      money_signal=False, money_signal_type=None, usable_evidence=True,
                      confidence=0.8, abstention_reason=None)
    return document, extraction


def test_optional_metadata_preserves_values_and_default(metadata_adapter_input):
    document, extraction = metadata_adapter_input
    metadata = dict(document_id=document["document_id"], author_hash="saved-author", community="saved-community")
    before = deepcopy((document, extraction, metadata))
    default = development_slice.extraction_to_observation(document, extraction)
    result = development_slice.extraction_to_observation(document, extraction, source_metadata=metadata)
    expanded = result["observation"]["source_metadata"]
    assert expanded == {**default["observation"]["source_metadata"], "author_hash":"saved-author", "community":"saved-community"}
    assert all(v is None for v in result["observation"]["unknowns"].values())
    assert (document, extraction, metadata) == before
    assert development_slice.extraction_to_observation(document, extraction, source_metadata=None) == default
    expanded.pop("author_hash"); expanded.pop("community")
    assert result == default


@pytest.mark.parametrize("author,community", [(None,None), ("author",None), (None,"community")])
def test_optional_metadata_keeps_explicit_null(metadata_adapter_input, author, community):
    document, extraction = metadata_adapter_input
    result = development_slice.extraction_to_observation(document, extraction, source_metadata=dict(
        document_id=document["document_id"], author_hash=author, community=community))
    assert result["observation"]["source_metadata"]["author_hash"] is author
    assert result["observation"]["source_metadata"]["community"] is community


@pytest.mark.parametrize("bad", [[], {}, {"document_id":"other","author_hash":None,"community":None},
    {"document_id":"local:metadata","author_hash":" ","community":None},
    {"document_id":"local:metadata","author_hash":False,"community":None},
    {"document_id":"local:metadata","author_hash":None,"community":42},
    {"document_id":"local:metadata","author_hash":None,"community":None,"extra":None}])
def test_optional_metadata_rejects_invalid(metadata_adapter_input, bad):
    document, extraction = metadata_adapter_input
    with pytest.raises(ValueError):
        development_slice.extraction_to_observation(document, extraction, source_metadata=bad)


def test_optional_metadata_abstention_and_quote_error(metadata_adapter_input):
    document, extraction = metadata_adapter_input
    metadata = dict(document_id=document["document_id"], author_hash=None, community=None)
    abstained = {key:None for key in extraction}
    abstained.update(document_id=document["document_id"], abstention_reason=" insufficient source ")
    result = development_slice.extraction_to_observation(document, abstained, source_metadata=metadata)
    assert result == dict(status="ABSTAINED", document_id=document["document_id"], observation=None,
                         abstention_reason=" insufficient source ")
    with pytest.raises(ValueError):
        development_slice.extraction_to_observation(document, abstained, source_metadata={**metadata,"document_id":"wrong"})
    with pytest.raises(development_slice.ExtractionValidationError) as error:
        development_slice.extraction_to_observation(document, {**extraction,"evidence_quote":"wrong"}, source_metadata=metadata)
    assert error.value.rule == "SPAN_MISMATCH"


def test_source_metadata_authenticity_is_caller_boundary(metadata_adapter_input):
    document, extraction = metadata_adapter_input
    saved = dict(document_id=document["document_id"], author_hash="original-author", community="original-community")
    forged = {**saved, "author_hash":"structurally-valid-forgery"}
    result = development_slice.extraction_to_observation(document, extraction, source_metadata=forged)
    # Structural validation cannot establish source truth; caller must compare.
    with pytest.raises(AssertionError):
        assert all(result["observation"]["source_metadata"][key] == saved[key] for key in ("author_hash", "community"))
    genuine = development_slice.extraction_to_observation(document, extraction, source_metadata=saved)
    assert all(genuine["observation"]["source_metadata"][key] == saved[key] for key in ("author_hash","community"))
