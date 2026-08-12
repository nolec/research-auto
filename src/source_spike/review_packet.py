from __future__ import annotations

import json
import os
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Callable
from uuid import uuid4

from src.source_spike.analysis_bundle import dataset_sha256


_PACKET_KEYS = (
    "assignment_id", "source", "title", "normalized_text", "published_at", "canonical_url"
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def validate_review_packet_bundle(
    root: Path, qualification: dict[str, object] | None = None
) -> dict[str, object]:
    manifest_path = root / "packet/bundle-manifest.json"
    required = (
        root / "packet/primary.json", root / "packet/secondary.json",
        root / "internal/assignment-map.json", manifest_path,
    )
    if not all(path.is_file() for path in required):
        raise ValueError("existing review packet bundle is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    provenance_keys = ("run_id", "dataset_sha256", "manifest_hash")
    if qualification is not None and any(
        manifest.get(key) != qualification.get(key) for key in provenance_keys
    ):
        raise ValueError("existing review packet provenance mismatch")
    expected_files = {
        "packet/primary.json",
        "packet/secondary.json",
        "internal/assignment-map.json",
    }
    file_hashes = manifest.get("file_sha256")
    if not isinstance(file_hashes, dict) or set(file_hashes) != expected_files:
        raise ValueError("review packet manifest file set mismatch")
    for relative, expected in file_hashes.items():
        if _digest(root / relative) != expected:
            raise ValueError(f"review packet hash mismatch: {relative}")
    primary = json.loads((root / "packet/primary.json").read_text(encoding="utf-8"))
    secondary = json.loads((root / "packet/secondary.json").read_text(encoding="utf-8"))
    mapping = json.loads((root / "internal/assignment-map.json").read_text(encoding="utf-8"))
    primary_ids = [value.get("assignment_id") for value in primary]
    secondary_ids = [value.get("assignment_id") for value in secondary]
    mapping_ids = [value.get("assignment_id") for value in mapping]
    expected_secondary = [
        value.get("assignment_id") for value in mapping if value.get("requires_second_review") is True
    ]
    if len(primary_ids) != len(set(primary_ids)) or set(primary_ids) != set(mapping_ids):
        raise ValueError("review packet primary assignment mismatch")
    if len(secondary_ids) != len(set(secondary_ids)) or set(secondary_ids) != set(expected_secondary):
        raise ValueError("review packet secondary assignment mismatch")
    return manifest


def build_review_packet_bundle(
    qualified_run: Path,
    review_root: Path,
    *,
    id_factory: Callable[[], object] = uuid4,
) -> dict[str, object]:
    qualification = json.loads((qualified_run / "qualification.json").read_text(encoding="utf-8"))
    if qualification.get("qualified") is not True:
        raise ValueError("source run is not qualified")
    items = [
        json.loads(line)
        for line in (qualified_run / "raw-source-items.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    if dataset_sha256(items) != qualification.get("dataset_sha256"):
        raise ValueError("qualified dataset hash mismatch")
    if review_root.exists():
        return validate_review_packet_bundle(review_root, qualification)
    assignments = json.loads((qualified_run / "labeling-assignments.json").read_text(encoding="utf-8"))
    by_document = {item["document_id"]: item for item in items}
    mapping: list[dict[str, object]] = []
    primary: list[dict[str, object]] = []
    secondary: list[dict[str, object]] = []
    for assignment in assignments:
        item = by_document[assignment["document_id"]]
        assignment_id = str(id_factory())
        mapped = {"assignment_id": assignment_id, **assignment}
        mapping.append(mapped)
        record = {
            "assignment_id": assignment_id,
            "source": item["source"],
            "title": item["title"],
            "normalized_text": item["text"],
            "published_at": item["published_at"],
            "canonical_url": item["source_url"],
        }
        primary.append(record)
        if assignment["requires_second_review"]:
            secondary.append(record)
    if len(primary) != 20 or len(secondary) != 5:
        raise ValueError("qualified assignments must contain primary 20 and secondary 5")
    temporary = review_root.with_name(f".{review_root.name}.tmp")
    if temporary.exists():
        raise ValueError("temporary review packet bundle already exists")
    try:
        (temporary / "packet").mkdir(parents=True)
        (temporary / "internal").mkdir()
        files = {
            "packet/primary.json": primary,
            "packet/secondary.json": secondary,
            "internal/assignment-map.json": mapping,
        }
        for relative, value in files.items():
            (temporary / relative).write_bytes(_json_bytes(value))
        manifest = {
            "run_id": qualification["run_id"],
            "dataset_sha256": qualification["dataset_sha256"],
            "manifest_hash": qualification["manifest_hash"],
            "primary_count": 20,
            "secondary_count": 5,
            "packet_fields": list(_PACKET_KEYS),
            "file_sha256": {relative: _digest(temporary / relative) for relative in files},
        }
        (temporary / "packet/bundle-manifest.json").write_bytes(_json_bytes(manifest))
        os.replace(temporary, review_root)
        return manifest
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
