from __future__ import annotations

import pytest
import json
from hashlib import sha256
from pathlib import Path

from src.source_spike.label_ingestion import ingest_submissions, validate_blind_submission


def submission() -> dict[str, object]:
    return {
        "assignment_id": "opaque-id", "reviewer_id": "human-primary",
        "reviewer_independence_asserted": False,
        "problem_signal": True, "money_signal": False,
        "money_signal_type": None, "structural_money_signal": False,
        "usable_evidence": True, "noise": False,
        "external_context_used": False,
        "label_reason": "The normalized text describes a concrete recurring failure.",
        "labeled_at": "2026-08-12T00:00:00Z",
    }


def test_blind_submission_accepts_only_human_fields() -> None:
    assert validate_blind_submission(submission()) == []
    changed = submission()
    changed["assignment_split"] = "development"
    assert validate_blind_submission(changed)


@pytest.mark.parametrize("reason", [
    "Contact person@example.com for the concrete failure details.",
    "The author @raw-user reports a concrete recurring failure.",
    "See https://github.com/raw-user for concrete failure details.",
])
def test_blind_submission_rejects_identity_in_reason(reason: str) -> None:
    changed = submission()
    changed["label_reason"] = reason
    assert any("identity" in error for error in validate_blind_submission(changed))


def review_root(tmp_path: Path) -> tuple[Path, list[dict[str, object]]]:
    root = tmp_path / "review"
    (root / "internal").mkdir(parents=True)
    mapping = []
    for index in range(20):
        mapping.append({
            "assignment_id": f"opaque-{index:02d}", "document_id": f"github:{index}",
            "source": "github", "split": "development" if index < 10 else "holdout",
            "requires_second_review": index < 5, "sample_rank": index + 1, "stratum": "a/b",
        })
    map_path = root / "internal/assignment-map.json"
    map_path.write_text(json.dumps(mapping), encoding="utf-8")
    (root / "packet").mkdir()
    primary_packet = root / "packet/primary.json"
    secondary_packet = root / "packet/secondary.json"
    primary_packet.write_text(json.dumps([{"assignment_id": value["assignment_id"]} for value in mapping]), encoding="utf-8")
    secondary_packet.write_text(json.dumps([
        {"assignment_id": value["assignment_id"]}
        for value in mapping if value["requires_second_review"]
    ]), encoding="utf-8")
    files = {
        "packet/primary.json": primary_packet,
        "packet/secondary.json": secondary_packet,
        "internal/assignment-map.json": map_path,
    }
    (root / "packet/bundle-manifest.json").write_text(json.dumps({
        "file_sha256": {
            relative: sha256(path.read_bytes()).hexdigest()
            for relative, path in files.items()
        }
    }), encoding="utf-8")
    return root, mapping


def labeled(assignment_id: str, reviewer: str, *, independent: bool = False) -> dict[str, object]:
    value = submission()
    value.update(
        assignment_id=assignment_id,
        reviewer_id=reviewer,
        reviewer_independence_asserted=independent,
    )
    return value


def test_ingestion_separates_development_and_sealed_holdout(tmp_path: Path) -> None:
    root, mapping = review_root(tmp_path)
    primary = [labeled(str(value["assignment_id"]), "primary") for value in mapping]
    secondary = [
        labeled(str(value["assignment_id"]), "secondary", independent=True)
        for value in mapping if value["requires_second_review"]
    ]

    summary = ingest_submissions(root, primary=primary, secondary=secondary)

    development = (root / "labels/development/canonical-labels.jsonl").read_text().splitlines()
    holdout = (root / "labels/holdout-sealed/canonical-labels.jsonl").read_text().splitlines()
    ingestion_manifest = json.loads((root / "labels/ingestion-manifest.json").read_text())
    audit = [
        json.loads(line)
        for line in (root / "labels/review-audit.jsonl").read_text().splitlines()
    ]
    assert summary == {"primary": 20, "secondary": 5, "development_primary": 10}
    assert len(development) == 15
    assert len(holdout) == 10
    assert all(json.loads(line)["assignment_split"] == "development" for line in development)
    assert all(json.loads(line)["assignment_split"] == "holdout" for line in holdout)
    assert ingestion_manifest["secondary_independence_asserted"] == 5
    assert ingestion_manifest["external_context_used"] == {"primary": 0, "secondary": 0}
    assert len(audit) == 25
    assert all("assignment_id" in value and "external_context_used" in value for value in audit)


def test_ingestion_rejects_tampered_frozen_assignment_map(tmp_path: Path) -> None:
    root, mapping = review_root(tmp_path)
    mapping[0]["split"] = "holdout"
    (root / "internal/assignment-map.json").write_text(json.dumps(mapping), encoding="utf-8")
    primary = [labeled(str(value["assignment_id"]), "primary") for value in mapping]
    secondary = [
        labeled(str(value["assignment_id"]), "secondary", independent=True)
        for value in mapping if value["requires_second_review"]
    ]

    with pytest.raises(ValueError, match="hash mismatch"):
        ingest_submissions(root, primary=primary, secondary=secondary)


def test_ingestion_rejects_incomplete_or_nonindependent_reviews(tmp_path: Path) -> None:
    root, mapping = review_root(tmp_path)
    primary = [labeled(str(value["assignment_id"]), "same") for value in mapping]
    secondary = [
        labeled(str(value["assignment_id"]), "same", independent=False)
        for value in mapping if value["requires_second_review"]
    ]
    with pytest.raises(ValueError, match="independence"):
        ingest_submissions(root, primary=primary, secondary=secondary)
    with pytest.raises(ValueError, match="primary assignments"):
        ingest_submissions(root, primary=primary[:-1], secondary=[])
