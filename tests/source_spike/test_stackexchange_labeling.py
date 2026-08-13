from __future__ import annotations

from src.source_spike import stackexchange_labeling
import json
import sys


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


def _review_root(tmp_path, *, source: str = "stackexchange"):
    root = tmp_path / "review"
    (root / "internal").mkdir(parents=True)
    (root / "internal/assignment-map.json").write_text(json.dumps([
        {"assignment_id": "assignment-1", "source": source}
    ]))
    return root


def _qualified_artifacts(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    run = root / "runs/run-current"
    run.mkdir(parents=True)
    qualification = {"run_id": "run-current", "dataset_sha256": "a" * 64, "manifest_hash": "b" * 64, "qualified": True}
    (root / "latest-qualified.json").write_text(json.dumps({"run_id": "run-current", "dataset_sha256": "a" * 64}))
    (run / "qualification.json").write_text(json.dumps(qualification))
    monkeypatch.setattr(stackexchange_labeling, "ARTIFACT_ROOT", root)
    return qualification


def test_ingest_command_uses_generic_ingestion_for_stackexchange_packet(tmp_path, monkeypatch) -> None:
    review_root = _review_root(tmp_path)
    _qualified_artifacts(tmp_path, monkeypatch)
    primary = tmp_path / "primary.jsonl"; primary.write_text("{}\n")
    secondary = tmp_path / "secondary.jsonl"; secondary.write_text("{}\n")
    monkeypatch.setattr(stackexchange_labeling, "validate_review_packet_bundle", lambda root, qualification: {"dataset_sha256": "a" * 64})
    observed = {}
    def ingest(root, *, primary, secondary):
        observed.update(root=root, primary=primary, secondary=secondary)
        return {"primary": 20, "secondary": 5}
    monkeypatch.setattr(stackexchange_labeling, "ingest_submissions", ingest)

    code = stackexchange_labeling.main([
        "ingest", "--review-root", str(review_root), "--primary", str(primary),
        "--secondary", str(secondary),
    ])

    assert code == 0
    assert observed["root"] == review_root
    assert observed["primary"] == [{}]
    assert observed["secondary"] == [{}]


def test_report_command_fails_before_human_confirmed_labels_exist(tmp_path) -> None:
    assert stackexchange_labeling.main([
        "report-development", "--review-root", str(tmp_path)
    ]) == 2


def test_commands_reject_a_non_stackexchange_review_packet(tmp_path, monkeypatch) -> None:
    review_root = _review_root(tmp_path, source="github")
    _qualified_artifacts(tmp_path, monkeypatch)
    labels = review_root / "labels/development/canonical-labels.jsonl"
    labels.parent.mkdir(parents=True); labels.write_text("{}\n")
    monkeypatch.setattr(stackexchange_labeling, "validate_review_packet_bundle", lambda root, qualification: {"dataset_sha256": "a" * 64})

    assert stackexchange_labeling.main([
        "report-development", "--review-root", str(review_root)
    ]) == 3


def test_report_command_uses_generic_development_report_with_packet_provenance(tmp_path, monkeypatch) -> None:
    review_root = _review_root(tmp_path)
    _qualified_artifacts(tmp_path, monkeypatch)
    labels = review_root / "labels/development/canonical-labels.jsonl"
    labels.parent.mkdir(parents=True); labels.write_text("{}\n")
    packet = {"dataset_sha256": "a" * 64, "manifest_hash": "b" * 64, "file_sha256": {"packet/primary.json": "c" * 64}}
    monkeypatch.setattr(stackexchange_labeling, "validate_review_packet_bundle", lambda root, qualification: packet)
    observed = {}
    monkeypatch.setattr(stackexchange_labeling, "policy_sha256", lambda: "d" * 64)
    def build(path, *, provenance):
        observed.update(path=path, provenance=provenance); return {"population": "development_only"}
    monkeypatch.setattr(stackexchange_labeling, "build_development_report", build)
    monkeypatch.setattr(stackexchange_labeling, "write_development_report", lambda root, report: observed.update(root=root, report=report))

    assert stackexchange_labeling.main([
        "report-development", "--review-root", str(review_root)
    ]) == 0
    assert observed["path"] == labels
    assert observed["provenance"]["dataset_sha256"] == "a" * 64
    assert observed["root"] == review_root


def test_main_without_explicit_argv_uses_process_arguments(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "argv", ["stackexchange-labeling", "report-development", "--review-root", str(tmp_path)])

    assert stackexchange_labeling.main() == 2


def test_report_rejects_packet_not_bound_to_latest_qualified_run(tmp_path, monkeypatch) -> None:
    artifact_root = tmp_path / "artifacts"
    run = artifact_root / "runs/run-current"
    run.mkdir(parents=True)
    digest = "a" * 64
    (artifact_root / "latest-qualified.json").write_text(json.dumps({"run_id": "run-current", "dataset_sha256": digest}))
    qualification = {"run_id": "run-current", "dataset_sha256": digest, "manifest_hash": "b" * 64, "qualified": True}
    (run / "qualification.json").write_text(json.dumps(qualification))
    review_root = _review_root(tmp_path)
    labels = review_root / "labels/development/canonical-labels.jsonl"
    labels.parent.mkdir(parents=True); labels.write_text("{}\n")
    observed = {}
    def validate(root, qualification=None):
        observed["qualification"] = qualification
        raise ValueError("existing review packet provenance mismatch")
    monkeypatch.setattr(stackexchange_labeling, "ARTIFACT_ROOT", artifact_root)
    monkeypatch.setattr(stackexchange_labeling, "validate_review_packet_bundle", validate)

    assert stackexchange_labeling.main([
        "report-development", "--review-root", str(review_root)
    ]) == 3
    assert observed["qualification"] == qualification


def test_report_rejects_non_object_authority_json_without_traceback(tmp_path, monkeypatch) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / "latest-qualified.json").write_text("[]")
    review_root = tmp_path / "review"
    labels = review_root / "labels/development/canonical-labels.jsonl"
    labels.parent.mkdir(parents=True); labels.write_text("{}\n")
    monkeypatch.setattr(stackexchange_labeling, "ARTIFACT_ROOT", artifact_root)

    assert stackexchange_labeling.main([
        "report-development", "--review-root", str(review_root)
    ]) == 3
