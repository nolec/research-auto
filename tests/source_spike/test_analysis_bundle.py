from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from src.source_spike.analysis_bundle import dataset_sha256, privacy_violations, write_run_bundle
from src.source_spike.labeling import create_stratified_labeling_assignments


def items() -> list[dict[str, object]]:
    values = []
    for repository_index, repository in enumerate(("a/one", "b/two", "c/three", "d/four")):
        for index in range(25):
            number = repository_index * 25 + index
            values.append({
                "document_id": f"github:{number}", "source": "github",
                "source_item_id": str(number), "source_url": f"https://github.com/{repository}/issues/{number}",
                "item_type": "issue", "author_hash": f"{number + 1:064x}",
                "community": repository, "thread_id": f"{repository}:{number}", "parent_id": None,
                "title": f"Issue {number}", "text": f"A concrete workflow problem with enough normalized detail for analysis number {number}.",
                "text_fingerprint": f"{number + 1000:064x}", "text_length": 79,
                "original_text_length": 79, "text_truncated": False,
                "published_at": "2026-08-11T00:00:00Z", "updated_at": None,
                "language": None, "engagement": {"comments": 1},
                "source_metadata": {"state": "open", "labels": []},
                "collected_at": "2026-08-12T00:00:00Z", "collector_version": "0.2.0",
                "fetch_run_id": "run-100",
            })
    return values


def test_stratified_assignments_select_five_per_repository() -> None:
    assignments = create_stratified_labeling_assignments(items(), seed=20260812)

    assert len(assignments) == 20
    assert sum(value.split == "development" for value in assignments) == 10
    assert sum(value.requires_second_review for value in assignments) == 5
    assert {value.stratum: sum(item.stratum == value.stratum for item in assignments) for value in assignments} == {
        "a/one": 5, "b/two": 5, "c/three": 5, "d/four": 5,
    }


def test_privacy_scan_rejects_raw_identity_payload_and_secret() -> None:
    unsafe = items()
    unsafe[0]["source_metadata"] = {"user": {"login": "raw-user"}}
    unsafe[1]["text"] = "TOKEN-CANARY"

    violations = privacy_violations(unsafe, secrets=("TOKEN-CANARY",))

    assert any("source_metadata.user" in value for value in violations)
    assert any("configured secret" in value for value in violations)


def test_dataset_hash_is_order_independent_and_content_sensitive() -> None:
    source = items()
    assert dataset_sha256(source) == dataset_sha256(list(reversed(source)))
    changed = items()
    changed[0]["text"] = "Changed normalized public issue content with sufficient detail."
    assert dataset_sha256(source) != dataset_sha256(changed)


def test_dataset_hash_and_privacy_support_immutable_collection_items() -> None:
    frozen = [MappingProxyType(value) for value in items()]

    assert dataset_sha256(frozen) == dataset_sha256(items())
    assert privacy_violations(frozen) == []


def test_bundle_failure_does_not_replace_latest_qualified(tmp_path: Path) -> None:
    latest = tmp_path / "latest-qualified.json"
    latest.write_text('{"run_id":"previous"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="privacy"):
        write_run_bundle(
            tmp_path, run_id="run-100", items=items(), collection_result={"run_id": "run-100"},
            assignments=[], qualified=True, secrets=(items()[0]["text"],),
        )

    assert json.loads(latest.read_text())["run_id"] == "previous"
    assert not (tmp_path / "runs/run-100").exists()


def test_source_qualification_is_namespaced_and_cannot_override_authority(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reserved qualification key"):
        write_run_bundle(
            tmp_path,
            run_id="run-100",
            items=items(),
            collection_result={"run_id": "run-100", "status": "success", "manifest_hash": "a" * 64},
            assignments=[],
            qualified=False,
            source_qualification={"qualified": True},
        )
