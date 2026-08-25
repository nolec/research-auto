from __future__ import annotations

import json
from hashlib import sha256

import pytest

from src.extraction.calibration_evaluator import evaluate_calibration
from src.extraction.development_slice import (
    DevelopmentGoldSidecar,
    DevelopmentInference,
)


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _document(document_id: str, source: str, text: str) -> dict[str, object]:
    return {
        "document_id": document_id,
        "source": source,
        "title": document_id,
        "text": text,
        "published_at": "2026-01-01T00:00:00Z",
        "source_url": f"https://example.com/{document_id}",
    }


def _output(
    document: dict[str, object],
    *,
    problem: bool,
    money: bool,
    evidence: bool,
) -> dict[str, object]:
    text = str(document["text"])
    return {
        "document_id": document["document_id"],
        "observation_type": "user_problem",
        "actor": "author",
        "problem": text,
        "context": str(document["title"]),
        "consequence": text,
        "evidence_quote": text,
        "evidence_start": 0,
        "evidence_end": len(text),
        "problem_signal": problem,
        "money_signal": money,
        "money_signal_type": "purchase" if money else None,
        "usable_evidence": evidence,
        "confidence": 0.5,
        "abstention_reason": None,
    }


def _abstention(document_id: str) -> dict[str, object]:
    fields = (
        "observation_type",
        "actor",
        "problem",
        "context",
        "consequence",
        "evidence_quote",
        "evidence_start",
        "evidence_end",
        "problem_signal",
        "money_signal",
        "money_signal_type",
        "usable_evidence",
        "confidence",
    )
    return {
        "document_id": document_id,
        **{field: None for field in fields},
        "abstention_reason": "no supported extraction",
    }


def _inputs() -> tuple[DevelopmentInference, DevelopmentGoldSidecar]:
    corpus = (
        _document("github:1", "github", "Failure one."),
        _document("github:2", "github", "Normal update."),
        _document("steam:1", "steam", "Purchase failure."),
        _document("steam:2", "steam", "Neutral review."),
    )
    labels = (
        {
            "document_id": "github:1",
            "problem_signal": True,
            "money_signal": False,
            "money_signal_type": None,
            "usable_evidence": True,
            "noise": False,
        },
        {
            "document_id": "github:2",
            "problem_signal": False,
            "money_signal": False,
            "money_signal_type": None,
            "usable_evidence": False,
            "noise": False,
        },
        {
            "document_id": "steam:1",
            "problem_signal": True,
            "money_signal": True,
            "money_signal_type": "purchase",
            "usable_evidence": True,
            "noise": False,
        },
        {
            "document_id": "steam:2",
            "problem_signal": False,
            "money_signal": False,
            "money_signal_type": None,
            "usable_evidence": False,
            "noise": False,
        },
    )
    inference = DevelopmentInference(
        corpus,
        {
            "inference_corpus_sha256": _digest(corpus),
            "selected_count": 4,
            "source_spike_reserved_emitted": 0,
        },
    )
    gold = DevelopmentGoldSidecar(
        labels,
        {"gold_sidecar_sha256": _digest(labels), "selected_count": 4},
    )
    return inference, gold


def _run_receipt(
    inference: DevelopmentInference,
    outputs: tuple[dict[str, object], ...],
    *,
    variant_id: str = "rule_v1",
) -> dict[str, object]:
    return {
        "variant_id": variant_id,
        "status": "success",
        "inference_corpus_sha256": inference.receipt["inference_corpus_sha256"],
        "input_count": len(inference.corpus),
        "output_count": len(outputs),
        "output_sha256": _digest(outputs),
    }


