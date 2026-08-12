from __future__ import annotations

import pytest
import json
from pathlib import Path

from src.source_spike.source_quality import (
    build_development_report,
    descriptive_agreement,
    load_source_quality_policy,
    signal_density,
    write_development_report,
)


def test_signal_density_reports_wilson_interval() -> None:
    result = signal_density([True] * 3 + [False] * 7)
    assert result["positive"] == 3
    assert result["total"] == 10
    assert result["estimate"] == pytest.approx(0.3)
    assert result["wilson_95"][0] == pytest.approx(0.1078, abs=0.001)
    assert result["wilson_95"][1] == pytest.approx(0.6032, abs=0.001)


def test_agreement_is_descriptive_and_has_no_pass_field() -> None:
    result = descriptive_agreement([True, False, True], [True, False, False])
    assert result["sample_size"] == 3
    assert result["raw_agreement"] == pytest.approx(2 / 3)
    assert "passed" not in result
    assert "positive_prevalence" in result


def test_development_report_never_reads_sealed_holdout(tmp_path: Path) -> None:
    development = tmp_path / "development.jsonl"
    labels = []
    for index in range(10):
        labels.append({
            "label_id": f"label-{index}", "document_id": f"github:{index}",
            "source": "github", "reviewer_id": "primary",
            "assignment_split": "development", "review_round": "primary",
            "problem_signal": index < 6, "money_signal": index < 2,
            "money_signal_type": "purchase" if index < 2 else None,
            "structural_money_signal": index == 0, "usable_evidence": index < 7,
            "noise": index >= 8,
            "label_reason": "The source describes a concrete recurring problem.",
            "labeled_at": "2026-08-12T00:00:00Z", "guide_version": "1.0.0",
        })
    labels.extend([
        {
            **labels[index],
            "label_id": f"secondary-{index}",
            "review_round": "secondary",
            "reviewer_id": "secondary",
        }
        for index in range(5)
    ])
    development.write_text("".join(json.dumps(value) + "\n" for value in labels), encoding="utf-8")
    sealed = tmp_path / "holdout.jsonl"
    sealed.write_text("SECRET-HOLDOUT", encoding="utf-8")
    sealed.chmod(0)

    report = build_development_report(development, provenance={"dataset_sha256": "a" * 64})

    assert report["population"] == "development_only"
    assert report["density"]["problem_signal"]["positive"] == 6
    assert report["agreement"]["problem_signal"]["sample_size"] == 5
    assert "passed" not in report["agreement"]["problem_signal"]


def test_development_report_rejects_holdout_or_duplicate_primary_labels(tmp_path: Path) -> None:
    development = tmp_path / "development.jsonl"
    labels = []
    for index in range(10):
        labels.append({
            "label_id": f"label-{index}", "document_id": f"github:{index}",
            "source": "github", "reviewer_id": "primary",
            "assignment_split": "holdout", "review_round": "primary",
            "problem_signal": True, "money_signal": False, "money_signal_type": None,
            "structural_money_signal": False, "usable_evidence": True, "noise": False,
            "label_reason": "The source describes a concrete recurring problem.",
            "labeled_at": "2026-08-12T00:00:00Z", "guide_version": "1.0.0",
        })
    development.write_text("".join(json.dumps(value) + "\n" for value in labels), encoding="utf-8")
    with pytest.raises(ValueError, match="development split"):
        build_development_report(development, provenance={})

    for value in labels:
        value["assignment_split"] = "development"
    labels[-1]["document_id"] = labels[0]["document_id"]
    development.write_text("".join(json.dumps(value) + "\n" for value in labels), encoding="utf-8")
    with pytest.raises(ValueError, match="unique primary"):
        build_development_report(development, provenance={})


def test_frozen_policy_is_descriptive_and_report_writes_no_reasons(tmp_path: Path) -> None:
    policy = load_source_quality_policy()
    assert policy["decision_mode"] == "descriptive_only"
    assert policy["thresholds_applied"] is False
    report = {
        "population": "development_only", "primary_sample_size": 10,
        "holdout_status": "sealed", "density": {}, "agreement": {},
        "provenance": {"policy_sha256": "a" * 64},
    }
    destination = write_development_report(tmp_path, report)
    assert (destination / "development-source-quality.json").is_file()
    markdown = (destination / "development-source-quality.md").read_text()
    assert "development_only" in markdown
    assert "label_reason" not in markdown
