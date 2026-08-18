from __future__ import annotations

import copy
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Mapping

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


_RECEIPT_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas/ted-capacity-receipt.schema.json").read_text()
)
_RECEIPT_VALIDATOR = Draft202012Validator(_RECEIPT_SCHEMA, format_checker=FORMAT_CHECKER)
_EXPECTED_STRATA = (
    "software_and_information_systems",
    "business_services",
    "health_and_social_services",
    "repair_and_maintenance_services",
)
_THRESHOLD_KEYS = (
    "procedure_completeness_min",
    "buyer_completeness_min",
    "text_completeness_min",
    "acceptance_yield_min",
    "processed_max_per_stratum",
)


@dataclass(frozen=True)
class TedNoticeMeasurement:
    processed: int
    notice_id: str | None
    procedure_id: str | None
    buyer_ids: tuple[str, ...]
    publication_date: str | None
    notice_type: str | None
    form_type: str | None
    cpv_codes: tuple[str, ...]
    text_values: tuple[str, ...]
    change_notice_ids: tuple[str, ...]
    procedure_present: bool
    buyer_present: bool
    text_present: bool
    shape_valid: bool
    rejection_reason: str | None


@dataclass(frozen=True)
class TedSelectionDecision:
    accepted: bool
    rejection_reason: str | None


@dataclass(frozen=True)
class TedBudgetDecision:
    allowed: bool
    termination_reason: str | None
    max_http_attempts: int
    deadline_seconds: float
    max_response_bytes: int


class TedRunBudget:
    def __init__(
        self,
        *,
        max_logical_requests: int,
        max_http_attempts: int,
        deadline_seconds: float,
        max_response_bytes: int,
        monotonic: Callable[[], float],
    ) -> None:
        self._max_logical_requests = max_logical_requests
        self._max_http_attempts = max_http_attempts
        self._deadline_seconds = deadline_seconds
        self._max_response_bytes = max_response_bytes
        self._monotonic = monotonic
        self._started = monotonic()
        self.logical_requests = 0
        self.http_attempts = 0
        self.response_bytes = 0

    def begin_request(self, *, max_attempts_per_request: int) -> TedBudgetDecision:
        elapsed = self._monotonic() - self._started
        reason = self._termination_reason(elapsed)
        if reason is not None:
            return TedBudgetDecision(False, reason, 0, 0, 0)
        remaining_attempts = self._max_http_attempts - self.http_attempts
        remaining_deadline = self._deadline_seconds - elapsed
        remaining_bytes = self._max_response_bytes - self.response_bytes
        self.logical_requests += 1
        return TedBudgetDecision(
            True,
            None,
            min(max_attempts_per_request, remaining_attempts),
            remaining_deadline,
            remaining_bytes,
        )

    def record(self, *, http_attempts: int, response_bytes: int) -> str | None:
        if http_attempts < 0 or response_bytes < 0:
            raise ValueError("observed budget values cannot be negative")
        self.http_attempts += http_attempts
        self.response_bytes += response_bytes
        if self.http_attempts > self._max_http_attempts:
            return "attempt_budget_exhausted"
        if self.response_bytes > self._max_response_bytes:
            return "response_byte_budget_exhausted"
        if self._monotonic() - self._started >= self._deadline_seconds:
            return "deadline_exhausted"
        return None

    def _termination_reason(self, elapsed: float) -> str | None:
        if self.logical_requests >= self._max_logical_requests:
            return "request_budget_exhausted"
        if self.http_attempts >= self._max_http_attempts:
            return "attempt_budget_exhausted"
        if elapsed >= self._deadline_seconds:
            return "deadline_exhausted"
        if self.response_bytes >= self._max_response_bytes:
            return "response_byte_budget_exhausted"
        return None


