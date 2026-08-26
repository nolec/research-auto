from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Mapping, Sequence

from jsonschema import Draft202012Validator


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads((_ROOT / "schemas/calibration-audit.schema.json").read_text())
_EXCLUDED = {"confidence", "document_id"}


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _jsonl(values: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(
        (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
        for value in values
    )


def _private_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def build_audit_packet(
    documents: Sequence[Mapping[str, object]],
    outputs: Sequence[Mapping[str, object]],
    *,
    candidate_run_sha256: str,
    root: Path,
) -> dict[str, object]:
    if "audit-local" not in root.parts:
        raise ValueError("audit packet root must be inside audit-local")
    if root.exists():
        raise FileExistsError("audit packet already exists")
    by_id = {value.get("document_id"): value for value in documents}
    output_ids = [value.get("document_id") for value in outputs]
    if (
        len(by_id) != len(documents)
        or any(not isinstance(value, str) for value in by_id)
        or any(not isinstance(value, str) for value in output_ids)
        or len(output_ids) != len(set(output_ids))
        or set(output_ids) != set(by_id)
    ):
        raise ValueError("audit documents and outputs must have exact membership")
    assignments = []
    for output in outputs:
        if output.get("usable_evidence") is not True:
            raise ValueError("audit packet accepts evidence-positive outputs only")
        document = by_id.get(output.get("document_id"))
        if document is None:
            raise ValueError("audit output document is missing")
        assignment_id = sha256(
            f"{candidate_run_sha256}:{output['document_id']}".encode()
        ).hexdigest()[:24]
        assignments.append(
            {
                "assignment_id": assignment_id,
                "document_text": document.get("text"),
                "extraction": {
                    key: value for key, value in output.items() if key not in _EXCLUDED
                },
            }
        )
    assignments.sort(key=lambda value: value["assignment_id"])
    assignment_payload = _jsonl(assignments)
    html = "<html><body><h1>Blind evidence audit</h1>" + "".join(
        f"<section><h2>{escape(str(value['assignment_id']))}</h2>"
        f"<pre>{escape(str(value['document_text']))}</pre>"
        f"<pre>{escape(json.dumps(value['extraction'], ensure_ascii=False, sort_keys=True))}</pre></section>"
        for value in assignments
    ) + "</body></html>"
    created = datetime.now(UTC)
    receipt = {
        "schema_version": "calibration-audit-custody/v1",
        "candidate_run_sha256": candidate_run_sha256,
        "assignment_count": len(assignments),
        "assignment_sha256": _digest_bytes(assignment_payload),
        "packet_sha256": _digest_bytes(html.encode()),
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(days=30)).isoformat(),
        "retention_days": 30,
        "raw_rows_tracked": False,
    }
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=root.parent))
    try:
        _private_write(staging / "handoff/assignments.jsonl", assignment_payload)
        _private_write(staging / "handoff/review.html", html.encode())
        _private_write(
            staging / "custody-receipt.json",
            json.dumps(receipt, sort_keys=True).encode(),
        )
        os.replace(staging, root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return receipt


def ingest_audit_submission(root: Path) -> dict[str, object]:
    custody = json.loads((root / "custody-receipt.json").read_text())
    assignment_path = root / "handoff/assignments.jsonl"
    submission_path = root / "submission.jsonl"
    if stat.S_IMODE(submission_path.stat().st_mode) != 0o600:
        raise ValueError("audit submission permissions must be 0600")
    if datetime.now(UTC) > datetime.fromisoformat(custody["expires_at"]):
        raise ValueError("audit packet has expired")
    assignment_payload = assignment_path.read_bytes()
    if _digest_bytes(assignment_payload) != custody.get("assignment_sha256"):
        raise ValueError("audit assignment hash mismatch")
    packet_path = root / "handoff/review.html"
    if _digest_bytes(packet_path.read_bytes()) != custody.get("packet_sha256"):
        raise ValueError("audit packet hash mismatch")
    assignments = [
        json.loads(line) for line in assignment_payload.decode("utf-8").splitlines()
    ]
    submission_payload = submission_path.read_bytes()
    submissions = [
        json.loads(line) for line in submission_payload.decode("utf-8").splitlines()
    ]
    allowed = {
        "assignment_id", "supported", "span_faithful", "reason_code", "reviewer_id"
    }
    if any(
        set(value) != allowed
        or not isinstance(value.get("supported"), bool)
        or not isinstance(value.get("span_faithful"), bool)
        for value in submissions
    ):
        raise ValueError("audit submission fields are invalid")
    expected = {value["assignment_id"] for value in assignments}
    observed = [value.get("assignment_id") for value in submissions]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        raise ValueError("audit submission does not match assignments")
    reviewer_ids = {value.get("reviewer_id") for value in submissions}
    if len(reviewer_ids) != 1 or not next(iter(reviewer_ids), None):
        raise ValueError("audit submission requires one reviewer")
    unsupported = sum(
        value.get("supported") is not True or value.get("span_faithful") is not True
        for value in submissions
    )
    receipt = {
        "schema_version": "calibration-audit-aggregate/v1",
        "status": "complete",
        "candidate_run_sha256": custody["candidate_run_sha256"],
        "packet_sha256": custody["packet_sha256"],
        "assignment_sha256": custody["assignment_sha256"],
        "submission_sha256": _digest_bytes(submission_payload),
        "reviewer_id": next(iter(reviewer_ids)),
        "audited_count": len(submissions),
        "supported_count": len(submissions) - unsupported,
        "unsupported_count": unsupported,
        "raw_rows_persisted": False,
    }
    validator = Draft202012Validator(
        {"$ref": "#/$defs/aggregateReceipt", "$defs": _SCHEMA["$defs"]}
    )
    errors = list(validator.iter_errors(receipt))
    if errors:
        raise ValueError(f"audit aggregate schema failed: {errors[0].message}")
    return receipt
