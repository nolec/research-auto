from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping, Sequence

from src.extraction.development_slice import (
    DevelopmentGoldSidecar,
    DevelopmentInference,
    validate_extraction,
)


_SIGNALS = ("problem_signal", "money_signal", "usable_evidence")


@dataclass(frozen=True)
class CalibrationReport:
    metrics: dict[str, dict[str, int | float | None]]
    source_metrics: dict[str, dict[str, object]]
    coverage: float
    abstention_count: int
    invalid_count: int
    receipt: dict[str, object]


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _empty_confusion() -> dict[str, int]:
    return {"tp": 0, "fp": 0, "tn": 0, "fn": 0}


def _record(confusion: dict[str, int], *, predicted: bool, actual: bool) -> None:
    if predicted and actual:
        confusion["tp"] += 1
    elif predicted:
        confusion["fp"] += 1
    elif actual:
        confusion["fn"] += 1
    else:
        confusion["tn"] += 1


def _finish(confusion: Mapping[str, int]) -> dict[str, int | float | None]:
    tp = confusion["tp"]
    fp = confusion["fp"]
    tn = confusion["tn"]
    fn = confusion["fn"]
    predicted_positive = tp + fp
    actual_positive = tp + fn
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "predicted_positive": predicted_positive,
        "actual_positive": actual_positive,
        "precision": tp / predicted_positive if predicted_positive else None,
        "recall": tp / actual_positive if actual_positive else None,
    }


def _validate_inputs(
    inference: DevelopmentInference,
    gold: DevelopmentGoldSidecar,
    outputs: Sequence[Mapping[str, object]],
    run_receipt: Mapping[str, object],
) -> None:
    if _digest(inference.corpus) != inference.receipt.get("inference_corpus_sha256"):
        raise ValueError("inference corpus hash mismatch")
    if _digest(gold.labels) != gold.receipt.get("gold_sidecar_sha256"):
        raise ValueError("gold sidecar hash mismatch")
    if inference.receipt.get("selected_count") != len(inference.corpus):
        raise ValueError("inference selected_count mismatch")
    if gold.receipt.get("selected_count") != len(gold.labels):
        raise ValueError("gold selected_count mismatch")
    if inference.receipt.get("source_spike_reserved_emitted") != 0:
        raise ValueError("inference contains source-spike-reserved records")

    inference_ids = [value.get("document_id") for value in inference.corpus]
    gold_ids = [value.get("document_id") for value in gold.labels]
    output_ids = [value.get("document_id") for value in outputs]
    if len(set(inference_ids)) != len(inference_ids):
        raise ValueError("duplicate inference document IDs")
    if len(set(gold_ids)) != len(gold_ids):
        raise ValueError("duplicate gold document IDs")
    if len(set(output_ids)) != len(output_ids):
        raise ValueError("extraction outputs contain duplicate document IDs")
    if not (len(inference_ids) == len(gold_ids) == len(output_ids)):
        raise ValueError("inference, gold, and output membership length mismatch")
    document_ids = set(inference_ids)
    if set(output_ids) != document_ids or set(gold_ids) != document_ids:
        raise ValueError("inference, gold, and output membership mismatch")

    variant_id = run_receipt.get("variant_id")
    if not isinstance(variant_id, str) or not variant_id.strip():
        raise ValueError("run receipt variant_id must be a non-empty string")
    if run_receipt.get("status") != "success":
        raise ValueError("run receipt status must be success")
    if run_receipt.get("inference_corpus_sha256") != inference.receipt.get(
        "inference_corpus_sha256"
    ):
        raise ValueError("run receipt corpus hash mismatch")
    if run_receipt.get("input_count") != len(inference.corpus):
        raise ValueError("run receipt input count mismatch")
    if run_receipt.get("output_count") != len(outputs):
        raise ValueError("run receipt output count mismatch")
    if run_receipt.get("output_sha256") != _digest(tuple(outputs)):
        raise ValueError("run receipt output hash mismatch")


def evaluate_calibration(
    inference: DevelopmentInference,
    gold: DevelopmentGoldSidecar,
    outputs: Sequence[Mapping[str, object]],
    run_receipt: Mapping[str, object],
) -> CalibrationReport:
    _validate_inputs(inference, gold, outputs, run_receipt)

    documents = {value["document_id"]: value for value in inference.corpus}
    labels = {value["document_id"]: value for value in gold.labels}
    overall = {signal: _empty_confusion() for signal in _SIGNALS}
    sources: dict[str, dict[str, object]] = {}
    abstention_count = 0
    invalid_count = 0
    covered_count = 0

    for output in outputs:
        document_id = output["document_id"]
        document = documents[document_id]
        label = labels[document_id]
        source = str(document["source"])
        source_result = sources.setdefault(
            source,
            {
                "input_count": 0,
                "covered_count": 0,
                "abstention_count": 0,
                "invalid_count": 0,
                **{signal: _empty_confusion() for signal in _SIGNALS},
            },
        )
        source_result["input_count"] += 1

        valid = True
        try:
            validate_extraction(document, output)
        except ValueError:
            valid = False
            invalid_count += 1
            source_result["invalid_count"] += 1

        abstained = valid and output.get("abstention_reason") is not None
        if abstained:
            abstention_count += 1
            source_result["abstention_count"] += 1
        covered = valid and not abstained
        if covered:
            covered_count += 1
            source_result["covered_count"] += 1

        for signal in _SIGNALS:
            predicted = bool(output.get(signal)) if covered else False
            actual = label.get(signal)
            if not isinstance(actual, bool):
                raise ValueError(f"gold {signal} must be boolean")
            _record(overall[signal], predicted=predicted, actual=actual)
            _record(source_result[signal], predicted=predicted, actual=actual)

    metrics = {signal: _finish(confusion) for signal, confusion in overall.items()}
    source_metrics: dict[str, dict[str, object]] = {}
    for source, values in sorted(sources.items()):
        input_count = int(values["input_count"])
        source_metrics[source] = {
            "input_count": input_count,
            "coverage": int(values["covered_count"]) / input_count,
            "abstention_count": values["abstention_count"],
            "invalid_count": values["invalid_count"],
            **{signal: _finish(values[signal]) for signal in _SIGNALS},
        }

    coverage = covered_count / len(inference.corpus) if inference.corpus else 0.0
    receipt = {
        "variant_id": run_receipt["variant_id"],
        "inference_corpus_sha256": inference.receipt["inference_corpus_sha256"],
        "gold_sidecar_sha256": gold.receipt["gold_sidecar_sha256"],
        "upstream_run_receipt_sha256": _digest(run_receipt),
        "input_count": len(inference.corpus),
        "covered_count": covered_count,
        "abstention_count": abstention_count,
        "invalid_count": invalid_count,
        "output_sha256": run_receipt["output_sha256"],
        "report_sha256": _digest(
            {"metrics": metrics, "source_metrics": source_metrics}
        ),
        "status": "success",
    }
    return CalibrationReport(
        metrics,
        source_metrics,
        coverage,
        abstention_count,
        invalid_count,
        receipt,
    )
