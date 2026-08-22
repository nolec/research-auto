from __future__ import annotations

import json
from pathlib import Path

from src.source_spike import ted_labeling


def _qualified_artifact(root: Path) -> tuple[Path, dict[str, object]]:
    run = root / "runs/run-1"
    run.mkdir(parents=True)
    qualification: dict[str, object] = {
        "run_id": "run-1",
        "dataset_sha256": "a" * 64,
        "manifest_hash": "b" * 64,
        "qualified": True,
    }
    (root / "latest-qualified.json").write_text(
        json.dumps({"run_id": "run-1", "dataset_sha256": "a" * 64}),
        encoding="utf-8",
    )
    (run / "qualification.json").write_text(json.dumps(qualification), encoding="utf-8")
    return run, qualification


def _fake_packet_builder(source: str = "ted"):
    def build(_run: Path, destination: Path) -> dict[str, object]:
        manifest = {
            "run_id": "run-1",
            "dataset_sha256": "a" * 64,
            "manifest_hash": "b" * 64,
            "primary_count": 20,
            "secondary_count": 5,
        }
        if destination.exists():
            return manifest
        (destination / "packet").mkdir(parents=True)
        (destination / "internal").mkdir()
        primary = [
            {
                "assignment_id": f"opaque-{index:02d}",
                "source": source,
                "title": f"Notice {index}",
                "normalized_text": "A concrete procurement problem with enough evidence.",
                "published_at": "2026-08-01T00:00:00Z",
                "canonical_url": "https://ted.europa.eu/en/notice/-/detail/example",
            }
            for index in range(20)
        ]
        secondary = primary[:5]
        mapping = [
            {
                "assignment_id": value["assignment_id"],
                "source": source,
                "requires_second_review": index < 5,
            }
            for index, value in enumerate(primary)
        ]
        (destination / "packet/primary.json").write_text(json.dumps(primary), encoding="utf-8")
        (destination / "packet/secondary.json").write_text(json.dumps(secondary), encoding="utf-8")
        (destination / "internal/assignment-map.json").write_text(json.dumps(mapping), encoding="utf-8")
        return manifest

    return build


def test_packet_fails_without_qualified_pointer(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ted_labeling, "ARTIFACT_ROOT", tmp_path)

    assert ted_labeling.main([]) == 3


def test_packet_builds_allowlisted_isolated_handoffs(tmp_path, monkeypatch) -> None:
    artifact_root = tmp_path / "artifacts"
    _run, qualification = _qualified_artifact(artifact_root)
    monkeypatch.setattr(ted_labeling, "ARTIFACT_ROOT", artifact_root)
    monkeypatch.setattr(ted_labeling, "build_review_packet_bundle", _fake_packet_builder())
    monkeypatch.setattr(
        ted_labeling,
        "validate_review_packet_bundle",
        lambda root, expected: qualification,
    )
    destination = tmp_path / "review"

    assert ted_labeling.main(["packet", "--review-root", str(destination)]) == 0
    assert {path.name for path in (destination / "handoff-primary").iterdir()} == {
        "review.html",
        "submission-template.jsonl",
    }
    assert {path.name for path in (destination / "handoff-secondary").iterdir()} == {
        "review.html",
        "submission-template.jsonl",
    }
    primary_html = (destination / "handoff-primary/review.html").read_text()
    secondary_html = (destination / "handoff-secondary/review.html").read_text()
    assert "primary-submission.jsonl" in primary_html
    assert 'id="independent"' not in primary_html
    assert "secondary-submission.jsonl" in secondary_html
    assert 'id="independent"' in secondary_html
    assert "hidden_split" not in primary_html + secondary_html
    before = (destination / "handoff-primary/review.html").stat().st_mtime_ns
    assert ted_labeling.main(["packet", "--review-root", str(destination)]) == 0
    assert (destination / "handoff-primary/review.html").stat().st_mtime_ns == before


def test_packet_rejects_non_ted_assignments(tmp_path, monkeypatch) -> None:
    artifact_root = tmp_path / "artifacts"
    _qualified_artifact(artifact_root)
    monkeypatch.setattr(ted_labeling, "ARTIFACT_ROOT", artifact_root)
    monkeypatch.setattr(ted_labeling, "build_review_packet_bundle", _fake_packet_builder("steam"))
    monkeypatch.setattr(
        ted_labeling,
        "validate_review_packet_bundle",
        lambda root, expected: expected,
    )

    assert ted_labeling.main(["packet", "--review-root", str(tmp_path / "review")]) == 3
