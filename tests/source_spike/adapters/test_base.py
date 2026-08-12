from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from src.contracts.validation import FORMAT_CHECKER
from src.source_spike.adapters.base import (
    CollectionResult,
    CollectionStatus,
    InvalidItem,
    SegmentResult,
    TerminationReason,
)
from src.source_spike.raw_items import canonical_text_fingerprint


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "schemas" / "collection-result.schema.json"
RAW_SCHEMA_PATH = ROOT / "schemas" / "raw-source-item.schema.json"
NOW = datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc)


def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    raw_schema = json.loads(RAW_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resource(
        raw_schema["$id"], Resource.from_contents(raw_schema)
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FORMAT_CHECKER,
    )


def raw_item(index: int, *, run_id: str = "run-1", version: str = "1.0.0") -> dict:
    text = f"A concrete public issue describes repeated workflow friction number {index}."
    return {
        "document_id": f"github:{index}",
        "source": "github",
        "source_item_id": str(index),
        "source_url": f"https://github.com/example/project/issues/{index}",
        "item_type": "issue",
        "author_hash": f"{index:064x}",
        "community": "example/project",
        "thread_id": f"example/project:{index}",
        "parent_id": None,
        "title": f"Issue {index}",
        "text": text,
        "text_fingerprint": canonical_text_fingerprint(text),
        "text_length": len(text),
        "original_text_length": len(text),
        "text_truncated": False,
        "published_at": "2026-08-10T00:00:00Z",
        "updated_at": None,
        "language": "en",
        "engagement": {"comments": 2},
        "source_metadata": {"state": "open", "labels": ["bug"]},
        "collected_at": "2026-08-11T06:00:00Z",
        "collector_version": version,
        "fetch_run_id": run_id,
    }


def result(
    *,
    items: list[dict] | None = None,
    target: int = 1,
    status: CollectionStatus = CollectionStatus.SUCCESS,
    invalid_items: list[InvalidItem] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> CollectionResult:
    resolved_items = items if items is not None else [raw_item(1)]
    resolved_invalid = invalid_items or []
    accepted_count = len(resolved_items)
    rejected_count = len(resolved_invalid)
    termination_reason = (
        TerminationReason.TARGET_REACHED
        if status is CollectionStatus.SUCCESS
        else TerminationReason.PAGE_BUDGET_EXHAUSTED
        if status is CollectionStatus.PARTIAL
        else TerminationReason.PREREQUISITE_FAILED
    )
    return CollectionResult(
        source="github",
        run_id="run-1",
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
        target_valid_count=target,
        status=status,
        items=resolved_items,
        invalid_items=resolved_invalid,
        request_count=1,
        response_bytes=2048,
        retry_count=0,
        rate_limit_events=0,
        error_code=error_code,
        error_message=error_message,
        manifest_version="smoke-1.0.0",
        adapter_version="1.0.0",
        termination_reason=termination_reason,
        fetched_item_count=accepted_count + rejected_count,
        processed_item_count=accepted_count + rejected_count,
        accepted_item_count=accepted_count,
        rejected_item_count=rejected_count,
        segment_results=(
            SegmentResult("repository", "example/project", target, accepted_count),
        ),
        manifest_hash="a" * 64,
        compliance_hash="b" * 64,
    )


def test_serialized_result_satisfies_schema_and_uses_utc_strings() -> None:
    payload = result().to_dict()

    assert not list(validator().iter_errors(payload))
    assert payload["status"] == "success"
    assert payload["started_at"].endswith("Z")
    assert payload["error_code"] is None
    assert payload["error_message"] is None
    assert payload["termination_reason"] == "target_reached"
    assert payload["failed_item_count"] == payload["rejected_item_count"]


def test_result_enforces_source_neutral_segment_and_metric_invariants() -> None:
    collection = result()

    assert collection.segment_results == (
        SegmentResult("repository", "example/project", 1, 1),
    )
    with pytest.raises(ValueError, match="processed_item_count"):
        collection.replace(processed_item_count=2)
    with pytest.raises(ValueError, match="segment accepted counts"):
        collection.replace(
            segment_results=(SegmentResult("repository", "example/project", 1, 0),)
        )


def test_status_requires_target_and_every_segment_quota() -> None:
    with pytest.raises(ValueError, match="status must be partial"):
        result().replace(
            target_valid_count=2,
            segment_results=(SegmentResult("repository", "example/project", 2, 1),),
        )


def test_prerequisite_failure_cannot_retain_accepted_items() -> None:
    with pytest.raises(ValueError, match="prerequisite_failed"):
        result().replace(termination_reason=TerminationReason.PREREQUISITE_FAILED)


def test_schema_registry_rejects_an_invalid_nested_raw_item() -> None:
    payload = result().to_dict()
    payload["items"][0]["author_hash"] = "not-a-hash"

    assert list(validator().iter_errors(payload))


def test_result_is_isolated_from_input_and_serialized_payload_mutation() -> None:
    item = raw_item(1)
    collection = result(items=[item])

    item["source_metadata"]["labels"].append("mutated")
    first_payload = collection.to_dict()
    first_payload["items"][0]["source_metadata"]["labels"].append("also-mutated")

    assert collection.to_dict()["items"][0]["source_metadata"]["labels"] == ["bug"]


@pytest.mark.parametrize(
    ("item_count", "target", "status", "error_code"),
    [
        (1, 1, CollectionStatus.SUCCESS, None),
        (1, 2, CollectionStatus.PARTIAL, "target_not_reached"),
        (0, 2, CollectionStatus.FAILED, "request_failed"),
    ],
)
def test_status_boundaries_are_enforced(
    item_count: int,
    target: int,
    status: CollectionStatus,
    error_code: str | None,
) -> None:
    collection = result(
        items=[raw_item(index + 1) for index in range(item_count)],
        target=target,
        status=status,
        error_code=error_code,
    )

    assert collection.status is status


def test_result_rejects_status_time_metric_and_error_inconsistency() -> None:
    with pytest.raises(ValueError, match="status must be partial"):
        result(target=2, status=CollectionStatus.SUCCESS)

    with pytest.raises(ValueError, match="timezone-aware"):
        result().replace(started_at=NOW.replace(tzinfo=None))

    with pytest.raises(ValueError, match="finished_at"):
        result().replace(finished_at=NOW - timedelta(seconds=1))

    with pytest.raises(ValueError, match="retry_count"):
        result().replace(retry_count=1)

    with pytest.raises(ValueError, match="success results cannot contain errors"):
        result(error_code="unexpected_error")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source", "other", "item source"),
        ("fetch_run_id", "other-run", "fetch_run_id"),
        ("collector_version", "2.0.0", "collector_version"),
        ("author_hash", "invalid", "invalid raw source item"),
    ],
)
def test_result_rejects_invalid_item_provenance(
    field: str, value: str, message: str
) -> None:
    item = raw_item(1)
    item[field] = value

    with pytest.raises(ValueError, match=message):
        result(items=[item])


