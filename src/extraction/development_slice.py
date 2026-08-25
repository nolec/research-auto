from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from src.source_spike.analysis_bundle import dataset_sha256
from src.source_spike.review_packet import validate_review_packet_bundle


_EXPECTED_SOURCES = frozenset({"github", "stackexchange", "steam", "ted"})
_OBSERVATION_TYPES = frozenset(
    {"user_problem", "product_feedback", "procurement_requirement"}
)
_MONEY_TYPES = frozenset(
    {
        "purchase",
        "subscription",
        "outsourcing",
        "labor_cost",
        "loss",
        "willingness_to_pay",
        "price_complaint",
        "replacement_search",
    }
)
_INFERENCE_FIELDS = (
    "document_id",
    "source",
    "title",
    "text",
    "published_at",
    "source_url",
)
_GOLD_FIELDS = (
    "document_id",
    "problem_signal",
    "money_signal",
    "money_signal_type",
    "usable_evidence",
    "noise",
)
_EXTRACTION_FIELDS = frozenset(
    {
        "document_id",
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
        "abstention_reason",
    }
)


@dataclass(frozen=True)
class SourceArtifacts:
    qualified_run: Path
    review_root: Path
    primary_submission: Path


@dataclass(frozen=True)
class DevelopmentInference:
    corpus: tuple[dict[str, object], ...]
    receipt: dict[str, object]


@dataclass(frozen=True)
class DevelopmentGoldSidecar:
    labels: tuple[dict[str, object], ...]
    receipt: dict[str, object]


@dataclass(frozen=True)
class _Projection:
    inference: tuple[dict[str, object], ...]
    gold: tuple[dict[str, object], ...]
    source_counts: dict[str, int]
    source_dataset_hashes: dict[str, str]
    source_qualification_hashes: dict[str, str]
    source_packet_manifest_hashes: dict[str, str]
    reserved_ids: frozenset[str]


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _load_json_snapshot(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"JSON snapshot must contain an object: {path}")
    return value, sha256(raw).hexdigest()


def _validate_gold_label(source: str, value: Mapping[str, object]) -> None:
    for field in ("problem_signal", "money_signal", "usable_evidence", "noise"):
        if not isinstance(value.get(field), bool):
            raise ValueError(f"{source} {field} must be boolean")
    money_type = value.get("money_signal_type")
    if value["money_signal"] is False and money_type is not None:
        raise ValueError(f"{source} money_signal_type must be null when money_signal is false")
    if value["money_signal"] is True and money_type not in _MONEY_TYPES:
        raise ValueError(f"{source} money_signal_type is invalid")


def _project_development(
    sources: Mapping[str, SourceArtifacts],
) -> _Projection:
    if set(sources) != _EXPECTED_SOURCES:
        raise ValueError("development slice requires github, stackexchange, steam, and ted")

    inference: list[dict[str, object]] = []
    gold: list[dict[str, object]] = []
    source_counts: dict[str, int] = {}
    source_dataset_hashes: dict[str, str] = {}
    source_qualification_hashes: dict[str, str] = {}
    source_packet_manifest_hashes: dict[str, str] = {}
    reserved_ids: set[str] = set()

    for source in sorted(sources):
        paths = sources[source]
        qualification_path = paths.qualified_run / "qualification.json"
        qualification, qualification_hash = _load_json_snapshot(qualification_path)
        if qualification.get("qualified") is not True:
            raise ValueError(f"{source} run is not qualified")
        packet_manifest = validate_review_packet_bundle(paths.review_root, qualification)
        source_qualification_hashes[source] = qualification_hash
        source_packet_manifest_hashes[source] = _digest(packet_manifest)

        items = _load_jsonl(paths.qualified_run / "raw-source-items.jsonl")
        observed_hash = dataset_sha256(items)
        if observed_hash != qualification.get("dataset_sha256"):
            raise ValueError(f"{source} dataset hash mismatch")
        source_dataset_hashes[source] = observed_hash

        mapping = json.loads(
            (paths.review_root / "internal/assignment-map.json").read_text(
                encoding="utf-8"
            )
        )
        development = {
            value["assignment_id"]: value
            for value in mapping
            if value.get("split") == "development"
        }
        if len(development) != 10:
            raise ValueError(f"{source} development split must contain exactly 10 records")
        reserved = {
            str(value["document_id"])
            for value in mapping
            if value.get("split") != "development"
        }
        if len(reserved) != 10:
            raise ValueError(f"{source} reserved split must contain exactly 10 records")
        reserved_ids.update(reserved)

        submissions = _load_jsonl(paths.primary_submission)
        submission_by_id = {value.get("assignment_id"): value for value in submissions}
        mapping_ids = {value.get("assignment_id") for value in mapping}
        if len(submission_by_id) != len(submissions) or set(submission_by_id) != mapping_ids:
            raise ValueError(f"{source} primary submission does not match frozen assignments")

        items_by_id = {value.get("document_id"): value for value in items}
        selected = 0
        for assignment_id, assignment in sorted(
            development.items(), key=lambda pair: str(pair[1]["document_id"])
        ):
            document_id = assignment["document_id"]
            item = items_by_id.get(document_id)
            if item is None or item.get("source") != source:
                raise ValueError(f"{source} development document is missing from qualified data")
            submission = submission_by_id[assignment_id]
            if not all(field in submission for field in _GOLD_FIELDS[1:]):
                raise ValueError(f"{source} development label is incomplete")
            _validate_gold_label(source, submission)
            inference.append({field: item.get(field) for field in _INFERENCE_FIELDS})
            gold.append(
                {
                    "document_id": document_id,
                    **{field: submission[field] for field in _GOLD_FIELDS[1:]},
                }
            )
            selected += 1
        source_counts[source] = selected

    inference.sort(key=lambda value: str(value["document_id"]))
    gold.sort(key=lambda value: str(value["document_id"]))
    if len(inference) != 40 or len(gold) != 40:
        raise ValueError("development slice must contain exactly 40 records")
    if {value["document_id"] for value in inference} != {
        value["document_id"] for value in gold
    }:
        raise ValueError("inference corpus and gold sidecar membership mismatch")

    return _Projection(
        tuple(inference),
        tuple(gold),
        source_counts,
        source_dataset_hashes,
        source_qualification_hashes,
        source_packet_manifest_hashes,
        frozenset(reserved_ids),
    )


