from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence


_FORBIDDEN_KEYS = frozenset(
    {"user", "login", "avatar_url", "profile", "email", "authorization", "token", "pull_request"}
)


def _canonical_json(value: object) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(nested) for nested in value]
    return value


def dataset_sha256(items: Sequence[Mapping[str, object]]) -> str:
    ordered = sorted(items, key=lambda item: str(item["document_id"]))
    payload = "\n".join(_canonical_json(item) for item in ordered).encode("utf-8")
    return sha256(payload).hexdigest()


def _forbidden_paths(value: object, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).casefold() in _FORBIDDEN_KEYS:
                paths.append(path)
            paths.extend(_forbidden_paths(nested, path))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_paths(nested, f"{prefix}[{index}]"))
    return paths


def privacy_violations(
    items: Sequence[Mapping[str, object]], *, secrets: Sequence[str] = ()
) -> list[str]:
    violations: list[str] = []
    for index, item in enumerate(items):
        violations.extend(f"item[{index}].{path}" for path in _forbidden_paths(item))
    serialized = _canonical_json(items)
    for secret in secrets:
        if secret and secret in serialized:
            violations.append("configured secret appears in normalized artifact")
    return sorted(set(violations))


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(_json_value(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_run_bundle(
    root: Path,
    *,
    run_id: str,
    items: Sequence[Mapping[str, object]],
    collection_result: Mapping[str, object],
    assignments: Sequence[object],
    qualified: bool,
    secrets: Sequence[str] = (),
) -> Path:
    if collection_result.get("run_id") != run_id:
        raise ValueError("collection result run_id mismatch")
    if any(item.get("fetch_run_id") != run_id for item in items):
        raise ValueError("item run_id mismatch")
    violations = privacy_violations(items, secrets=secrets)
    if violations:
        raise ValueError(f"privacy qualification failed: {'; '.join(violations)}")
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    destination = runs / run_id
    temporary = runs / f".{run_id}.tmp"
    if destination.exists() or temporary.exists():
        raise FileExistsError(f"run bundle already exists: {run_id}")
    temporary.mkdir()
    digest = dataset_sha256(items)
    try:
        ordered = sorted(items, key=lambda item: str(item["document_id"]))
        (temporary / "raw-source-items.jsonl").write_text(
            "".join(_canonical_json(item) + "\n" for item in ordered), encoding="utf-8"
        )
        _write_json(temporary / "collection-result.json", collection_result)
        assignment_values = [asdict(value) if is_dataclass(value) else value for value in assignments]
        _write_json(temporary / "labeling-assignments.json", assignment_values)
        qualification = {
            "run_id": run_id,
            "status": collection_result.get("status"),
            "accepted_item_count": len(items),
            "manifest_hash": collection_result.get("manifest_hash"),
            "dataset_sha256": digest,
            "privacy_qualification": "PASS",
            "privacy_violation_count": 0,
            "qualified": qualified,
        }
        _write_json(temporary / "qualification.json", qualification)
        _write_json(
            temporary / "bundle-manifest.json",
            {
                "run_id": run_id,
                "dataset_sha256": digest,
                "item_count": len(items),
                "assignment_count": len(assignments),
                "files": [
                    "raw-source-items.jsonl", "collection-result.json",
                    "qualification.json", "labeling-assignments.json",
                ],
            },
        )
        temporary.replace(destination)
        if qualified:
            pointer_temp = root / ".latest-qualified.tmp"
            _write_json(pointer_temp, {"run_id": run_id, "dataset_sha256": digest})
            os.replace(pointer_temp, root / "latest-qualified.json")
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination
