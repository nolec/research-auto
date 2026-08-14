from __future__ import annotations

import json

from src.source_spike import steam_labeling


def test_packet_fails_without_qualified_pointer(tmp_path, monkeypatch):
    monkeypatch.setattr(steam_labeling, "ARTIFACT_ROOT", tmp_path)
    assert steam_labeling.main([]) == 3


def test_packet_builds_separate_primary_and_secondary_handoffs(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    run = artifact_root / "runs/run-1"
    run.mkdir(parents=True)
    qualification = {
        "run_id": "run-1", "dataset_sha256": "a" * 64,
        "manifest_hash": "b" * 64, "qualified": True,
    }
    (artifact_root / "latest-qualified.json").write_text(json.dumps({
        "run_id": "run-1", "dataset_sha256": "a" * 64,
    }))
    (run / "qualification.json").write_text(json.dumps(qualification))
    monkeypatch.setattr(steam_labeling, "ARTIFACT_ROOT", artifact_root)
    observed = {}

    def build(_run, destination):
        (destination / "packet").mkdir(parents=True)
        (destination / "internal").mkdir()
        primary = [{"assignment_id": "p", "source": "steam", "title": "Review", "normalized_text": "A concrete problem", "published_at": "2026-01-01T00:00:00Z", "canonical_url": "https://example.com"}]
        secondary = [{**primary[0], "assignment_id": "s"}]
        (destination / "packet/primary.json").write_text(json.dumps(primary))
        (destination / "packet/secondary.json").write_text(json.dumps(secondary))
        (destination / "internal/assignment-map.json").write_text(json.dumps([
            {"assignment_id": "p", "source": "steam"}
        ]))
        return qualification

    monkeypatch.setattr(steam_labeling, "build_review_packet_bundle", build)
    monkeypatch.setattr(steam_labeling, "validate_review_packet_bundle", lambda root, qualification: qualification)
    destination = tmp_path / "review"

    assert steam_labeling.main(["packet", "--review-root", str(destination)]) == 0
    primary_html = (destination / "handoff/primary-review.html").read_text()
    secondary_html = (destination / "handoff/secondary-review.html").read_text()
    assert "primary-submission.jsonl" in primary_html
    assert 'id="independent"' not in primary_html
    assert "secondary-submission.jsonl" in secondary_html
    assert 'id="independent"' in secondary_html
