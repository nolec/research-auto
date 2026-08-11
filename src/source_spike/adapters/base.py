from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence, cast

from src.source_spike.raw_items import validate_raw_source_item


_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class CollectionStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _validate_error_code(value: str, *, field: str = "error_code") -> None:
    if not isinstance(value, str) or not _ERROR_CODE.fullmatch(value):
        raise ValueError(f"{field} must be lower snake case and at most 64 characters")


def _validate_non_empty_string(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")


@dataclass(frozen=True)
class InvalidItem:
    source_item_id: str | None
    error_code: str
    errors: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.source_item_id is not None:
            _validate_non_empty_string(self.source_item_id, field="source_item_id")
        _validate_error_code(self.error_code)
        normalized_errors = tuple(self.errors)
        if not 1 <= len(normalized_errors) <= 20:
            raise ValueError("errors must contain between 1 and 20 entries")
        if any(
            not isinstance(error, str) or not error or len(error) > 500
            for error in normalized_errors
        ):
            raise ValueError("each error must contain between 1 and 500 characters")
        object.__setattr__(self, "errors", normalized_errors)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_item_id": self.source_item_id,
            "error_code": self.error_code,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class CollectionResult:
    source: str
    run_id: str
    started_at: datetime
    finished_at: datetime
    target_valid_count: int
    status: CollectionStatus
    items: Sequence[Mapping[str, object]]
    invalid_items: Sequence[InvalidItem]
    request_count: int
    response_bytes: int
    retry_count: int
    rate_limit_events: int
    failed_item_count: int
    error_code: str | None
    error_message: str | None
    manifest_version: str
    adapter_version: str

    def __post_init__(self) -> None:
        for field, value in (
            ("source", self.source),
            ("run_id", self.run_id),
            ("manifest_version", self.manifest_version),
            ("adapter_version", self.adapter_version),
        ):
            _validate_non_empty_string(value, field=field)
        if (
            self.started_at.tzinfo is None
            or self.started_at.utcoffset() is None
            or self.finished_at.tzinfo is None
            or self.finished_at.utcoffset() is None
        ):
            raise ValueError("started_at and finished_at must be timezone-aware")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be earlier than started_at")
        if (
            isinstance(self.target_valid_count, bool)
            or not isinstance(self.target_valid_count, int)
            or self.target_valid_count < 1
        ):
            raise ValueError("target_valid_count must be a positive integer")

        metric_values = (
            ("request_count", self.request_count),
            ("response_bytes", self.response_bytes),
            ("retry_count", self.retry_count),
            ("rate_limit_events", self.rate_limit_events),
            ("failed_item_count", self.failed_item_count),
        )
        for field, value in metric_values:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.retry_count > max(self.request_count - 1, 0):
            raise ValueError("retry_count cannot exceed request_count minus one")

        normalized_status = CollectionStatus(self.status)
        item_payloads: list[Mapping[str, object]] = []
        for index, item in enumerate(self.items):
            if not isinstance(item, Mapping):
                raise ValueError("items must contain mappings")
            payload = cast(Mapping[str, object], _thaw(item))
            if payload.get("source") != self.source:
                raise ValueError(f"item source does not match result source at index {index}")
            errors = validate_raw_source_item(payload)
            if errors:
                raise ValueError(
                    f"invalid raw source item at index {index}: {'; '.join(errors)}"
                )
            if payload["fetch_run_id"] != self.run_id:
                raise ValueError(f"item fetch_run_id does not match run_id at index {index}")
            if payload["collector_version"] != self.adapter_version:
                raise ValueError(
                    f"item collector_version does not match adapter_version at index {index}"
                )
            item_payloads.append(payload)

        normalized_invalid_items = tuple(self.invalid_items)
        if any(not isinstance(item, InvalidItem) for item in normalized_invalid_items):
            raise ValueError("invalid_items must contain InvalidItem values")
        if self.failed_item_count != len(normalized_invalid_items):
            raise ValueError("failed_item_count must equal len(invalid_items)")

        item_count = len(item_payloads)
        expected_status = (
            CollectionStatus.SUCCESS
            if item_count >= self.target_valid_count
            else CollectionStatus.PARTIAL
            if item_count > 0
            else CollectionStatus.FAILED
        )
        if normalized_status is not expected_status:
            raise ValueError(f"status must be {expected_status.value} for {item_count} items")
        if expected_status is CollectionStatus.SUCCESS:
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("success results cannot contain errors")
        else:
            if self.error_code is None:
                raise ValueError("partial and failed results require error_code")
            _validate_error_code(self.error_code)
            if self.error_message is not None and (
                not isinstance(self.error_message, str)
                or not 1 <= len(self.error_message) <= 500
            ):
                raise ValueError("error_message must contain between 1 and 500 characters")

        object.__setattr__(self, "status", normalized_status)
        object.__setattr__(self, "items", tuple(_freeze(item) for item in item_payloads))
        object.__setattr__(self, "invalid_items", normalized_invalid_items)

    def replace(self, **changes: object) -> CollectionResult:
        return replace(self, **changes)

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "run_id": self.run_id,
            "started_at": _format_datetime(self.started_at),
            "finished_at": _format_datetime(self.finished_at),
            "target_valid_count": self.target_valid_count,
            "status": self.status.value,
            "items": [_thaw(item) for item in self.items],
            "invalid_items": [item.to_dict() for item in self.invalid_items],
            "request_count": self.request_count,
            "response_bytes": self.response_bytes,
            "retry_count": self.retry_count,
            "rate_limit_events": self.rate_limit_events,
            "failed_item_count": self.failed_item_count,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "manifest_version": self.manifest_version,
            "adapter_version": self.adapter_version,
        }


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class SourceAdapter(Protocol):
    source: str
    adapter_version: str

    def collect(
        self,
        source_config: Mapping[str, object],
        target_valid_count: int,
        *,
        run_id: str,
        manifest_version: str,
    ) -> CollectionResult: ...
