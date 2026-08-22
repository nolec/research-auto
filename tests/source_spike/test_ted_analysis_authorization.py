import json
import stat
from pathlib import Path

import pytest

from src.source_spike.ted_analysis_authorization import check_authorization, init_authorization


def _smoke(path: Path, run_id: str = "smoke-run") -> None:
    path.write_text(json.dumps({"schema_version": 1, "run_id": run_id, "status": "PASS", "termination_reason": "target_reached", "accepted": 10, "provenance": {"manifest_hash": "a" * 64, "capacity_manifest_hash": "b" * 64, "authorization_hash": "c" * 64}}), encoding="utf-8")


def test_local_authorization_is_private_exact_and_detects_smoke_drift(tmp_path: Path) -> None:
    trusted = tmp_path / "artifacts" / "source-spike"
    trusted.mkdir(parents=True)
    smoke = trusted / "smoke.json"
    _smoke(smoke)
    destination = trusted / "ted-analysis-authorization" / "authorization.json"
    value = init_authorization(smoke, destination, trusted_root=trusted, authorized_at="2026-08-22T00:00:00Z")
    assert check_authorization(value, smoke) == []
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    _smoke(smoke, "changed")
    assert check_authorization(value, smoke)
    with pytest.raises(FileExistsError):
        init_authorization(smoke, destination, trusted_root=trusted, authorized_at="2026-08-22T00:00:00Z")


def test_authorization_rejects_symlink_parent(tmp_path: Path) -> None:
    trusted = tmp_path / "artifacts" / "source-spike"
    trusted.mkdir(parents=True)
    smoke = trusted / "smoke.json"
    _smoke(smoke)
    outside = tmp_path / "outside"
    outside.mkdir()
    (trusted / "ted-analysis-authorization").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        init_authorization(smoke, trusted / "ted-analysis-authorization/authorization.json", trusted_root=trusted, authorized_at="2026-08-22T00:00:00Z")
