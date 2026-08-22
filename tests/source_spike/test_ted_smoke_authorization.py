import json
from hashlib import sha256
from pathlib import Path

from src.source_spike.ted_smoke_authorization import validate_ted_smoke_authorization


def test_authorization_is_bound_to_exact_capacity_receipt(tmp_path: Path) -> None:
    receipt = {"run_id": "capacity-run", "status": "PASS", "termination_reason": "capacity_reached", "capacity_manifest_hash": "a" * 64, "feasibility_hash": "b" * 64, "compliance_hash": "c" * 64}
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    authorization = {"schema_version": "1.0.0", "status": "AUTHORIZED", "operational_next_action": "run_smoke", "capacity_run_id": "capacity-run", "capacity_receipt_sha256": sha256(path.read_bytes()).hexdigest(), "capacity_manifest_hash": "a" * 64, "feasibility_hash": "b" * 64, "compliance_hash": "c" * 64, "query_set_sha256": "d" * 64, "authorized_at": "2026-08-22T00:00:00Z"}

    assert validate_ted_smoke_authorization(authorization, path) == []
    receipt["run_id"] = "other"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert validate_ted_smoke_authorization(authorization, path)


def test_authorization_schema_rejects_bad_timestamp_and_extra_field(tmp_path: Path) -> None:
    receipt = {"run_id": "capacity-run", "status": "PASS", "termination_reason": "capacity_reached", "capacity_manifest_hash": "a" * 64, "feasibility_hash": "b" * 64, "compliance_hash": "c" * 64}
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    authorization = {"schema_version": "1.0.0", "status": "AUTHORIZED", "operational_next_action": "run_smoke", "capacity_run_id": "capacity-run", "capacity_receipt_sha256": sha256(path.read_bytes()).hexdigest(), "capacity_manifest_hash": "a" * 64, "feasibility_hash": "b" * 64, "compliance_hash": "c" * 64, "query_set_sha256": "d" * 64, "authorized_at": "not-a-date", "unexpected": True}
    assert validate_ted_smoke_authorization(authorization, path)
