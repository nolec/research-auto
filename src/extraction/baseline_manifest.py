from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from src.extraction.development_slice import SourceArtifacts


_SCHEMA_VERSION = "development-baseline-manifest/v1"
_ARTIFACT_CUSTODY = "local_ignored"
_EXPECTED_SOURCES = frozenset({"github", "stackexchange", "steam", "ted"})
_PATH_FIELDS = frozenset({"qualified_run", "review_root", "primary_submission"})


@dataclass(frozen=True)
class LoadedBaselineManifest:
    sources: dict[str, SourceArtifacts]
    receipt: dict[str, object]


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _safe_path(repo_root: Path, value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty repository-relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} must be a repository-relative path")
    resolved = (repo_root / relative).resolve()
    if not resolved.is_relative_to(repo_root):
        raise ValueError(f"{field} must be a repository-relative path")
    return resolved


def load_baseline_manifest(
    manifest_path: Path, *, repo_root: Path
) -> LoadedBaselineManifest:
    root = repo_root.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "manifest_id",
        "artifact_custody",
        "sources",
    }:
        raise ValueError("baseline manifest fields are invalid")
    if manifest["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("baseline manifest schema_version is invalid")
    manifest_id = manifest["manifest_id"]
    if not isinstance(manifest_id, str) or not manifest_id.strip():
        raise ValueError("baseline manifest_id must be a non-empty string")
    if manifest["artifact_custody"] != _ARTIFACT_CUSTODY:
        raise ValueError("baseline artifact_custody must be local_ignored")
    source_values = manifest["sources"]
    if not isinstance(source_values, Mapping) or set(source_values) != _EXPECTED_SOURCES:
        raise ValueError(
            "baseline manifest requires exactly github, stackexchange, steam, and ted"
        )

    sources: dict[str, SourceArtifacts] = {}
    for source in sorted(_EXPECTED_SOURCES):
        value = source_values[source]
        if not isinstance(value, Mapping) or set(value) != _PATH_FIELDS:
            raise ValueError(f"{source} artifact path fields are invalid")
        qualified_run = _safe_path(root, value["qualified_run"], field="qualified_run")
        review_root = _safe_path(root, value["review_root"], field="review_root")
        primary_submission = _safe_path(
            root, value["primary_submission"], field="primary_submission"
        )
        if not qualified_run.is_dir():
            raise ValueError(f"{source} qualified_run does not exist as a directory")
        if not review_root.is_dir():
            raise ValueError(f"{source} review_root does not exist as a directory")
        if not primary_submission.is_file():
            raise ValueError(f"{source} primary_submission does not exist as a file")
        sources[source] = SourceArtifacts(
            qualified_run,
            review_root,
            primary_submission,
        )

    receipt = {
        "schema_version": _SCHEMA_VERSION,
        "manifest_id": manifest_id,
        "artifact_custody": _ARTIFACT_CUSTODY,
        "manifest_sha256": _digest(manifest),
        "source_count": len(sources),
        "status": "validated",
    }
    return LoadedBaselineManifest(sources, receipt)
