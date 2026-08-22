import json
from pathlib import Path

from src.source_spike.ted_analysis_manifest import validate_ted_analysis_manifest


ROOT = Path(__file__).resolve().parents[2]


def test_committed_analysis_manifest_freezes_quota_budget_and_privacy() -> None:
    manifest = json.loads((ROOT / "config/source-spike/ted-analysis.json").read_text())
    capacity = json.loads((ROOT / "config/source-spike/ted-capacity.json").read_text())
    assert validate_ted_analysis_manifest(manifest, capacity) == []
    assert [value["quota"] for value in manifest["strata"]] == [25, 25, 25, 25]
    assert manifest["request"] == {"page_size": 100, "max_pages_per_stratum": 3, "max_logical_requests": 12, "max_http_attempts": 24, "deadline_seconds": 180, "max_response_bytes": 31457280, "request_timeout_seconds": 10}
    assert manifest["redaction_policy_version"] == "ted-contact-v1"


def test_analysis_manifest_rejects_budget_and_query_identity_drift() -> None:
    manifest = json.loads((ROOT / "config/source-spike/ted-analysis.json").read_text())
    capacity = json.loads((ROOT / "config/source-spike/ted-capacity.json").read_text())
    manifest["request"]["max_logical_requests"] = 13
    manifest["strata"][0]["name"] = "wrong"
    assert validate_ted_analysis_manifest(manifest, capacity)
