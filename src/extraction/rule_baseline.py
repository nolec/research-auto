from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from src.extraction.development_slice import DevelopmentInference, validate_extraction


_PROBLEM_PATTERNS = (
    "cannot",
    "can't",
    "crash",
    "error",
    "fails",
    "failed",
    "broken",
    "missing",
    "unable",
    "warning",
    "spent days",
)
_MONEY_PATTERNS = (
    ("purchase", "purchase"),
    ("buy", "purchase"),
    ("paid", "purchase"),
    ("subscription", "subscription"),
    ("contract", "outsourcing"),
    ("tender", "outsourcing"),
    ("budget", "willingness_to_pay"),
    ("price", "price_complaint"),
    ("cost", "loss"),
    ("umowa", "outsourcing"),
    ("zamówienia", "purchase"),
    ("dostawy", "purchase"),
)
_OBSERVATION_TYPE = {
    "github": "user_problem",
    "stackexchange": "user_problem",
    "steam": "product_feedback",
    "ted": "procurement_requirement",
}
_OUTPUT_FIELDS = (
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


@dataclass(frozen=True)
class RuleBaselineProfile:
    corpus_sha256: str
    variant_id: str = "rule_v1"
    schema_version: str = "extraction-v0.1"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", self.corpus_sha256):
            raise ValueError("corpus hash must contain 64 lowercase hexadecimal characters")
        if self.variant_id != "rule_v1":
            raise ValueError("rule baseline variant_id must be rule_v1")


@dataclass(frozen=True)
class BenchmarkRun:
    outputs: tuple[dict[str, object], ...]
    receipt: dict[str, object]


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _abstention(document_id: object) -> dict[str, object]:
    return {
        "document_id": document_id,
        **{field: None for field in _OUTPUT_FIELDS},
        "abstention_reason": "rule_v1 found no explicit problem or money pattern",
    }


def _pattern_start(text: str, pattern: str) -> int:
    match = re.search(
        rf"(?<!\w){re.escape(pattern)}(?!\w)",
        text,
        flags=re.IGNORECASE,
    )
    return match.start() if match else -1


def _problem_start(text: str) -> int:
    matches = [
        position
        for pattern in _PROBLEM_PATTERNS
        if (position := _pattern_start(text, pattern)) >= 0
    ]
    return min(matches) if matches else -1


def _money_match(text: str) -> tuple[int, str | None]:
    matches = [
        (position, money_type)
        for pattern, money_type in _MONEY_PATTERNS
        if (position := _pattern_start(text, pattern)) >= 0
    ]
    return min(matches, key=lambda value: value[0]) if matches else (-1, None)


def _evidence_span(
    text: str, first_match_start: int, last_match_start: int
) -> tuple[int, int]:
    left = max(
        text.rfind(".", 0, first_match_start),
        text.rfind("!", 0, first_match_start),
        text.rfind("?", 0, first_match_start),
        text.rfind("\n", 0, first_match_start),
    )
    start = left + 1
    while start < len(text) and text[start].isspace():
        start += 1
    endings = [
        position
        for marker in (".", "!", "?", "\n")
        if (position := text.find(marker, last_match_start)) >= 0
    ]
    end = min(endings) + 1 if endings else len(text)
    return start, end


def _extract(document: Mapping[str, object]) -> dict[str, object]:
    document_id = document.get("document_id")
    text = document.get("text")
    if not isinstance(text, str):
        return _abstention(document_id)
    problem_start = _problem_start(text)
    money_start, money_type = _money_match(text)
    signal_starts = [position for position in (problem_start, money_start) if position >= 0]
    if not signal_starts:
        return _abstention(document_id)

    start, end = _evidence_span(text, min(signal_starts), max(signal_starts))
    quote = text[start:end]
    source = str(document.get("source"))
    context = document.get("title") or source
    return {
        "document_id": document_id,
        "observation_type": _OBSERVATION_TYPE.get(source, "user_problem"),
        "actor": "source author",
        "problem": quote,
        "context": str(context),
        "consequence": quote,
        "evidence_quote": quote,
        "evidence_start": start,
        "evidence_end": end,
        "problem_signal": problem_start >= 0,
        "money_signal": money_type is not None,
        "money_signal_type": money_type,
        "usable_evidence": True,
        "confidence": 0.25,
        "abstention_reason": None,
    }


def run_rule_baseline(
    inference: DevelopmentInference, profile: RuleBaselineProfile
) -> BenchmarkRun:
    receipt_hash = inference.receipt.get("inference_corpus_sha256")
    observed_hash = _digest(inference.corpus)
    if receipt_hash != observed_hash or profile.corpus_sha256 != observed_hash:
        raise ValueError("benchmark corpus hash does not match the frozen inference corpus")
    selected_count = inference.receipt.get("selected_count")
    if not isinstance(selected_count, int) or selected_count != len(inference.corpus):
        raise ValueError("benchmark selected_count does not match the inference corpus")
    if inference.receipt.get("source_spike_reserved_emitted") != 0:
        raise ValueError("benchmark input contains source-spike-reserved records")

    outputs = tuple(_extract(document) for document in inference.corpus)
    for document, output in zip(inference.corpus, outputs, strict=True):
        validate_extraction(document, output)
    abstentions = sum(output["abstention_reason"] is not None for output in outputs)
    receipt = {
        "variant_id": profile.variant_id,
        "schema_version": profile.schema_version,
        "inference_corpus_sha256": observed_hash,
        "input_count": len(inference.corpus),
        "output_count": len(outputs),
        "valid_count": len(outputs),
        "invalid_count": 0,
        "abstention_count": abstentions,
        "output_sha256": _digest(outputs),
        "status": "success",
    }
    return BenchmarkRun(outputs, receipt)