class TedPaginationState:
    def __init__(self) -> None:
        self._signatures: set[str] = set()
        self._last_total_notice_count: int | None = None
        self._last_page_number: int | None = None
        self._pages_observed = 0
        self._repeated_page_signatures = 0
        self._total_count_change_events = 0
        self._source_exhausted = False

    def observe(
        self,
        *,
        page_number: int,
        payload_signature: str,
        total_notice_count: int,
        has_more: bool,
    ) -> str | None:
        self._pages_observed += 1
        if (
            self._last_total_notice_count is not None
            and total_notice_count != self._last_total_notice_count
        ):
            self._total_count_change_events += 1
        self._last_total_notice_count = total_notice_count
        self._source_exhausted = self._source_exhausted or not has_more
        expected_page_number = 1 if self._last_page_number is None else self._last_page_number + 1
        if page_number != expected_page_number:
            return "pagination_repeated"
        self._last_page_number = page_number
        if payload_signature in self._signatures:
            self._repeated_page_signatures += 1
            return "pagination_repeated"
        self._signatures.add(payload_signature)
        return None

    def summary(self) -> dict[str, object]:
        return {
            "pages_observed": self._pages_observed,
            "unique_page_signatures": len(self._signatures),
            "repeated_page_signatures": self._repeated_page_signatures,
            "total_count_change_events": self._total_count_change_events,
            "source_exhausted": self._source_exhausted,
            "mode": "PAGE_NUMBER",
            "interpretation": "single_run_capacity_only",
        }


def build_stratum_summary(
    *,
    fetched: int,
    processed: int,
    accepted: int,
    rejection_reason_counts: Mapping[str, int],
    procedure_present_count: int,
    buyer_present_count: int,
    text_present_count: int,
    required: int,
    thresholds: Mapping[str, float | int],
) -> dict[str, object]:
    values = (
        fetched,
        processed,
        accepted,
        procedure_present_count,
        buyer_present_count,
        text_present_count,
        required,
        *rejection_reason_counts.values(),
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("stratum counts must be nonnegative integers")
    if set(thresholds) != set(_THRESHOLD_KEYS):
        raise ValueError("stratum threshold field set mismatch")
    rejected = sum(rejection_reason_counts.values())
    if processed != accepted + rejected or processed > fetched:
        raise ValueError("stratum count arithmetic mismatch")
    if any(count > processed for count in (procedure_present_count, buyer_present_count, text_present_count)):
        raise ValueError("stratum completeness count exceeds processed count")
    denominator = processed or 1
    procedure_completeness = procedure_present_count / denominator if processed else 0.0
    buyer_completeness = buyer_present_count / denominator if processed else 0.0
    text_completeness = text_present_count / denominator if processed else 0.0
    acceptance_yield = accepted / denominator if processed else 0.0
    capacity_pass = (
        accepted >= required
        and processed <= int(thresholds["processed_max_per_stratum"])
        and procedure_completeness >= float(thresholds["procedure_completeness_min"])
        and buyer_completeness >= float(thresholds["buyer_completeness_min"])
        and text_completeness >= float(thresholds["text_completeness_min"])
        and acceptance_yield >= float(thresholds["acceptance_yield_min"])
    )
    return {
        "fetched": fetched,
        "processed": processed,
        "accepted": accepted,
        "rejected": rejected,
        "rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
        "procedure_completeness": procedure_completeness,
        "buyer_completeness": buyer_completeness,
        "text_completeness": text_completeness,
        "acceptance_yield": acceptance_yield,
        "capacity_pass": capacity_pass,
    }


def build_capacity_receipt(
    *,
    run_id: str,
    run_sequence: int,
    started_at: str,
    finished_at: str,
    elapsed_ms: int,
    capacity_manifest_hash: str,
    feasibility_hash: str,
    compliance_hash: str,
    required_per_stratum: int,
    strata: Mapping[str, object],
    transport: Mapping[str, object],
    pagination: Mapping[str, object],
    failure_reason: str | None,
) -> dict[str, object]:
    copied_strata = copy.deepcopy(dict(strata))
    copied_transport = copy.deepcopy(dict(transport))
    copied_pagination = copy.deepcopy(dict(pagination))
    all_strata_pass = set(copied_strata) == set(_EXPECTED_STRATA) and all(
        isinstance(value, Mapping)
        and value.get("capacity_pass") is True
        and _stratum_capacity_pass(value, required_per_stratum)
        for value in copied_strata.values()
    )
    transport_pass = (
        copied_transport.get("deadline_exhausted") is False
        and _within_budget(copied_transport, "logical_requests", "max_logical_requests")
        and _within_budget(copied_transport, "http_attempts", "max_http_attempts")
        and _within_budget(copied_transport, "response_bytes", "max_response_bytes")
        and _transport_arithmetic_valid(copied_transport)
    )
    pagination_pass = (
        copied_pagination.get("repeated_page_signatures") == 0
        and _pagination_arithmetic_valid(copied_pagination)
    )
    passed = all_strata_pass and transport_pass and pagination_pass and failure_reason is None
    return {
        "schema_version": 1,
        "run_id": run_id,
        "run_sequence": run_sequence,
        "status": "PASS" if passed else "FAIL",
        "termination_reason": "capacity_reached" if passed else failure_reason or "quality_threshold_failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_ms": elapsed_ms,
        "capacity_manifest_hash": capacity_manifest_hash,
        "feasibility_hash": feasibility_hash,
        "compliance_hash": compliance_hash,
        "required_per_stratum": required_per_stratum,
        "retained_items": 0,
        "raw_text_persisted": 0,
        "raw_author_persisted": 0,
        "strata": copied_strata,
        "transport": copied_transport,
        "pagination": copied_pagination,
    }


def _within_budget(values: Mapping[str, object], observed_key: str, limit_key: str) -> bool:
    observed = values.get(observed_key)
    limit = values.get(limit_key)
    return (
        not isinstance(observed, bool)
        and isinstance(observed, int)
        and not isinstance(limit, bool)
        and isinstance(limit, int)
        and observed <= limit
    )


def _is_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and (isinstance(value, int) or math.isfinite(value))
    )


