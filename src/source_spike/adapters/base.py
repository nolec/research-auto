from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence, cast

from src.source_spike.raw_items import validate_raw_source_item


_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_TRANSPORT_EVENT_KEYS = frozenset(
    {"sequence", "category", "attempt", "status_code", "retryable", "rate_limit"}
)
_RATE_LIMIT_KEYS = frozenset(
    {"limit", "remaining", "reset_at", "resource", "retry_after_seconds"}
)
_TRANSPORT_CATEGORIES = frozenset(
    {"http_error", "timeout", "connection_reset", "rate_limit"}
)
_RATE_LIMIT_RESOURCES = frozenset(
    {"core", "search", "graphql", "integration_manifest", "source_import", "code_scanning", "actions_runner_registration", "scim", "unknown"}
)


class CollectionStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class TerminationReason(StrEnum):
    TARGET_REACHED = "target_reached"
    REQUEST_BUDGET_EXHAUSTED = "request_budget_exhausted"
    PAGE_BUDGET_EXHAUSTED = "page_budget_exhausted"
    REPOSITORY_QUOTA_UNREACHABLE = "repository_quota_unreachable"
    SOURCE_EXHAUSTED = "source_exhausted"
    PREREQUISITE_FAILED = "prerequisite_failed"
    TRANSPORT_ERROR = "transport_error"
    RATE_LIMIT_EXHAUSTED = "rate_limit_exhausted"
    SMOKE_DEADLINE_EXHAUSTED = "smoke_deadline_exhausted"


