from __future__ import annotations

import json
from pathlib import Path

from src.source_spike.stackexchange_capacity_manifest import (
    required_capacity,
    validate_stackexchange_capacity_manifest,
)


ROOT = Path(__file__).resolve().parents[2]


def test_capacity_policy_rounds_twenty_five_times_one_point_five_up() -> None:
    assert required_capacity(25, 1.5) == 38


def test_frozen_capacity_manifest_validates_actual_probe_contract() -> None:
    manifest = json.loads((ROOT / "config/source-spike/stackexchange-capacity.json").read_text())
    analysis = json.loads((ROOT / "config/source-spike/stackexchange-analysis.json").read_text())
    compliance = json.loads((ROOT / "config/source-spike/compliance/stackexchange.json").read_text())
    filter_record = json.loads((ROOT / "config/source-spike/stackexchange-filter.json").read_text())

    assert validate_stackexchange_capacity_manifest(manifest, analysis, compliance, filter_record) == []
    assert manifest["target_valid_records"] == 152
    assert {site["quota"] for site in manifest["sites"]} == {38}


def test_capacity_manifest_rejects_threshold_and_analysis_hash_drift() -> None:
    manifest = json.loads((ROOT / "config/source-spike/stackexchange-capacity.json").read_text())
    analysis = json.loads((ROOT / "config/source-spike/stackexchange-analysis.json").read_text())
    compliance = json.loads((ROOT / "config/source-spike/compliance/stackexchange.json").read_text())
    filter_record = json.loads((ROOT / "config/source-spike/stackexchange-filter.json").read_text())
    manifest["sites"][0]["quota"] = 37
    assert validate_stackexchange_capacity_manifest(manifest, analysis, compliance, filter_record)
    drifted = json.loads((ROOT / "config/source-spike/stackexchange-capacity.json").read_text())
    drifted["analysis_manifest_hash"] = "0" * 64
    assert "analysis manifest hash mismatch" in validate_stackexchange_capacity_manifest(drifted, analysis, compliance, filter_record)