def _transport_arithmetic_valid(values: Mapping[str, object]) -> bool:
    logical_requests = values.get("logical_requests")
    http_attempts = values.get("http_attempts")
    retries = values.get("retries")
    deadline_seconds = values.get("deadline_seconds")
    if not all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (logical_requests, http_attempts, retries)
    ) or (
        not _is_finite_number(deadline_seconds)
        or deadline_seconds <= 0
    ):
        return False
    return retries <= http_attempts <= logical_requests + retries


def _pagination_arithmetic_valid(values: Mapping[str, object]) -> bool:
    pages = values.get("pages_observed")
    unique = values.get("unique_page_signatures")
    repeated = values.get("repeated_page_signatures")
    if not all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (pages, unique, repeated)
    ):
        return False
    return pages == unique + repeated


def _stratum_capacity_pass(value: Mapping[str, object], required: int) -> bool:
    accepted = value.get("accepted")
    processed = value.get("processed")
    ratios = tuple(
        value.get(key)
        for key in (
            "procedure_completeness",
            "buyer_completeness",
            "text_completeness",
            "acceptance_yield",
        )
    )
    if (
        isinstance(accepted, bool)
        or not isinstance(accepted, int)
        or isinstance(processed, bool)
        or not isinstance(processed, int)
        or any(
            not _is_finite_number(ratio)
            for ratio in ratios
        )
    ):
        return False
    procedure, buyer, text, acceptance = ratios
    return (
        accepted >= required
        and processed <= 300
        and procedure >= 0.95
        and buyer >= 0.8
        and text >= 0.8
        and acceptance >= 0.25
    )


