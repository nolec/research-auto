from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER
from src.source_spike.labeling import create_labeling_assignments
from src.source_spike.labeling import create_stratified_labeling_assignments


ROOT = Path(__file__).resolve().parents[2]
SOURCES = ["github", "stackexchange", "steam", "youtube", "reddit"]


def load_schema() -> dict:
    return json.loads(
        (ROOT / "schemas" / "source-label.schema.json").read_text(encoding="utf-8")
    )


def valid_label() -> dict:
    return {
        "label_id": "github:1:reviewer-a:primary",
        "document_id": "github:1",
        "source": "github",
        "reviewer_id": "reviewer-a",
        "assignment_split": "development",
        "review_round": "primary",
        "problem_signal": True,
        "money_signal": True,
        "money_signal_type": "replacement_search",
        "structural_money_signal": False,
        "usable_evidence": True,
        "noise": False,
        "label_reason": "The author describes a concrete replacement search and its cause.",
        "labeled_at": "2026-08-11T00:00:00Z",
        "guide_version": "1.0.0",
    }


def make_items(count_per_source: int = 100) -> list[dict[str, str]]:
    return [
        {"source": source, "document_id": f"{source}:{index:03d}"}
        for source in SOURCES
        for index in range(count_per_source)
    ]


def test_source_label_schema_accepts_a_complete_label() -> None:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)

    assert not list(validator.iter_errors(valid_label()))


def test_source_label_schema_enforces_money_consistency_and_reason() -> None:
    validator = Draft202012Validator(load_schema(), format_checker=FORMAT_CHECKER)

    missing_type = valid_label()
    missing_type["money_signal_type"] = None
    assert list(validator.iter_errors(missing_type))

    false_with_type = valid_label()
    false_with_type["money_signal"] = False
    assert list(validator.iter_errors(false_with_type))

    structural_without_money = valid_label()
    structural_without_money["money_signal"] = False
    structural_without_money["money_signal_type"] = None
    structural_without_money["structural_money_signal"] = True
    assert list(validator.iter_errors(structural_without_money))

    weak_reason = valid_label()
    weak_reason["label_reason"] = "yes"
    assert list(validator.iter_errors(weak_reason))


def test_assignments_create_twenty_per_source_with_balanced_split() -> None:
    assignments = create_labeling_assignments(make_items(), seed=20260811)

    by_source: dict[str, list] = defaultdict(list)
    for assignment in assignments:
        by_source[assignment.source].append(assignment)

    assert set(by_source) == set(SOURCES)
    for source in SOURCES:
        assert len(by_source[source]) == 20
        assert Counter(item.split for item in by_source[source]) == {
            "development": 10,
            "holdout": 10,
        }
        assert sum(item.requires_second_review for item in by_source[source]) == 5


def test_assignments_are_independent_of_input_order() -> None:
    items = make_items()

    forward = create_labeling_assignments(items, seed=17)
    reverse = create_labeling_assignments(list(reversed(items)), seed=17)

    assert forward == reverse


def test_assignments_reject_duplicate_or_insufficient_source_items() -> None:
    duplicate = make_items()
    duplicate.append(dict(duplicate[0]))
    with pytest.raises(ValueError, match="duplicate document_id: github:000"):
        create_labeling_assignments(duplicate, seed=1)

    insufficient = make_items(count_per_source=19)
    with pytest.raises(ValueError, match="github has 19 items; 20 required"):
        create_labeling_assignments(insufficient, seed=1)


def test_assignments_validate_sampling_parameters() -> None:
    items = make_items()
    with pytest.raises(ValueError, match="sample_per_source must be a positive even number"):
        create_labeling_assignments(items, seed=1, sample_per_source=19)
    with pytest.raises(ValueError, match="double_review_per_source cannot exceed"):
        create_labeling_assignments(items, seed=1, double_review_per_source=21)