def test_evaluator_reports_confusion_coverage_and_source_breakdown() -> None:
    inference, gold = _inputs()
    outputs = (
        _output(inference.corpus[0], problem=True, money=False, evidence=True),
        _output(inference.corpus[1], problem=True, money=False, evidence=True),
        _output(inference.corpus[2], problem=True, money=False, evidence=True),
        _abstention("steam:2"),
    )

    report = evaluate_calibration(inference, gold, outputs, _run_receipt(inference, outputs))

    assert report.metrics["problem_signal"] == {
        "tp": 2,
        "fp": 1,
        "tn": 1,
        "fn": 0,
        "predicted_positive": 3,
        "actual_positive": 2,
        "precision": pytest.approx(2 / 3),
        "recall": 1.0,
    }
    assert report.metrics["money_signal"]["precision"] is None
    assert report.metrics["money_signal"]["recall"] == 0.0
    assert report.coverage == 0.75
    assert report.abstention_count == 1
    assert report.invalid_count == 0
    assert report.source_metrics["github"]["problem_signal"]["fp"] == 1
    assert report.source_metrics["steam"]["money_signal"]["fn"] == 1
    assert report.receipt["input_count"] == 4
    assert report.receipt["variant_id"] == "rule_v1"


def test_evaluator_counts_invalid_output_as_non_covered_negative_prediction() -> None:
    inference, gold = _inputs()
    invalid = _output(inference.corpus[0], problem=True, money=False, evidence=True)
    invalid["evidence_quote"] = "not in source"
    outputs = (
        invalid,
        _abstention("github:2"),
        _abstention("steam:1"),
        _abstention("steam:2"),
    )

    report = evaluate_calibration(
        inference,
        gold,
        outputs,
        _run_receipt(inference, outputs, variant_id="model_v1"),
    )

    assert report.invalid_count == 1
    assert report.coverage == 0.0
    assert report.metrics["problem_signal"]["fn"] == 2
    assert report.metrics["usable_evidence"]["fn"] == 2


def test_evaluator_rejects_membership_duplicates_and_hash_mismatch() -> None:
    inference, gold = _inputs()
    valid = tuple(_abstention(str(document["document_id"])) for document in inference.corpus)

    with pytest.raises(ValueError, match="membership"):
        evaluate_calibration(
            inference, gold, valid[:-1], _run_receipt(inference, valid[:-1])
        )

    duplicated = (*valid[:-1], {**valid[-1], "document_id": "github:1"})
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_calibration(
            inference, gold, duplicated, _run_receipt(inference, duplicated)
        )

    bad_gold = DevelopmentGoldSidecar(
        gold.labels,
        {**gold.receipt, "gold_sidecar_sha256": "0" * 64},
    )
    with pytest.raises(ValueError, match="gold sidecar hash"):
        evaluate_calibration(inference, bad_gold, valid, _run_receipt(inference, valid))


def test_evaluator_rejects_duplicate_inference_and_gold_ids() -> None:
    inference, gold = _inputs()
    outputs = tuple(_abstention(str(document["document_id"])) for document in inference.corpus)

    duplicate_corpus = (*inference.corpus[:-1], inference.corpus[0])
    duplicate_inference = DevelopmentInference(
        duplicate_corpus,
        {
            **inference.receipt,
            "inference_corpus_sha256": _digest(duplicate_corpus),
        },
    )
    with pytest.raises(ValueError, match="duplicate inference"):
        evaluate_calibration(
            duplicate_inference,
            gold,
            outputs,
            _run_receipt(duplicate_inference, outputs),
        )

    duplicate_labels = (*gold.labels[:-1], gold.labels[0])
    duplicate_gold = DevelopmentGoldSidecar(
        duplicate_labels,
        {**gold.receipt, "gold_sidecar_sha256": _digest(duplicate_labels)},
    )
    with pytest.raises(ValueError, match="duplicate gold"):
        evaluate_calibration(
            inference, duplicate_gold, outputs, _run_receipt(inference, outputs)
        )


def test_evaluator_rejects_unbound_or_tampered_run_receipt() -> None:
    inference, gold = _inputs()
    outputs = tuple(_abstention(str(document["document_id"])) for document in inference.corpus)
    receipt = _run_receipt(inference, outputs)

    with pytest.raises(ValueError, match="output hash"):
        evaluate_calibration(
            inference,
            gold,
            outputs,
            {**receipt, "output_sha256": "0" * 64},
        )

    with pytest.raises(ValueError, match="variant_id"):
        evaluate_calibration(
            inference,
            gold,
            outputs,
            {**receipt, "variant_id": ""},
        )
