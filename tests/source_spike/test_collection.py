from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping

import pytest

from src.source_spike.adapters.base import (
    CollectionResult,
    CollectionStatus,
    SegmentResult,
    TerminationReason,
)
from src.source_spike.collection import collect_source, operational_metrics_observed
from src.source_spike.protocol import content_sha256
from src.source_spike.raw_items import canonical_text_fingerprint


NOW = datetime(2026, 8, 11, 7, 0, tzinfo=timezone.utc)


def raw_item(run_id: str, version: str) -> dict[str, object]:
    text = "A public issue explains a repeated workflow failure with concrete impact."
    return {
        "document_id": "github:1",
        "source": "github",
        "source_item_id": "1",
        "source_url": "https://github.com/example/project/issues/1",
        "item_type": "issue",
        "author_hash": "1" * 64,
        "community": "example/project",
        "thread_id": "example/project:1",
        "parent_id": None,
        "title": "Repeated workflow failure",
        "text": text,
        "text_fingerprint": canonical_text_fingerprint(text),
        "text_length": len(text),
        "original_text_length": len(text),
        "text_truncated": False,
        "published_at": "2026-08-10T00:00:00Z",
        "updated_at": None,
        "language": "en",
        "engagement": {"comments": 1},
        "source_metadata": {"state": "open", "labels": ["bug"]},
        "collected_at": "2026-08-11T07:00:00Z",
        "collector_version": version,
        "fetch_run_id": run_id,
    }


def adapter_result(
    *,
    source: str = "github",
    run_id: str = "run-fixed",
    manifest_version: str = "smoke-1.0.0",
    adapter_version: str = "1.0.0",
    target: int = 1,
    success: bool = True,
    manifest_hash: str | None = None,
    compliance_hash: str | None = None,
) -> CollectionResult:
    return CollectionResult(
        source=source,
        run_id=run_id,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
        target_valid_count=target,
        status=CollectionStatus.SUCCESS if success else CollectionStatus.FAILED,
        items=[raw_item(run_id, adapter_version)] if success else [],
        invalid_items=[],
        request_count=1,
        response_bytes=1024,
        retry_count=0,
        rate_limit_events=0,
        error_code=None if success else "request_failed",
        error_message=None,
        manifest_version=manifest_version,
        adapter_version=adapter_version,
        termination_reason=(
            TerminationReason.TARGET_REACHED
            if success
            else TerminationReason.PREREQUISITE_FAILED
        ),
        fetched_item_count=1 if success else 0,
        processed_item_count=1 if success else 0,
        accepted_item_count=1 if success else 0,
        rejected_item_count=0,
        segment_results=(
            SegmentResult("repository", "example/project", target, 1 if success else 0),
        ),
        manifest_hash=manifest_hash or content_sha256({}),
        compliance_hash=compliance_hash,
    )


class HealthyAdapter:
    source = "github"
    adapter_version = "1.0.0"

    def __init__(self, *, mutate_config: bool = False) -> None:
        self.mutate_config = mutate_config
        self.received: tuple[str, str, int] | None = None
        self.returned: CollectionResult | None = None

    def collect(
        self,
        source_config: Mapping[str, object],
        target_valid_count: int,
        *,
        run_id: str,
        manifest_version: str,
    ) -> CollectionResult:
        self.received = (run_id, manifest_version, target_valid_count)
        if self.mutate_config:
            source_config["nested"]["values"].append("mutated")  # type: ignore[index,union-attr]
        self.returned = adapter_result(
            run_id=run_id,
            manifest_version=manifest_version,
            target=target_valid_count,
            manifest_hash=content_sha256(source_config),
            compliance_hash=(
                str(source_config["compliance_hash"])
                if "compliance_hash" in source_config
                else None
            ),
        )
        return self.returned


class RaisingAdapter:
    source = "github"
    adapter_version = "1.0.0"

    def collect(self, *args: object, **kwargs: object) -> CollectionResult:
        raise RuntimeError("token=super-secret response_body=private")


class InterruptingAdapter(RaisingAdapter):
    def collect(self, *args: object, **kwargs: object) -> CollectionResult:
        raise KeyboardInterrupt


class ReturningAdapter:
    source = "github"
    adapter_version = "1.0.0"

    def __init__(self, value: object) -> None:
        self.value = value

    def collect(self, *args: object, **kwargs: object) -> object:
        return self.value


def clock() -> datetime:
    clock.current += timedelta(seconds=1)
    return clock.current


clock.current = NOW  # type: ignore[attr-defined]


def test_runner_passes_one_run_context_and_preserves_a_valid_result() -> None:
    adapter = HealthyAdapter()

    collection = collect_source(
        adapter,
        {"repository": "example/project"},
        1,
        manifest_version="smoke-1.0.0",
        run_id="run-fixed",
        clock=clock,
    )

    assert adapter.received == ("run-fixed", "smoke-1.0.0", 1)
    assert collection is adapter.returned
    assert collection.run_id == "run-fixed"
    assert collection.status is CollectionStatus.SUCCESS
    assert operational_metrics_observed(collection) is True


