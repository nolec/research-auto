from __future__ import annotations

import json
from pathlib import Path

from src.source_spike.protocol import content_sha256
from src.source_spike.stackexchange_analysis_manifest import validate_stackexchange_analysis_manifest


ROOT = Path(__file__).resolve().parents[2]


def records():
    manifest = json.loads((ROOT / "config/source-spike/stackexchange-analysis.json").read_text())
    compliance = json.loads((ROOT / "config/source-spike/compliance/stackexchange.json").read_text())
    filter_record = json.loads((ROOT / "config/source-spike/stackexchange-filter.json").read_text())
    return manifest, compliance, filter_record


def test_frozen_analysis_manifest_is_valid_and_balanced() -> None:
    manifest, compliance, filter_record = records()
    assert validate_stackexchange_analysis_manifest(manifest, compliance, filter_record) == []
    assert [site["quota"] for site in manifest["sites"]] == [25, 25, 25, 25]
    assert len({site["stratum"] for site in manifest["sites"]}) == 4
    assert manifest["filter_hash"] == content_sha256(filter_record)


def test_analysis_manifest_rejects_quota_and_provenance_drift() -> None:
    manifest, compliance, filter_record = records()
    changed = json.loads(json.dumps(manifest))
    changed["sites"][0]["quota"] = 24
    assert validate_stackexchange_analysis_manifest(changed, compliance, filter_record)
    drifted = json.loads(json.dumps(manifest))
    drifted["compliance_hash"] = "0" * 64
    assert "compliance hash mismatch" in validate_stackexchange_analysis_manifest(drifted, compliance, filter_record)