def validate_capacity_receipt(
    receipt: Mapping[str, object],
    *,
    capacity_manifest_hash: str,
    feasibility_hash: str,
    compliance_hash: str,
) -> list[str]:
    errors = [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in sorted(
            _RECEIPT_VALIDATOR.iter_errors(receipt),
            key=lambda value: tuple(map(str, value.absolute_path)),
        )
    ]
    for key, expected, label in (
        ("capacity_manifest_hash", capacity_manifest_hash, "capacity manifest hash"),
        ("feasibility_hash", feasibility_hash, "feasibility hash"),
        ("compliance_hash", compliance_hash, "compliance hash"),
    ):
        if receipt.get(key) != expected:
            errors.append(f"{label} mismatch")
    strata = receipt.get("strata")
    required = receipt.get("required_per_stratum")
    failed_stratum = False
    if isinstance(strata, Mapping):
        for name, value in strata.items():
            if not isinstance(value, Mapping):
                continue
            fetched = value.get("fetched")
            processed = value.get("processed")
            accepted = value.get("accepted")
            rejected = value.get("rejected")
            reasons = value.get("rejection_reason_counts")
            ratios = (
                value.get("procedure_completeness"),
                value.get("buyer_completeness"),
                value.get("text_completeness"),
                value.get("acceptance_yield"),
            )
            if any(
                not _is_finite_number(ratio)
                for ratio in ratios
            ):
                errors.append(f"stratum ratio must be finite: {name}")
            if (
                all(isinstance(item, int) and not isinstance(item, bool) for item in (fetched, processed, accepted, rejected))
                and isinstance(reasons, Mapping)
                and all(isinstance(count, int) and not isinstance(count, bool) for count in reasons.values())
                and (
                    processed != accepted + rejected
                    or rejected != sum(reasons.values())
                    or processed > fetched
                )
            ):
                errors.append(f"stratum arithmetic mismatch: {name}")
            if value.get("capacity_pass") is not True:
                failed_stratum = True
            if isinstance(required, int) and not isinstance(required, bool):
                expected_pass = _stratum_capacity_pass(value, required)
                if value.get("capacity_pass") is not expected_pass:
                    errors.append(f"stratum capacity pass mismatch: {name}")
    transport = receipt.get("transport")
    transport_failed = True
    if isinstance(transport, Mapping):
        transport_failed = not (
            transport.get("deadline_exhausted") is False
            and _within_budget(transport, "logical_requests", "max_logical_requests")
            and _within_budget(transport, "http_attempts", "max_http_attempts")
            and _within_budget(transport, "response_bytes", "max_response_bytes")
        )
        if not _transport_arithmetic_valid(transport):
            errors.append("capacity receipt transport arithmetic mismatch")
    pagination = receipt.get("pagination")
    pagination_failed = not isinstance(pagination, Mapping) or pagination.get("repeated_page_signatures") != 0
    if isinstance(pagination, Mapping) and not _pagination_arithmetic_valid(pagination):
        errors.append("capacity receipt pagination arithmetic mismatch")
        pagination_failed = True
    if receipt.get("status") == "PASS":
        if receipt.get("termination_reason") != "capacity_reached":
            errors.append("PASS receipt termination mismatch")
        if failed_stratum:
            errors.append("PASS receipt has a failed stratum")
        if transport_failed:
            errors.append("PASS receipt has transport budget failure")
        if pagination_failed:
            errors.append("PASS receipt has pagination failure")
    elif receipt.get("termination_reason") == "capacity_reached":
        errors.append("FAIL receipt cannot terminate with capacity_reached")
    return errors


class TedSelectionState:
    def __init__(
        self,
        *,
        published_from: str,
        published_before: str,
        allowed_notice_types: frozenset[str],
        form_type: str,
        cpv_prefix: str,
        max_items_per_buyer: int,
    ) -> None:
        self._published_from = _parse_yyyymmdd(published_from)
        self._published_before = _parse_yyyymmdd(published_before)
        if self._published_from is None or self._published_before is None:
            raise ValueError("selection window must use valid YYYYMMDD dates")
        self._allowed_notice_types = allowed_notice_types
        self._form_type = form_type
        self._cpv_prefix = cpv_prefix
        self._max_items_per_buyer = max_items_per_buyer
        self._notice_ids: set[str] = set()
        self._procedure_ids: set[str] = set()
        self._buyer_counts: Counter[str] = Counter()

    def select(self, measurement: TedNoticeMeasurement) -> TedSelectionDecision:
        rejection_reason = self._eligibility_rejection(measurement)
        if rejection_reason is not None:
            return TedSelectionDecision(False, rejection_reason)
        assert measurement.notice_id is not None
        assert measurement.procedure_id is not None
        if measurement.notice_id in self._notice_ids:
            return TedSelectionDecision(False, "duplicate_notice")
        if measurement.procedure_id in self._procedure_ids:
            return TedSelectionDecision(False, "duplicate_procedure")
        buyers = tuple(dict.fromkeys(measurement.buyer_ids))
        if any(self._buyer_counts[buyer] >= self._max_items_per_buyer for buyer in buyers):
            return TedSelectionDecision(False, "buyer_limit_exceeded")
        self._notice_ids.add(measurement.notice_id)
        self._procedure_ids.add(measurement.procedure_id)
        self._buyer_counts.update(buyers)
        return TedSelectionDecision(True, None)

    def _eligibility_rejection(self, measurement: TedNoticeMeasurement) -> str | None:
        if not measurement.shape_valid:
            return "invalid_field_shape"
        if measurement.notice_id is None:
            return "missing_notice_id"
        if measurement.procedure_id is None:
            return "missing_procedure_id"
        if not measurement.buyer_ids:
            return "missing_buyer_id"
        if not measurement.text_values:
            return "missing_text"
        publication_date = _parse_yyyymmdd(measurement.publication_date)
        if publication_date is None or not self._published_from <= publication_date < self._published_before:
            return "outside_window"
        if (
            measurement.form_type != self._form_type
            or measurement.notice_type not in self._allowed_notice_types
        ):
            return "wrong_notice_scope"
        if not any(
            len(code) == 8
            and code.isascii()
            and code.isdecimal()
            and code.startswith(self._cpv_prefix)
            for code in measurement.cpv_codes
        ):
            return "wrong_cpv_stratum"
        if measurement.change_notice_ids:
            return "change_notice"
        return None


