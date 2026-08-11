from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Mapping
from uuid import uuid4

from src.source_spike.adapters.base import (
    CollectionResult,
    CollectionStatus,
    SourceAdapter,
)


_FALLBACK_MESSAGES = {
    "runner_adapter_exception": "Unexpected adapter failure",
    "runner_invalid_adapter_result": "Adapter returned an invalid result",
    "runner_source_mismatch": "Adapter result source does not match the adapter",
    "runner_adapter_version_mismatch": (
        "Adapter result version does not match the adapter"
    ),
    "runner_run_id_mismatch": "Adapter result run ID does not match the collection run",
    "runner_manifest_version_mismatch": (
        "Adapter result manifest version does not match"
    ),
    "runner_target_mismatch": "Adapter result target does not match the collection target",
}
_FALLBACK_ERROR_CODES = frozenset(_FALLBACK_MESSAGES)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _non_empty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _copy_source_config(source_config: object) -> dict[str, object]:
    if not isinstance(source_config, Mapping):
        raise ValueError("source_config must be a mapping")
    try:
        serialized = json.dumps(source_config, ensure_ascii=False, allow_nan=False)
        copied = json.loads(serialized)
    except (TypeError, ValueError) as error:
        raise ValueError("source_config must be JSON-compatible") from error
    if not isinstance(copied, dict):
        raise ValueError("source_config must serialize to an object")
    return copied


def _failed_result(
    *,
    source: str,
    adapter_version: str,
    run_id: str,
    manifest_version: str,
    target_valid_count: int,
    started_at: datetime,
    clock: Callable[[], datetime],
    error_code: str,
) -> CollectionResult:
    return CollectionResult(
        source=source,
        run_id=run_id,
        started_at=started_at,
        finished_at=clock(),
        target_valid_count=target_valid_count,
        status=CollectionStatus.FAILED,
        items=(),
        invalid_items=(),
        request_count=0,
        response_bytes=0,
        retry_count=0,
        rate_limit_events=0,
        failed_item_count=0,
        error_code=error_code,
        error_message=_FALLBACK_MESSAGES[error_code],
        manifest_version=manifest_version,
        adapter_version=adapter_version,
    )


def collect_source(
    adapter: SourceAdapter,
    source_config: Mapping[str, object],
    target_valid_count: int,
    *,
    manifest_version: str,
    run_id: str | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> CollectionResult:
    source = _non_empty_string(getattr(adapter, "source", None), field="adapter.source")
    adapter_version = _non_empty_string(
        getattr(adapter, "adapter_version", None), field="adapter.adapter_version"
    )
    target = _positive_integer(target_valid_count, field="target_valid_count")
    manifest = _non_empty_string(manifest_version, field="manifest_version")
    resolved_run_id = (
        _non_empty_string(run_id, field="run_id")
        if run_id is not None
        else str(uuid4())
    )
    config_copy = _copy_source_config(source_config)
    started_at = clock()

    try:
        result = adapter.collect(
            config_copy,
            target,
            run_id=resolved_run_id,
            manifest_version=manifest,
        )
    except Exception:
        return _failed_result(
            source=source,
            adapter_version=adapter_version,
            run_id=resolved_run_id,
            manifest_version=manifest,
            target_valid_count=target,
            started_at=started_at,
            clock=clock,
            error_code="runner_adapter_exception",
        )

    error_code: str | None = None
    if not isinstance(result, CollectionResult):
        error_code = "runner_invalid_adapter_result"
    elif result.error_code in _FALLBACK_ERROR_CODES:
        error_code = "runner_invalid_adapter_result"
    elif result.source != source:
        error_code = "runner_source_mismatch"
    elif result.adapter_version != adapter_version:
        error_code = "runner_adapter_version_mismatch"
    elif result.run_id != resolved_run_id:
        error_code = "runner_run_id_mismatch"
    elif result.manifest_version != manifest:
        error_code = "runner_manifest_version_mismatch"
    elif result.target_valid_count != target:
        error_code = "runner_target_mismatch"

    if error_code is not None:
        return _failed_result(
            source=source,
            adapter_version=adapter_version,
            run_id=resolved_run_id,
            manifest_version=manifest,
            target_valid_count=target,
            started_at=started_at,
            clock=clock,
            error_code=error_code,
        )
    return result


def operational_metrics_observed(result: CollectionResult) -> bool:
    return result.error_code not in _FALLBACK_ERROR_CODES