@dataclass(frozen=True)
class SegmentResult:
    segment_type: str
    segment_id: str
    quota: int
    accepted_item_count: int

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.segment_type, field="segment_type")
        _validate_non_empty_string(self.segment_id, field="segment_id")
        for field, value in (
            ("quota", self.quota),
            ("accepted_item_count", self.accepted_item_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.accepted_item_count > self.quota:
            raise ValueError("accepted_item_count cannot exceed segment quota")

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_type": self.segment_type,
            "segment_id": self.segment_id,
            "quota": self.quota,
            "accepted_item_count": self.accepted_item_count,
        }


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
    successful_request_count: int
    http_attempt_count: int
    transport_events: Sequence[Mapping[str, object]]
    error_code: str | None
    error_message: str | None
    manifest_version: str
    adapter_version: str
    termination_reason: TerminationReason
    fetched_item_count: int
    processed_item_count: int
    accepted_item_count: int
    rejected_item_count: int
    segment_results: Sequence[SegmentResult]
    manifest_hash: str
    compliance_hash: str | None

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
            ("successful_request_count", self.successful_request_count),
            ("http_attempt_count", self.http_attempt_count),
            ("fetched_item_count", self.fetched_item_count),
            ("processed_item_count", self.processed_item_count),
            ("accepted_item_count", self.accepted_item_count),
            ("rejected_item_count", self.rejected_item_count),
        )
        for field, value in metric_values:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.successful_request_count > self.request_count:
            raise ValueError("successful_request_count cannot exceed request_count")
        if self.request_count > self.http_attempt_count:
            raise ValueError("request_count cannot exceed http_attempt_count")
        if self.retry_count != self.http_attempt_count - self.request_count:
            raise ValueError("retry_count must equal http_attempt_count minus request_count")
        normalized_transport_events = tuple(self.transport_events)
        if len(normalized_transport_events) > self.http_attempt_count:
            raise ValueError("transport_events cannot exceed http_attempt_count")
        if any(not isinstance(event, Mapping) for event in normalized_transport_events):
            raise ValueError("transport_events must contain mappings")
        for event in normalized_transport_events:
            if set(event) != _TRANSPORT_EVENT_KEYS:
                raise ValueError("transport_events must use the safe event allowlist")
            for key in ("sequence", "attempt"):
                value = event[key]
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError(f"transport event {key} must be a positive integer")
            status_code = event["status_code"]
            if status_code is not None and (
                isinstance(status_code, bool)
                or not isinstance(status_code, int)
                or not 100 <= status_code <= 599
            ):
                raise ValueError(
                    "transport event status_code must be null or an HTTP status integer"
                )
            if not isinstance(event["retryable"], bool):
                raise ValueError("transport event retryable must be a boolean")
            rate_limit = event.get("rate_limit")
            if event.get("category") not in _TRANSPORT_CATEGORIES:
                raise ValueError("transport event category is not allowlisted")
            if rate_limit is not None:
                if not isinstance(rate_limit, Mapping) or set(rate_limit) != _RATE_LIMIT_KEYS:
                    raise ValueError("rate_limit must use the safe nested allowlist")
                for key in ("limit", "remaining", "reset_at", "retry_after_seconds"):
                    value = rate_limit[key]
                    if value is not None and (
                        isinstance(value, bool) or not isinstance(value, int) or value < 0
                    ):
                        raise ValueError(f"rate_limit.{key} must be null or a non-negative integer")
                resource = rate_limit["resource"]
                if resource is not None and (
                    not isinstance(resource, str) or resource not in _RATE_LIMIT_RESOURCES
                ):
                    raise ValueError("rate_limit.resource is not allowlisted")

        normalized_status = CollectionStatus(self.status)
        normalized_termination = TerminationReason(self.termination_reason)
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
        item_count = len(item_payloads)
        if self.accepted_item_count != item_count:
            raise ValueError("accepted_item_count must equal len(items)")
        if self.rejected_item_count != len(normalized_invalid_items):
            raise ValueError("rejected_item_count must equal len(invalid_items)")
        if self.processed_item_count != self.accepted_item_count + self.rejected_item_count:
            raise ValueError("processed_item_count must equal accepted plus rejected counts")
        if self.processed_item_count > self.fetched_item_count:
            raise ValueError("processed_item_count cannot exceed fetched_item_count")
        if self.accepted_item_count > self.target_valid_count:
            raise ValueError("accepted_item_count cannot exceed target_valid_count")

        normalized_segments = tuple(self.segment_results)
        if not normalized_segments or any(
            not isinstance(segment, SegmentResult) for segment in normalized_segments
        ):
            raise ValueError("segment_results must contain SegmentResult values")
        segment_keys = [
            (segment.segment_type, segment.segment_id) for segment in normalized_segments
        ]
        if len(segment_keys) != len(set(segment_keys)):
            raise ValueError("segment_results must be unique")
        if sum(segment.accepted_item_count for segment in normalized_segments) != item_count:
            raise ValueError("segment accepted counts must equal accepted_item_count")

        if not isinstance(self.manifest_hash, str) or not _SHA256.fullmatch(
            self.manifest_hash
        ):
            raise ValueError("manifest_hash must be a lowercase SHA-256 hex digest")
        if self.compliance_hash is not None and (
            not isinstance(self.compliance_hash, str)
            or not _SHA256.fullmatch(self.compliance_hash)
        ):
            raise ValueError(
                "compliance_hash must be null or a lowercase SHA-256 hex digest"
            )

        quotas_met = all(
            segment.accepted_item_count == segment.quota
            for segment in normalized_segments
        )
        target_met = item_count == self.target_valid_count
        if (
            normalized_termination is TerminationReason.PREREQUISITE_FAILED
            and item_count
        ):
            raise ValueError("prerequisite_failed results cannot retain accepted items")
        expected_status = (
            CollectionStatus.SUCCESS
            if target_met
            and quotas_met
            and normalized_termination is TerminationReason.TARGET_REACHED
            else CollectionStatus.PARTIAL
            if item_count > 0
            and normalized_termination is not TerminationReason.PREREQUISITE_FAILED
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
        object.__setattr__(self, "termination_reason", normalized_termination)
        object.__setattr__(self, "items", tuple(_freeze(item) for item in item_payloads))
        object.__setattr__(self, "invalid_items", normalized_invalid_items)
        object.__setattr__(self, "segment_results", normalized_segments)
        object.__setattr__(
            self, "transport_events", tuple(_freeze(event) for event in normalized_transport_events)
        )

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
            "successful_request_count": self.successful_request_count,
            "http_attempt_count": self.http_attempt_count,
            "transport_events": [_thaw(event) for event in self.transport_events],
            "failed_item_count": self.rejected_item_count,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "manifest_version": self.manifest_version,
            "adapter_version": self.adapter_version,
            "termination_reason": self.termination_reason.value,
            "fetched_item_count": self.fetched_item_count,
            "processed_item_count": self.processed_item_count,
            "accepted_item_count": self.accepted_item_count,
            "rejected_item_count": self.rejected_item_count,
            "segment_results": [segment.to_dict() for segment in self.segment_results],
            "manifest_hash": self.manifest_hash,
            "compliance_hash": self.compliance_hash,
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