def test_runner_isolates_adapter_exception_without_leaking_its_message() -> None:
    source_config = {"repository": "example/project"}
    collection = collect_source(
        RaisingAdapter(),
        source_config,
        10,
        manifest_version="smoke-1.0.0",
        run_id="run-failed",
        clock=clock,
    )

    assert collection.status is CollectionStatus.FAILED
    assert collection.run_id == "run-failed"
    assert collection.error_code == "runner_adapter_exception"
    assert collection.error_message == "Unexpected adapter failure"
    assert "secret" not in str(collection.to_dict())
    assert collection.manifest_hash == content_sha256(source_config)
    assert collection.compliance_hash is None
    assert operational_metrics_observed(collection) is False


def test_adapter_generated_failed_result_keeps_observed_metrics() -> None:
    expected = adapter_result(success=False)

    collection = collect_source(
        ReturningAdapter(expected),
        {},
        1,
        manifest_version="smoke-1.0.0",
        run_id="run-fixed",
        clock=clock,
    )

    assert collection is expected
    assert collection.status is CollectionStatus.FAILED
    assert operational_metrics_observed(collection) is True


def test_adapter_exception_code_keeps_adapter_observed_metrics() -> None:
    expected = adapter_result(success=False).replace(error_code="adapter_exception")

    collection = collect_source(
        ReturningAdapter(expected),
        {},
        1,
        manifest_version="smoke-1.0.0",
        run_id="run-fixed",
        clock=clock,
    )

    assert collection is expected
    assert collection.request_count == 1
    assert operational_metrics_observed(collection) is True


def test_runner_rejects_adapter_result_using_reserved_runner_error_code() -> None:
    returned = adapter_result(success=False).replace(
        error_code="runner_adapter_exception"
    )

    collection = collect_source(
        ReturningAdapter(returned),
        {},
        1,
        manifest_version="smoke-1.0.0",
        run_id="run-fixed",
        clock=clock,
    )

    assert collection is not returned
    assert collection.error_code == "runner_invalid_adapter_result"
    assert operational_metrics_observed(collection) is False


@pytest.mark.parametrize(
    ("result_value", "error_code"),
    [
        ({"status": "success"}, "runner_invalid_adapter_result"),
        (adapter_result(source="other", success=False), "runner_source_mismatch"),
        (
            adapter_result(adapter_version="2.0.0", success=False),
            "runner_adapter_version_mismatch",
        ),
        (
            adapter_result(run_id="other-run", success=False),
            "runner_run_id_mismatch",
        ),
        (
            adapter_result(manifest_version="other", success=False),
            "runner_manifest_version_mismatch",
        ),
        (adapter_result(target=2, success=False), "runner_target_mismatch"),
        (
            adapter_result(manifest_hash="f" * 64, success=False),
            "runner_manifest_hash_mismatch",
        ),
        (
            adapter_result(compliance_hash="f" * 64, success=False),
            "runner_compliance_hash_mismatch",
        ),
    ],
)
def test_runner_converts_each_return_contract_violation_to_a_distinct_failure(
    result_value: object, error_code: str
) -> None:
    collection = collect_source(
        ReturningAdapter(result_value),
        {},
        1,
        manifest_version="smoke-1.0.0",
        run_id="run-fixed",
        clock=clock,
    )

    assert collection.status is CollectionStatus.FAILED
    assert collection.error_code == error_code
    assert operational_metrics_observed(collection) is False


def test_runner_passes_a_deep_copy_of_source_config() -> None:
    source_config = {"nested": {"values": ["original"]}}

    collect_source(
        HealthyAdapter(mutate_config=True),
        source_config,
        1,
        manifest_version="smoke-1.0.0",
        run_id="run-fixed",
        clock=clock,
    )

    assert source_config == {"nested": {"values": ["original"]}}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"target_valid_count": 0}, "target_valid_count"),
        ({"manifest_version": 123}, "manifest_version"),
        ({"run_id": ""}, "run_id"),
        ({"source_config": ["not", "a", "mapping"]}, "source_config"),
        ({"source_config": {"value": float("nan")}}, "JSON-compatible"),
    ],
)
def test_runner_rejects_invalid_caller_input(
    kwargs: dict[str, object], message: str
) -> None:
    arguments: dict[str, object] = {
        "adapter": HealthyAdapter(),
        "source_config": {},
        "target_valid_count": 1,
        "manifest_version": "smoke-1.0.0",
        "run_id": "run-fixed",
        "clock": clock,
    }
    arguments.update(kwargs)

    with pytest.raises(ValueError, match=message):
        collect_source(**arguments)  # type: ignore[arg-type]


def test_runner_does_not_swallow_process_control_exceptions() -> None:
    with pytest.raises(KeyboardInterrupt):
        collect_source(
            InterruptingAdapter(),
            {},
            1,
            manifest_version="smoke-1.0.0",
            run_id="run-fixed",
            clock=clock,
        )
