from __future__ import annotations

import copy
import json
from pathlib import Path

from src.source_spike.github_analysis_manifest import validate_github_analysis_manifest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/source-spike/github-analysis.json"
COMPLIANCE_PATH = ROOT / "config/source-spike/compliance/github.json"


def load_inputs() -> tuple[dict[str, object], dict[str, object]]:
    return (
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
        json.loads(COMPLIANCE_PATH.read_text(encoding="utf-8")),
    )


def test_committed_analysis_manifest_freezes_four_archetypes_and_cutoff() -> None:
    manifest, compliance = load_inputs()

    assert validate_github_analysis_manifest(manifest, compliance) == []
    assert manifest["target_valid_records"] == 100
    assert manifest["published_before"] == "2026-08-12T00:00:00Z"
    assert manifest["random_seed"] == 20260812
    assert manifest["request"]["state"] == "all"
    assert manifest["repositories"] == [
        {"archetype": "end_user_application", "name": "microsoft/vscode", "quota": 25},
        {"archetype": "language_runtime", "name": "python/cpython", "quota": 25},
        {"archetype": "infrastructure_platform", "name": "kubernetes/kubernetes", "quota": 25},
        {"archetype": "data_workflow_library", "name": "pandas-dev/pandas", "quota": 25},
    ]


def test_analysis_manifest_rejects_drift_in_experiment_identity() -> None:
    manifest, compliance = load_inputs()

    for mutate, expected in (
        (lambda value: value.update(target_valid_records=10), "target_valid_records"),
        (lambda value: value.update(published_before="not-a-date"), "published_before"),
        (lambda value: value["repositories"][1].update(archetype=value["repositories"][0]["archetype"]), "archetypes must be unique"),
        (lambda value: value["repositories"][1].update(name=value["repositories"][0]["name"]), "repositories must be unique"),
        (lambda value: value["repositories"][0].update(quota=24), "quota"),
    ):
        changed = copy.deepcopy(manifest)
        mutate(changed)
        assert expected in "; ".join(validate_github_analysis_manifest(changed, compliance))
