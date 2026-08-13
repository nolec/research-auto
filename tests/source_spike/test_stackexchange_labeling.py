from __future__ import annotations

from src.source_spike import stackexchange_labeling
import json


def test_labeling_cli_returns_prerequisite_failure_without_qualified_pointer(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(stackexchange_labeling, "ARTIFACT_ROOT", tmp_path)

    assert stackexchange_labeling.main([]) == 3


def test_labeling_cli_rejects_pointer_dataset_hash_mismatch(tmp_path, monkeypatch) -> None:
    root = tmp_path
    run = root / "runs/run-1"
    run.mkdir(parents=True)
    (root / "latest-qualified.json").write_text(json.dumps({"run_id": "run-1", "dataset_sha256": "a" * 64}))
    (run / "qualification.json").write_text(json.dumps({"run_id": "run-1", "dataset_sha256": "b" * 64, "qualified": True}))
    monkeypatch.setattr(stackexchange_labeling, "ARTIFACT_ROOT", root)

    assert stackexchange_labeling.main([]) == 3


def test_labeling_cli_rejects_pointer_run_id_mismatch(tmp_path, monkeypatch) -> None:
    root = tmp_path
    run = root / "runs/run-1"
    run.mkdir(parents=True)
    digest = "a" * 64
    (root / "latest-qualified.json").write_text(json.dumps({"run_id": "run-1", "dataset_sha256": digest}))
    (run / "qualification.json").write_text(json.dumps({"run_id": "run-2", "dataset_sha256": digest, "qualified": True}))
    monkeypatch.setattr(stackexchange_labeling, "ARTIFACT_ROOT", root)

    assert stackexchange_labeling.main([]) == 3
