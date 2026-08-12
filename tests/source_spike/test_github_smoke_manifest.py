from __future__ import annotations

import copy
import json
from pathlib import Path

from src.source_spike.github_smoke_manifest import validate_github_smoke_manifest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config" / "source-spike" / "github-smoke.json"
COMPLIANCE_PATH = ROOT / "config" / "source-spike" / "compliance" / "github.json"


def load_inputs() -> tuple[dict[str, object], dict[str, object]]:
    return (
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
        json.loads(COMPLIANCE_PATH.read_text(encoding="utf-8")),
    )


def test_committed_github_smoke_manifest_is_frozen_and_valid() -> None:
    manifest, compliance = load_inputs()

    assert validate_github_smoke_manifest(manifest, compliance) == []
    assert manifest["source"] == "github"
    assert manifest["target_valid_records"] == 10
    assert manifest["max_items_per_author"] == 2
    assert manifest["request"] == {
        "endpoint": "/repos/{owner}/{repo}/issues",
        "state": "open",
        "sort": "created",
        "direction": "desc",
        "per_page": 30,
        "max_pages_total": 4,
        "max_requests": 8,
    }
    repositories = manifest["repositories"]
    assert repositories == [
        {"name": "microsoft/vscode", "quota": 5},
        {"name": "python/cpython", "quota": 5},
    ]


def test_manifest_rejects_duplicate_repositories_and_wrong_quota_total() -> None:
    manifest, compliance = load_inputs()
    changed = copy.deepcopy(manifest)
    repositories = changed["repositories"]
    assert isinstance(repositories, list)
    repositories[1]["name"] = repositories[0]["name"]
    repositories[1]["quota"] = 4

    errors = validate_github_smoke_manifest(changed, compliance)

    assert "repositories must be unique" in errors
    assert "repository quotas must total target_valid_records (9 != 10)" in errors


def test_manifest_rejects_case_insensitive_duplicate_repositories() -> None:
    manifest, compliance = load_inputs()
    changed = copy.deepcopy(manifest)
    changed["repositories"][1]["name"] = "Microsoft/VSCode"

    assert validate_github_smoke_manifest(changed, compliance) == [
        "repositories must be unique"
    ]


def test_manifest_rejects_compliance_drift() -> None:
    manifest, compliance = load_inputs()
    changed = copy.deepcopy(compliance)
    changed["allowed_usage"] = "changed after manifest freeze"

    assert validate_github_smoke_manifest(manifest, changed) == [
        "compliance hash mismatch"
    ]


def test_manifest_rejects_retry_budget_that_can_exceed_request_budget() -> None:
    manifest, compliance = load_inputs()
    changed = copy.deepcopy(manifest)
    changed["retry"]["max_retries"] = changed["request"]["max_requests"]

    assert validate_github_smoke_manifest(changed, compliance) == [
        "max_retries must be less than max_requests"
    ]


def test_manifest_schema_rejects_unbounded_collection() -> None:
    manifest, compliance = load_inputs()
    changed = copy.deepcopy(manifest)
    del changed["request"]["max_requests"]

    errors = validate_github_smoke_manifest(changed, compliance)

    assert any("max_requests" in error and "required" in error for error in errors)
