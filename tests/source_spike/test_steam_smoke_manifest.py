from __future__ import annotations

import copy
import json
from pathlib import Path

from src.source_spike.steam_smoke_manifest import validate_steam_smoke_manifest


ROOT = Path(__file__).resolve().parents[2]


def records() -> tuple[dict, dict]:
    manifest = json.loads((ROOT / "config/source-spike/steam-smoke.json").read_text())
    compliance = json.loads(
        (ROOT / "config/source-spike/compliance/steam.json").read_text()
    )
    return manifest, compliance


def test_manifest_freezes_four_unique_archetypes_and_ninety_day_window() -> None:
    manifest, compliance = records()
    assert validate_steam_smoke_manifest(manifest, compliance) == []
    assert [value["quota"] for value in manifest["applications"]] == [3, 3, 2, 2]


def test_manifest_rejects_duplicate_apps_archetypes_and_bad_quota() -> None:
    manifest, compliance = records()
    changed = copy.deepcopy(manifest)
    changed["applications"][1]["appid"] = changed["applications"][0]["appid"]
    changed["applications"][1]["archetype"] = changed["applications"][0]["archetype"]
    changed["applications"][1]["quota"] = 2
    errors = validate_steam_smoke_manifest(changed, compliance)
    assert "application appids must be unique" in errors
    assert "application archetypes must be unique" in errors
    assert "application quotas must total target_valid_records" in errors


def test_manifest_rejects_compliance_drift() -> None:
    manifest, compliance = records()
    compliance["decision"] = "blocked"
    assert validate_steam_smoke_manifest(manifest, compliance) == [
        "compliance hash mismatch"
    ]


def test_manifest_rejects_unbounded_or_biased_request_policy() -> None:
    manifest, compliance = records()
    for field, value in (
        ("filter", "all"), ("language", "all"), ("review_type", "negative"),
        ("purchase_type", "steam"), ("filter_offtopic_activity", 0),
    ):
        changed = copy.deepcopy(manifest)
        changed["request"][field] = value
        assert validate_steam_smoke_manifest(changed, compliance)