def test_invalid_items_are_bounded_and_counted() -> None:
    invalid = InvalidItem(
        source_item_id=None,
        error_code="invalid_payload",
        errors=("required issue body is missing",),
    )
    collection = result(
        invalid_items=[invalid],
    )

    assert collection.to_dict()["invalid_items"] == [
        {
            "source_item_id": None,
            "error_code": "invalid_payload",
            "errors": ["required issue body is missing"],
        }
    ]

    with pytest.raises(ValueError, match="error_code"):
        InvalidItem(source_item_id=None, error_code="INVALID CODE", errors=("x",))
    with pytest.raises(ValueError, match="between 1 and 20"):
        InvalidItem(source_item_id=None, error_code="invalid", errors=())


def test_result_rejects_runtime_values_that_only_look_typed() -> None:
    with pytest.raises(ValueError, match="target_valid_count"):
        result().replace(target_valid_count=1.5)
    with pytest.raises(ValueError, match="items must contain mappings"):
        result().replace(items=["not-an-item"])
    with pytest.raises(ValueError, match="response_bytes"):
        result().replace(response_bytes=-1)
    with pytest.raises(ValueError, match="error_code"):
        result(
            target=2,
            status=CollectionStatus.PARTIAL,
            error_code="INVALID CODE",
        )
    with pytest.raises(ValueError, match="error_message"):
        result(
            target=2,
            status=CollectionStatus.PARTIAL,
            error_code="target_not_reached",
            error_message=1,  # type: ignore[arg-type]
        )


def test_invalid_item_rejects_non_string_error_entries() -> None:
    with pytest.raises(ValueError, match="each error"):
        InvalidItem(
            source_item_id=None,
            error_code="invalid",
            errors=(1,),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", 123),
        ("run_id", 456),
        ("manifest_version", 789),
        ("adapter_version", 101),
    ],
)
def test_failed_result_rejects_non_string_identifiers(
    field: str, value: int
) -> None:
    failed = result(
        items=[],
        target=1,
        status=CollectionStatus.FAILED,
        error_code="request_failed",
    )

    with pytest.raises(ValueError, match=f"{field} must be a non-empty string"):
        failed.replace(**{field: value})


def test_invalid_item_rejects_non_string_identity_and_error_code() -> None:
    with pytest.raises(ValueError, match="source_item_id"):
        InvalidItem(
            source_item_id=123,  # type: ignore[arg-type]
            error_code="invalid_payload",
            errors=("bad",),
        )
    with pytest.raises(ValueError, match="error_code"):
        InvalidItem(
            source_item_id=None,
            error_code=123,  # type: ignore[arg-type]
            errors=("bad",),
        )


def test_partial_result_rejects_non_string_error_code() -> None:
    with pytest.raises(ValueError, match="error_code"):
        result(
            target=2,
            status=CollectionStatus.PARTIAL,
            error_code=123,  # type: ignore[arg-type]
        )