def build_development_inference(
    sources: Mapping[str, SourceArtifacts],
) -> DevelopmentInference:
    projection = _project_development(sources)
    emitted_ids = {str(value["document_id"]) for value in projection.inference}
    receipt = {
        "source_counts": projection.source_counts,
        "selected_count": len(projection.inference),
        "source_spike_reserved_available": len(projection.reserved_ids),
        "source_spike_reserved_selected": len(emitted_ids & projection.reserved_ids),
        "source_spike_reserved_emitted": sum(
            str(value["document_id"]) in projection.reserved_ids
            for value in projection.inference
        ),
        "split_policy": "development_calibration_only",
        "independent_evaluation_status": "not_available",
        "source_dataset_sha256": projection.source_dataset_hashes,
        "source_qualification_sha256": projection.source_qualification_hashes,
        "source_packet_manifest_sha256": projection.source_packet_manifest_hashes,
        "inference_corpus_sha256": _digest(projection.inference),
        "packet_validation": "PASS",
    }
    return DevelopmentInference(projection.inference, receipt)


def build_development_gold_sidecar(
    sources: Mapping[str, SourceArtifacts],
) -> DevelopmentGoldSidecar:
    projection = _project_development(sources)
    receipt = {
        "source_counts": projection.source_counts,
        "selected_count": len(projection.gold),
        "split_policy": "development_calibration_only",
        "independent_evaluation_status": "not_available",
        "source_dataset_sha256": projection.source_dataset_hashes,
        "source_qualification_sha256": projection.source_qualification_hashes,
        "source_packet_manifest_sha256": projection.source_packet_manifest_hashes,
        "gold_sidecar_sha256": _digest(projection.gold),
        "packet_validation": "PASS",
    }
    return DevelopmentGoldSidecar(projection.gold, receipt)


def validate_extraction(
    document: Mapping[str, object], output: Mapping[str, object]
) -> None:
    if set(document) != set(_INFERENCE_FIELDS):
        raise ValueError("inference document fields do not match the gold-free contract")
    if set(output) != _EXTRACTION_FIELDS:
        raise ValueError("extraction fields do not match the minimal contract")
    if output["document_id"] != document.get("document_id"):
        raise ValueError("extraction document_id does not match input document_id")

    abstention_reason = output["abstention_reason"]
    inferred_fields = _EXTRACTION_FIELDS - {"document_id", "abstention_reason"}
    if abstention_reason is not None:
        if not isinstance(abstention_reason, str) or not abstention_reason.strip():
            raise ValueError("abstention reason must be a non-empty string")
        if any(output[field] is not None for field in inferred_fields):
            raise ValueError("abstention must not contain inferred values")
        return

    if output["observation_type"] not in _OBSERVATION_TYPES:
        raise ValueError("invalid observation_type")
    for field in ("actor", "problem", "context", "consequence", "evidence_quote"):
        if not isinstance(output[field], str) or not str(output[field]).strip():
            raise ValueError(f"{field} must be a non-empty string")
    for field in ("problem_signal", "money_signal", "usable_evidence"):
        if not isinstance(output[field], bool):
            raise ValueError(f"{field} must be boolean")

    money_type = output["money_signal_type"]
    if output["money_signal"] is False and money_type is not None:
        raise ValueError("money signal type must be null when money signal is false")
    if output["money_signal"] is True and money_type not in _MONEY_TYPES:
        raise ValueError("money signal type is required when money signal is true")

    confidence = output["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be numeric")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between zero and one")

    start = output["evidence_start"]
    end = output["evidence_end"]
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
        raise ValueError("evidence span must use integer offsets")
    text = document.get("text")
    if not isinstance(text, str) or start < 0 or end <= start or end > len(text):
        raise ValueError("evidence span is outside the input text")
    if text[start:end] != output["evidence_quote"]:
        raise ValueError("evidence span does not match evidence_quote")
