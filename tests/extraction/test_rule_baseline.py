from __future__ import annotations

import json
from hashlib import sha256

import pytest

from src.extraction.development_slice import DevelopmentInference, validate_extraction
from src.extraction.rule_baseline import RuleBaselineProfile, run_rule_baseline


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _document(index: int, text: str) -> dict[str, object]:
    return {
        "document_id": f"github:{index}",
        "source": "github",
        "title": f"Issue {index}",
        "text": text,
        "published_at": "2026-01-01T00:00:00Z",
        "source_url": f"https://example.com/{index}",
    }


def _inference(*documents: dict[str, object]) -> DevelopmentInference:
    corpus = tuple(documents)
    return DevelopmentInference(
        corpus,
        {
            "inference_corpus_sha256": _digest(corpus),
            "source_spike_reserved_emitted": 0,
            "selected_count": len(corpus),
        },
    )


def test_rule_baseline_is_deterministic_and_contract_valid() -> None:
    inference = _inference(
        _document(1, "The application crashes after login and the user cannot continue."),
        _document(2, "A normal informational update with no request or observed failure."),
    )
    profile = RuleBaselineProfile(inference.receipt["inference_corpus_sha256"])

    first = run_rule_baseline(inference, profile)
    second = run_rule_baseline(inference, profile)

    assert first == second
    assert first.receipt["variant_id"] == "rule_v1"
    assert first.receipt["input_count"] == 2
    assert first.receipt["output_count"] == 2
    assert first.receipt["abstention_count"] == 1
    assert first.receipt["invalid_count"] == 0
    assert "gold" not in json.dumps(first.receipt).casefold()
    for document, output in zip(inference.corpus, first.outputs, strict=True):
        validate_extraction(document, output)


def test_rule_baseline_detects_explicit_money_language() -> None:
    inference = _inference(
        _document(1, "We need to purchase a replacement because the current service fails."),
    )
    run = run_rule_baseline(
        inference, RuleBaselineProfile(inference.receipt["inference_corpus_sha256"])
    )
    output = run.outputs[0]
    assert output["problem_signal"] is True
    assert output["money_signal"] is True
    assert output["money_signal_type"] == "purchase"
    start, end = output["evidence_start"], output["evidence_end"]
    assert inference.corpus[0]["text"][start:end] == output["evidence_quote"]


def test_rule_baseline_requires_keyword_boundaries() -> None:
    inference = _inference(
        _document(1, "The costume customization is delightful."),
    )

    output = run_rule_baseline(
        inference, RuleBaselineProfile(inference.receipt["inference_corpus_sha256"])
    ).outputs[0]

    assert output["problem_signal"] is None
    assert output["money_signal"] is None
    assert output["abstention_reason"] is not None


def test_rule_baseline_detects_problem_and_money_across_sentences() -> None:
    inference = _inference(
        _document(
            1,
            "The service fails repeatedly. We need to purchase a replacement.",
        ),
    )

    output = run_rule_baseline(
        inference, RuleBaselineProfile(inference.receipt["inference_corpus_sha256"])
    ).outputs[0]

    assert output["problem_signal"] is True
    assert output["money_signal"] is True
    assert output["money_signal_type"] == "purchase"


def test_rule_baseline_does_not_infer_problem_from_money_alone() -> None:
    inference = _inference(
        _document(1, "We paid 100 dollars. Everything works perfectly."),
    )

    output = run_rule_baseline(
        inference, RuleBaselineProfile(inference.receipt["inference_corpus_sha256"])
    ).outputs[0]

    assert output["problem_signal"] is False
    assert output["money_signal"] is True
    assert output["money_signal_type"] == "purchase"


def test_rule_baseline_rejects_corpus_hash_mismatch() -> None:
    inference = _inference(_document(1, "The service fails repeatedly for this user."))
    with pytest.raises(ValueError, match="corpus hash"):
        run_rule_baseline(inference, RuleBaselineProfile("0" * 64))


def test_rule_baseline_rejects_reserved_or_gold_contaminated_input() -> None:
    inference = _inference(_document(1, "The service fails repeatedly for this user."))
    contaminated_receipt = {**inference.receipt, "source_spike_reserved_emitted": 1}
    with pytest.raises(ValueError, match="reserved"):
        run_rule_baseline(
            DevelopmentInference(inference.corpus, contaminated_receipt),
            RuleBaselineProfile(inference.receipt["inference_corpus_sha256"]),
        )

    contaminated_document = {**inference.corpus[0], "problem_signal": True}
    contaminated = _inference(contaminated_document)
    with pytest.raises(ValueError, match="gold-free"):
        run_rule_baseline(
            contaminated,
            RuleBaselineProfile(contaminated.receipt["inference_corpus_sha256"]),
        )


def test_rule_baseline_rejects_unmeasured_or_mismatched_receipt() -> None:
    inference = _inference(_document(1, "The service fails repeatedly for this user."))
    missing_count = dict(inference.receipt)
    missing_count.pop("selected_count")
    with pytest.raises(ValueError, match="selected_count"):
        run_rule_baseline(
            DevelopmentInference(inference.corpus, missing_count),
            RuleBaselineProfile(inference.receipt["inference_corpus_sha256"]),
        )

    wrong_count = {**inference.receipt, "selected_count": 2}
    with pytest.raises(ValueError, match="selected_count"):
        run_rule_baseline(
            DevelopmentInference(inference.corpus, wrong_count),
            RuleBaselineProfile(inference.receipt["inference_corpus_sha256"]),
        )
