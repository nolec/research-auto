from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.source_spike.review_packet import build_review_packet_bundle
from src.source_spike.analysis_bundle import dataset_sha256


def qualified_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    items = []
    assignments = []
    for index in range(20):
        items.append({
            "document_id": f"github:{index}", "source": "github",
            "title": f"Issue {index}", "text": f"Normalized problem text {index}",
            "published_at": "2026-08-11T00:00:00Z",
            "source_url": f"https://github.com/a/b/issues/{index}",
            "fetch_run_id": "run-1",
        })
        assignments.append({
            "document_id": f"github:{index}", "source": "github",
            "split": "development" if index < 10 else "holdout",
            "requires_second_review": index < 5, "sample_rank": index + 1,
            "stratum": "a/b",
        })
    (run / "raw-source-items.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in items), encoding="utf-8"
    )
    (run / "labeling-assignments.json").write_text(json.dumps(assignments), encoding="utf-8")
    (run / "qualification.json").write_text(json.dumps({
        "run_id": "run-1", "qualified": True, "dataset_sha256": dataset_sha256(items),
        "manifest_hash": "manifest-hash",
    }), encoding="utf-8")
    return run


def test_packet_bundle_is_blind_frozen_and_idempotent(tmp_path: Path) -> None:
    run = qualified_run(tmp_path)
    review = tmp_path / "review"

    bundle = build_review_packet_bundle(run, review)
    repeated = build_review_packet_bundle(run, review)

    primary = json.loads((review / "packet/primary.json").read_text())
    secondary = json.loads((review / "packet/secondary.json").read_text())
    mapping = json.loads((review / "internal/assignment-map.json").read_text())
    allowed = {"assignment_id", "source", "title", "normalized_text", "published_at", "canonical_url"}
    assert len(primary) == 20
    assert len(secondary) == 5
    assert all(set(record) == allowed for record in primary + secondary)
    assert len({record["assignment_id"] for record in primary}) == 20
    assert all("github:" not in record["assignment_id"] for record in primary)
    assert {record["assignment_id"] for record in secondary} == {
        entry["assignment_id"] for entry in mapping if entry["requires_second_review"]
    }
    assert bundle == repeated


def test_packet_bundle_fails_on_partial_existing_bundle(tmp_path: Path) -> None:
    run = qualified_run(tmp_path)
    review = tmp_path / "review"
    (review / "packet").mkdir(parents=True)
    (review / "packet/primary.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete"):
        build_review_packet_bundle(run, review)


def test_packet_bundle_rejects_existing_bundle_from_another_qualified_run(tmp_path: Path) -> None:
    run = qualified_run(tmp_path)
    review = tmp_path / "review"
    build_review_packet_bundle(run, review)
    qualification_path = run / "qualification.json"
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    qualification["run_id"] = "run-2"
    qualification_path.write_text(json.dumps(qualification), encoding="utf-8")

    with pytest.raises(ValueError, match="provenance mismatch"):
        build_review_packet_bundle(run, review)
