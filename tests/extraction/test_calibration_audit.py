from __future__ import annotations

import json
import stat
from hashlib import sha256
from pathlib import Path

import pytest

from src.extraction.calibration_audit import build_audit_packet, ingest_audit_submission


def _documents() -> tuple[dict[str, object], ...]:
    return tuple(
        {"document_id": f"doc:{index}", "text": f"Problem evidence {index}."}
        for index in range(14)
    )


def _outputs() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "document_id": f"doc:{index}", "observation_type": "user_problem",
            "actor": "author", "problem": "Problem", "context": "Context",
            "consequence": "Consequence", "evidence_quote": f"Problem evidence {index}.",
            "evidence_start": 0, "evidence_end": len(f"Problem evidence {index}."),
            "problem_signal": True, "money_signal": False,
            "money_signal_type": None, "usable_evidence": True,
            "confidence": 0.99, "abstention_reason": None,
        }
        for index in range(14)
    )


def test_audit_packet_is_local_blind_complete_and_private(tmp_path: Path) -> None:
    root = tmp_path / "audit-local" / "run-1"
    receipt = build_audit_packet(
        _documents(), _outputs(), candidate_run_sha256="a" * 64, root=root
    )
    assignments = [json.loads(line) for line in (root / "handoff/assignments.jsonl").read_text().splitlines()]
    body = json.dumps(assignments)
    assert len(assignments) == 14
    assert "confidence" not in body
    assert "gold" not in body
    assert "gate" not in body
    assert "rule_v1" not in body
    assert receipt["assignment_count"] == 14
    for path in root.rglob("*"):
        if path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_audit_packet_requires_local_path_and_all_evidence_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="audit-local"):
        build_audit_packet(_documents(), _outputs(), candidate_run_sha256="a" * 64, root=tmp_path / "tracked")
    bad = list(_outputs())
    bad[0] = {**bad[0], "usable_evidence": False}
    with pytest.raises(ValueError, match="evidence-positive"):
        build_audit_packet(_documents(), tuple(bad), candidate_run_sha256="a" * 64, root=tmp_path / "audit-local/run")


def test_audit_packet_rejects_duplicate_or_missing_output_membership(
    tmp_path: Path,
) -> None:
    outputs = list(_outputs())
    outputs[-1] = dict(outputs[0])
    with pytest.raises(ValueError, match="exact membership"):
        build_audit_packet(
            _documents(), tuple(outputs), candidate_run_sha256="a" * 64,
            root=tmp_path / "audit-local/run",
        )


def test_ingestion_requires_exact_assignments_and_emits_aggregate_only(tmp_path: Path) -> None:
    root = tmp_path / "audit-local" / "run-1"
    build_audit_packet(_documents(), _outputs(), candidate_run_sha256="a" * 64, root=root)
    assignments = [json.loads(line) for line in (root / "handoff/assignments.jsonl").read_text().splitlines()]
    submission = root / "submission.jsonl"
    submission.write_text(
        "".join(json.dumps({
            "assignment_id": value["assignment_id"], "supported": True,
            "span_faithful": True, "reason_code": "supported", "reviewer_id": "reviewer-2"
        }) + "\n" for value in assignments), encoding="utf-8"
    )
    submission.chmod(0o600)
    receipt = ingest_audit_submission(root)
    assert receipt["status"] == "complete"
    assert receipt["audited_count"] == 14
    assert receipt["unsupported_count"] == 0
    assert receipt["raw_rows_persisted"] is False
    assert "document_text" not in json.dumps(receipt)

    submission.write_text(submission.read_text().splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="assignments"):
        ingest_audit_submission(root)


def test_ingestion_rejects_non_private_submission(tmp_path: Path) -> None:
    root = tmp_path / "audit-local" / "run-1"
    build_audit_packet(_documents(), _outputs(), candidate_run_sha256="a" * 64, root=root)
    assignments = [json.loads(line) for line in (root / "handoff/assignments.jsonl").read_text().splitlines()]
    submission = root / "submission.jsonl"
    submission.write_text(
        "".join(json.dumps({
            "assignment_id": value["assignment_id"], "supported": True,
            "span_faithful": True, "reason_code": "supported", "reviewer_id": "reviewer-2"
        }) + "\n" for value in assignments), encoding="utf-8"
    )
    submission.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        ingest_audit_submission(root)


def test_ingestion_rejects_tampered_assignment_file(tmp_path: Path) -> None:
    root = tmp_path / "audit-local" / "run-1"
    build_audit_packet(
        _documents(), _outputs(), candidate_run_sha256="a" * 64, root=root
    )
    assignment_path = root / "handoff/assignments.jsonl"
    assignment_path.write_text(
        assignment_path.read_text().replace("Problem evidence 0.", "Tampered evidence."),
        encoding="utf-8",
    )
    assignment_path.chmod(0o600)
    submission = root / "submission.jsonl"
    assignments = [
        json.loads(line) for line in assignment_path.read_text().splitlines()
    ]
    submission.write_text(
        "".join(
            json.dumps({
                "assignment_id": value["assignment_id"], "supported": True,
                "span_faithful": True, "reason_code": "supported",
                "reviewer_id": "reviewer-2",
            }) + "\n"
            for value in assignments
        ),
        encoding="utf-8",
    )
    submission.chmod(0o600)
    with pytest.raises(ValueError, match="assignment hash"):
        ingest_audit_submission(root)


def test_packet_failure_leaves_no_partial_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.extraction import calibration_audit

    root = tmp_path / "audit-local" / "run-1"
    original = calibration_audit._private_write
    calls = 0

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected write failure")
        original(path, payload)

    monkeypatch.setattr(calibration_audit, "_private_write", fail_second)
    with pytest.raises(OSError, match="injected"):
        build_audit_packet(
            _documents(), _outputs(), candidate_run_sha256="a" * 64, root=root
        )
    assert not root.exists()


def test_ingestion_parses_and_hashes_one_submission_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "audit-local" / "run-1"
    build_audit_packet(
        _documents(), _outputs(), candidate_run_sha256="a" * 64, root=root
    )
    assignments = [
        json.loads(line)
        for line in (root / "handoff/assignments.jsonl").read_text().splitlines()
    ]
    rows = [
        {
            "assignment_id": value["assignment_id"], "supported": True,
            "span_faithful": True, "reason_code": "supported",
            "reviewer_id": "reviewer-2",
        }
        for value in assignments
    ]
    submission = root / "submission.jsonl"
    submission.write_text("".join(json.dumps(row) + "\n" for row in rows))
    submission.chmod(0o600)
    snapshot_rows = [dict(row) for row in rows]
    snapshot_rows[0]["supported"] = False
    snapshot = "".join(json.dumps(row) + "\n" for row in snapshot_rows).encode()
    original_read_bytes = Path.read_bytes

    def snapshot_read(path: Path) -> bytes:
        if path == submission:
            return snapshot
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", snapshot_read)
    receipt = ingest_audit_submission(root)
    assert receipt["unsupported_count"] == 1
    assert receipt["submission_sha256"] == sha256(snapshot).hexdigest()
