import json
from pathlib import Path

from src.source_spike.ted_smoke_manifest import validate_ted_smoke_manifest


ROOT = Path(__file__).resolve().parents[2]


def test_committed_ted_smoke_manifest_has_exact_quotas_and_budgets() -> None:
    manifest = json.loads((ROOT / "config/source-spike/ted-smoke.json").read_text())
    authorization = json.loads((ROOT / "config/source-spike/ted-smoke-authorization.json").read_text())
    capacity = json.loads((ROOT / "config/source-spike/ted-capacity.json").read_text())
    assert validate_ted_smoke_manifest(manifest, authorization, capacity) == []
    assert [(s["cpv_prefix"], s["quota"]) for s in manifest["strata"]] == [("48", 3), ("79", 3), ("85", 2), ("50", 2)]
    assert manifest["request"] == {"page_size": 100, "max_pages_per_stratum": 2, "max_logical_requests": 8, "max_http_attempts": 16, "deadline_seconds": 45, "max_response_bytes": 10485760, "request_timeout_seconds": 10}


def test_manifest_rejects_stratum_name_to_query_identity_drift() -> None:
    manifest = json.loads((ROOT / "config/source-spike/ted-smoke.json").read_text())
    authorization = json.loads((ROOT / "config/source-spike/ted-smoke-authorization.json").read_text())
    capacity = json.loads((ROOT / "config/source-spike/ted-capacity.json").read_text())
    manifest["strata"][0]["name"], manifest["strata"][1]["name"] = manifest["strata"][1]["name"], manifest["strata"][0]["name"]
    assert validate_ted_smoke_manifest(manifest, authorization, capacity)