def _parse_yyyymmdd(value: str | None) -> date | None:
    if value is None or len(value) != 8 or not value.isascii() or not value.isdecimal():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _clean_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_values(value: object, *, language_map: bool = False) -> tuple[tuple[str, ...], bool]:
    if value is None:
        return (), True
    scalar = _clean_string(value)
    if scalar is not None:
        return (scalar,), True
    if isinstance(value, str):
        return (), True
    if isinstance(value, list):
        if any(not isinstance(item, str) for item in value):
            return (), False
        return tuple(cleaned for item in value if (cleaned := _clean_string(item)) is not None), True
    if language_map and isinstance(value, Mapping):
        normalized: list[str] = []
        for language, language_value in value.items():
            if not isinstance(language, str) or isinstance(language_value, Mapping):
                return (), False
            values, valid = _normalize_values(language_value)
            if not valid:
                return (), False
            normalized.extend(values)
        return tuple(normalized), True
    return (), False


def _first(values: tuple[str, ...]) -> str | None:
    return values[0] if values else None


def _normalize_single(value: object) -> tuple[tuple[str, ...], bool]:
    values, valid = _normalize_values(value)
    cardinality_valid = not isinstance(value, list) or len(value) <= 1
    field_valid = valid and cardinality_valid
    return values if field_valid else (), field_valid


def measure_notice(notice: Mapping[str, object]) -> TedNoticeMeasurement:
    notice_ids, notice_valid = _normalize_single(notice.get("notice-identifier"))
    procedure_ids, procedure_valid = _normalize_single(notice.get("procedure-identifier"))
    buyer_ids, buyer_valid = _normalize_values(notice.get("buyer-identifier"))
    publication_dates, publication_valid = _normalize_single(notice.get("publication-date"))
    notice_types, notice_type_valid = _normalize_single(notice.get("notice-type"))
    form_types, form_type_valid = _normalize_single(notice.get("form-type"))
    cpv_codes, cpv_valid = _normalize_values(notice.get("classification-cpv"))
    title_values, title_valid = _normalize_values(notice.get("notice-title"), language_map=True)
    description_values, description_valid = _normalize_values(
        notice.get("description-proc"), language_map=True
    )
    change_notice_ids, change_valid = _normalize_values(
        notice.get("change-notice-version-identifier")
    )
    shape_valid = all(
        (
            notice_valid,
            procedure_valid,
            buyer_valid,
            publication_valid,
            notice_type_valid,
            form_type_valid,
            cpv_valid,
            title_valid,
            description_valid,
            change_valid,
        )
    )
    text_values = title_values + description_values
    procedure_id = _first(procedure_ids)
    return TedNoticeMeasurement(
        processed=1,
        notice_id=_first(notice_ids),
        procedure_id=procedure_id,
        buyer_ids=buyer_ids,
        publication_date=_first(publication_dates),
        notice_type=_first(notice_types),
        form_type=_first(form_types),
        cpv_codes=cpv_codes,
        text_values=text_values,
        change_notice_ids=change_notice_ids,
        procedure_present=procedure_id is not None,
        buyer_present=bool(buyer_ids),
        text_present=bool(text_values),
        shape_valid=shape_valid,
        rejection_reason=None if shape_valid else "invalid_field_shape",
    )
