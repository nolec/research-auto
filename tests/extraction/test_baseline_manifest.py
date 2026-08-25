from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.extraction.baseline_manifest import load_baseline_manifest
from src.extraction.development_slice import (
    build_development_gold_sidecar,
    build_development_inference,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN_MANIFEST = REPO_ROOT / "configs/extraction/development-baseline-v1.json"
SOURCES = {"github", "stackexchange", "steam", "ted"}


@pytest.mark.skipif(
    os.environ.get("RESEARCH_AUTO_RUN_LOCAL_ARTIFACT_TESTS") != "1",
    reason="requires Git-ignored local source-spike artifact custody",
)
def test_frozen_manifest_projects_real_40_record_development_slice() -> None:
    loaded = load_baseline_manifest(FROZEN_MANIFEST, repo_root=REPO_ROOT)

    assert set(loaded.sources) == SOURCES
    assert loaded.receipt["schema_version"] == "development-baseline-manifest/v1"
    assert loaded.receipt["artifact_custody"] == "local_ignored"
    assert len(loaded.receipt["manifest_sha256"]) == 64

    inference = build_development_inference(loaded.sources)
    gold = build_development_gold_sidecar(loaded.sources)
    assert len(inference.corpus) == 40
    assert len(gold.labels) == 40
    assert inference.receipt["source_counts"] == {source: 10 for source in SOURCES}
    assert gold.receipt["source_counts"] == {source: 10 for source in SOURCES}


def test_manifest_loads_with_fixture_artifact_custody(tmp_path: Path) -> None:
    source_values = {}
    for source in SOURCES:
        qualified_run = tmp_path / "artifacts" / source
        review_root = qualified_run / "review"
        review_root.mkdir(parents=True)
        primary_submission = review_root / "primary.jsonl"
        primary_submission.write_text("", encoding="utf-8")
        source_values[source] = {
            "qualified_run": str(qualified_run.relative_to(tmp_path)),
            "review_root": str(review_root.relative_to(tmp_path)),
            "primary_submission": str(primary_submission.relative_to(tmp_path)),
        }
    manifest = {
        "schema_version": "development-baseline-manifest/v1",
        "manifest_id": "fixture",
        "artifact_custody": "local_ignored",
        "sources": source_values,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = load_baseline_manifest(path, repo_root=tmp_path)

    assert set(loaded.sources) == SOURCES
    assert loaded.receipt["artifact_custody"] == "local_ignored"


@pytest.mark.parametrize("bad_path", ["/tmp/outside", "../outside"])
def test_manifest_rejects_absolute_or_escaping_paths(
    tmp_path: Path, bad_path: str
) -> None:
    manifest = {
        "schema_version": "development-baseline-manifest/v1",
        "manifest_id": "bad-path",
        "artifact_custody": "local_ignored",
        "sources": {
            source: {
                "qualified_run": bad_path,
                "review_root": bad_path,
                "primary_submission": bad_path,
            }
            for source in SOURCES
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="repository-relative"):
        load_baseline_manifest(path, repo_root=tmp_path)


def test_manifest_rejects_wrong_source_set_and_missing_files(tmp_path: Path) -> None:
    wrong_sources = {
        "schema_version": "development-baseline-manifest/v1",
        "manifest_id": "wrong-sources",
        "artifact_custody": "local_ignored",
        "sources": {},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(wrong_sources), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly github, stackexchange, steam, and ted"):
        load_baseline_manifest(path, repo_root=tmp_path)

    missing = {
        **wrong_sources,
        "manifest_id": "missing-files",
        "sources": {
            source: {
                "qualified_run": f"artifacts/{source}",
                "review_root": f"artifacts/{source}/review",
                "primary_submission": f"artifacts/{source}/primary.jsonl",
            }
            for source in SOURCES
        },
    }
    path.write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(ValueError, match="does not exist"):
        load_baseline_manifest(path, repo_root=tmp_path)


def test_manifest_rejects_non_local_artifact_custody(tmp_path: Path) -> None:
    manifest = {
        "schema_version": "development-baseline-manifest/v1",
        "manifest_id": "wrong-custody",
        "artifact_custody": "tracked",
        "sources": {source: {} for source in SOURCES},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact_custody"):
        load_baseline_manifest(path, repo_root=tmp_path)
