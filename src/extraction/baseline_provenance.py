from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Sequence


RULE_V1_IMPLEMENTATION_PATHS = (
    "schemas/baseline-calibration-artifacts.schema.json",
    "src/extraction/baseline_calibration.py",
    "src/extraction/baseline_manifest.py",
    "src/extraction/baseline_provenance.py",
    "src/extraction/calibration_evaluator.py",
    "src/extraction/development_slice.py",
    "src/extraction/rule_baseline.py",
)


def canonical_digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def build_implementation_bundle(
    repo_root: Path, implementation_files: Sequence[Path]
) -> dict[str, object]:
    root = repo_root.resolve()
    files: dict[str, str] = {}
    for candidate in implementation_files:
        path = candidate.resolve()
        if not path.is_file():
            raise ValueError(f"implementation file is missing: {candidate}")
        if not path.is_relative_to(root):
            raise ValueError("implementation files must be inside the repository root")
        relative = path.relative_to(root).as_posix()
        if relative in files:
            raise ValueError("implementation file list contains duplicates")
        files[relative] = file_digest(path)
    if not files:
        raise ValueError("implementation file list must not be empty")
    identity = {
        "schema_version": "baseline-implementation-bundle/v1",
        "files": dict(sorted(files.items())),
    }
    return {
        **identity,
        "implementation_bundle_sha256": canonical_digest(identity),
    }


def build_rule_v1_implementation_bundle(repo_root: Path) -> dict[str, object]:
    root = repo_root.resolve()
    return build_implementation_bundle(
        root,
        tuple(root / relative for relative in RULE_V1_IMPLEMENTATION_PATHS),
    )
