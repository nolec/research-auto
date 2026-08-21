from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence, cast
from uuid import uuid4

from src.source_spike.adapters.ted_http import (
    HttpTedTransport,
    TedTransportFailure,
    TedTransportSuccess,
)
from src.source_spike.protocol import content_sha256
from src.source_spike.ted_capacity import (
    TedPaginationState,
    TedRunBudget,
    TedIdentityState,
    TedSelectionState,
    build_capacity_receipt,
    build_stratum_summary,
    measure_notice,
    validate_capacity_receipt,
    validate_query_validation_preflight,
)
from src.source_spike.ted_capacity_manifest import validate_ted_capacity_manifest
from src.source_spike.ted_query_validation import build_query_set


_ROOT = Path(__file__).resolve().parents[2]
_BUDGET_REASONS = frozenset(
    {
        "request_budget_exhausted",
        "attempt_budget_exhausted",
        "deadline_exhausted",
        "response_byte_budget_exhausted",
    }
)


class TedCapacityTransport(Protocol):
    def fetch_notices(self, **kwargs: object) -> TedTransportSuccess | TedTransportFailure: ...


@dataclass(frozen=True)
class TedCapacityExecution:
    exit_code: int
    run_id: str
    status: str
    receipt_path: Path | None
    error_code: str | None


@dataclass
class _StratumCounts:
    fetched: int = 0
    processed: int = 0
    accepted: int = 0
    procedure_present: int = 0
    buyer_present: int = 0
    text_present: int = 0
    rejection_reasons: Counter[str] | None = None

    def __post_init__(self) -> None:
        if self.rejection_reasons is None:
            self.rejection_reasons = Counter()


def _zero_summary(required: int, thresholds: Mapping[str, float | int]) -> dict[str, object]:
    return build_stratum_summary(
        fetched=0,
        processed=0,
        accepted=0,
        rejection_reason_counts={},
        procedure_present_count=0,
        buyer_present_count=0,
        text_present_count=0,
        required=required,
        thresholds=thresholds,
    )


def _summary(
    counts: _StratumCounts,
    *,
    required: int,
    thresholds: Mapping[str, float | int],
) -> dict[str, object]:
    return build_stratum_summary(
        fetched=counts.fetched,
        processed=counts.processed,
        accepted=counts.accepted,
        rejection_reason_counts=counts.rejection_reasons or {},
        procedure_present_count=counts.procedure_present,
        buyer_present_count=counts.buyer_present,
        text_present_count=counts.text_present,
        required=required,
        thresholds=thresholds,
    )


def _aggregate_pagination(states: Sequence[TedPaginationState]) -> dict[str, object]:
    summaries = [state.summary() for state in states]
    return {
        "pages_observed": sum(int(value["pages_observed"]) for value in summaries),
        "unique_page_signatures": sum(
            int(value["unique_page_signatures"]) for value in summaries
        ),
        "repeated_page_signatures": sum(
            int(value["repeated_page_signatures"]) for value in summaries
        ),
        "total_count_change_events": sum(
            int(value["total_count_change_events"]) for value in summaries
        ),
        "source_exhausted": any(bool(value["source_exhausted"]) for value in summaries),
        "mode": "PAGE_NUMBER",
        "interpretation": "single_run_capacity_only",
    }


def _event_count(events: Sequence[Mapping[str, object]], category: str) -> int:
    return sum(value.get("category") == category for value in events)


def _output_root_ready(output_root: Path) -> bool:
    if output_root.is_symlink() or (output_root.exists() and not output_root.is_dir()):
        return False
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return output_root.is_dir() and not output_root.is_symlink()


def _atomic_json_write(path: Path, value: Mapping[str, object], *, run_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{run_id}.tmp")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def execute_capacity_probe(
    manifest: Mapping[str, object],
    query_validation_receipt: Mapping[str, object],
    transport: TedCapacityTransport,
    *,
    output_root: Path,
    capacity_manifest_hash: str,
    feasibility_hash: str,
    compliance_hash: str,
    run_id: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    elapsed_ms: int | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> TedCapacityExecution:
    execution_started = monotonic()
    actual_started_at = started_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        query_set = build_query_set(manifest)
    except (KeyError, TypeError, ValueError):
        return TedCapacityExecution(3, run_id, "FAIL", None, "prerequisite_failed")
    preflight_errors = validate_query_validation_preflight(
        query_validation_receipt,
        capacity_manifest_hash=capacity_manifest_hash,
        feasibility_hash=feasibility_hash,
        compliance_hash=compliance_hash,
        query_set_sha256=query_set.query_set_sha256,
    )
    receipt_strata = query_validation_receipt.get("strata")
    expected_identity = tuple(
        (candidate.stratum, candidate.query_sha256) for candidate in query_set.candidates
    )
    actual_identity = tuple(
        (value.get("stratum"), value.get("query_sha256"))
        for value in receipt_strata
        if isinstance(value, Mapping)
    ) if isinstance(receipt_strata, list) else ()
    if preflight_errors or actual_identity != expected_identity or not _output_root_ready(output_root):
        return TedCapacityExecution(3, run_id, "FAIL", None, "prerequisite_failed")

    pagination_config = cast(Mapping[str, object], manifest["pagination"])
    retry_config = cast(Mapping[str, object], manifest["retry"])
    allocation = cast(Mapping[str, object], manifest["allocation"])
    window = cast(Mapping[str, object], manifest["window"])
    scope = cast(Mapping[str, object], manifest["notice_scope"])
    selection = cast(Mapping[str, object], manifest["selection"])
    api = cast(Mapping[str, object], manifest["api"])
    thresholds = cast(Mapping[str, float | int], manifest["thresholds"])
    manifest_strata = cast(Sequence[Mapping[str, object]], manifest["strata"])
    required = int(allocation["required_unique_per_stratum"])
    summaries = {
        candidate.stratum: _zero_summary(required, thresholds)
        for candidate in query_set.candidates
    }
    pagination_states = {candidate.stratum: TedPaginationState() for candidate in query_set.candidates}
    budget = TedRunBudget(
        max_logical_requests=int(pagination_config["max_logical_requests_total"]),
        max_http_attempts=int(pagination_config["max_http_attempts_total"]),
        deadline_seconds=float(pagination_config["deadline_seconds"]),
        max_response_bytes=int(pagination_config["max_response_bytes_total"]),
        monotonic=monotonic,
    )
    retries = rate_limit_events = transport_errors = 0
    failure_reason: str | None = None
    any_source_exhausted = False
    identity_state = TedIdentityState(
        max_items_per_buyer=int(selection["max_items_per_buyer"])
    )

    for candidate, stratum in zip(query_set.candidates, manifest_strata, strict=True):
        counts = _StratumCounts()
        state = TedSelectionState(
            published_from=str(window["query_from_date"]),
            published_before=datetime.fromisoformat(
                str(window["published_before"]).replace("Z", "+00:00")
            ).strftime("%Y%m%d"),
            allowed_notice_types=frozenset(cast(Sequence[str], scope["allowed_notice_types"])),
            form_type=str(scope["form_type"]),
            cpv_prefix=str(stratum["cpv_prefix"]),
            max_items_per_buyer=int(selection["max_items_per_buyer"]),
            identity_state=identity_state,
        )
        pagination = pagination_states[candidate.stratum]
        max_pages = int(pagination_config["max_logical_requests_per_stratum"])
        for page_number in range(1, max_pages + 1):
            if counts.accepted >= required:
                break
            allowance = budget.begin_request(
                max_attempts_per_request=int(pagination_config["max_attempts_per_logical_request"])
            )
            if not allowance.allowed:
                failure_reason = allowance.termination_reason
                break
            response = transport.fetch_notices(
                query=candidate.query,
                fields=cast(Sequence[str], manifest["fields"]),
                page=page_number,
                page_size=int(pagination_config["page_size"]),
                scope=str(api["scope"]),
                check_query_syntax=bool(api["check_query_syntax"]),
                pagination_mode=str(api["pagination_mode"]),
                max_http_attempts=allowance.max_http_attempts,
                request_timeout_seconds=float(pagination_config["request_timeout_seconds"]),
                deadline_seconds=allowance.deadline_seconds,
                max_response_bytes=allowance.max_response_bytes,
                max_retries=min(
                    int(retry_config["max_retries_per_logical_request"]),
                    max(0, allowance.max_http_attempts - 1),
                ),
                base_backoff_seconds=float(retry_config["base_backoff_seconds"]),
                max_backoff_seconds=float(retry_config["max_backoff_seconds"]),
                reject_unknown_wrapper_fields=True,
                allow_nullable_total=False,
            )
            retries += response.retry_count
            rate_limit_events += _event_count(response.events, "rate_limit")
            response_transport_errors = _event_count(response.events, "transport_error")
            transport_errors += response_transport_errors
            budget_reason = budget.record(
                http_attempts=response.http_attempt_count,
                response_bytes=response.response_bytes,
            )
            if budget_reason is not None:
                failure_reason = budget_reason
                break
            if isinstance(response, TedTransportFailure):
                failure_reason = (
                    response.error_code if response.error_code in _BUDGET_REASONS else "transport_failed"
                )
                if response_transport_errors == 0:
                    transport_errors += 1
                break
            counts.fetched += len(response.page.notices)
            pagination_reason = pagination.observe(
                page_number=response.page.page_number,
                payload_signature=response.page.payload_signature,
                total_notice_count=response.page.total_notice_count,
                has_more=response.page.has_more,
            )
            if pagination_reason is not None:
                failure_reason = "pagination_repeated"
                break
            for notice in response.page.notices:
                if counts.accepted >= required:
                    break
                measurement = measure_notice(notice)
                counts.processed += 1
                counts.procedure_present += measurement.procedure_present
                counts.buyer_present += measurement.buyer_present
                counts.text_present += measurement.text_present
                decision = state.select(measurement)
                if decision.accepted:
                    counts.accepted += 1
                else:
                    assert decision.rejection_reason is not None
                    assert counts.rejection_reasons is not None
                    counts.rejection_reasons[decision.rejection_reason] += 1
            if not response.page.has_more:
                any_source_exhausted = any_source_exhausted or counts.accepted < required
                break
        summaries[candidate.stratum] = _summary(counts, required=required, thresholds=thresholds)
        if failure_reason is not None:
            break

    if failure_reason is None:
        if any_source_exhausted and any(
            int(value["accepted"]) < required for value in summaries.values()
        ):
            failure_reason = "source_exhausted"
        elif any(int(value["accepted"]) < required for value in summaries.values()):
            failure_reason = "quota_unmet"
        elif any(value["capacity_pass"] is not True for value in summaries.values()):
            failure_reason = "quality_threshold_failed"

    actual_finished_at = finished_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    actual_elapsed_ms = elapsed_ms if elapsed_ms is not None else max(
        0, int((monotonic() - execution_started) * 1000)
    )
    transport_summary = {
        "logical_requests": budget.logical_requests,
        "http_attempts": budget.http_attempts,
        "retries": retries,
        "rate_limit_events": rate_limit_events,
        "transport_errors": transport_errors,
        "response_bytes": budget.response_bytes,
        "max_logical_requests": int(pagination_config["max_logical_requests_total"]),
        "max_http_attempts": int(pagination_config["max_http_attempts_total"]),
        "deadline_seconds": float(pagination_config["deadline_seconds"]),
        "max_response_bytes": int(pagination_config["max_response_bytes_total"]),
        "deadline_exhausted": failure_reason == "deadline_exhausted",
    }
    receipt = build_capacity_receipt(
        run_id=run_id,
        run_sequence=1,
        started_at=actual_started_at,
        finished_at=actual_finished_at,
        elapsed_ms=actual_elapsed_ms,
        capacity_manifest_hash=capacity_manifest_hash,
        feasibility_hash=feasibility_hash,
        compliance_hash=compliance_hash,
        required_per_stratum=required,
        strata=summaries,
        transport=transport_summary,
        pagination=_aggregate_pagination(tuple(pagination_states.values())),
        failure_reason=failure_reason,
    )
    errors = validate_capacity_receipt(
        receipt,
        capacity_manifest_hash=capacity_manifest_hash,
        feasibility_hash=feasibility_hash,
        compliance_hash=compliance_hash,
    )
    if errors:
        return TedCapacityExecution(3, run_id, "FAIL", None, "receipt_validation_failed")
    receipt_path = output_root / "runs" / run_id / "receipt.json"
    try:
        _atomic_json_write(receipt_path, receipt, run_id=run_id)
        _atomic_json_write(output_root / "latest.json", receipt, run_id=run_id)
    except OSError:
        return TedCapacityExecution(4, run_id, str(receipt["status"]), None, "receipt_persistence_failed")
    status = str(receipt["status"])
    return TedCapacityExecution(
        0 if status == "PASS" else 2,
        run_id,
        status,
        receipt_path,
        None if status == "PASS" else str(receipt["termination_reason"]),
    )


def main(
    argv: list[str] | None = None,
    *,
    transport_factory: Callable[[], TedCapacityTransport] = HttpTedTransport,
) -> int:
    parser = argparse.ArgumentParser(description="Run bounded aggregate-only TED capacity probe")
    parser.add_argument("--manifest", type=Path, default=_ROOT / "config/source-spike/ted-capacity.json")
    parser.add_argument("--feasibility", type=Path, default=_ROOT / "config/source-spike/feasibility/ted.json")
    parser.add_argument(
        "--query-validation-receipt",
        type=Path,
        default=_ROOT / "artifacts/source-spike/ted-query-validation/latest.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_ROOT / "artifacts/source-spike/ted-capacity",
    )
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        feasibility = json.loads(args.feasibility.read_text(encoding="utf-8"))
        query_receipt = json.loads(args.query_validation_receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"status": "FAIL", "error_code": "prerequisite_failed"}))
        return 3
    if (
        not isinstance(manifest, Mapping)
        or not isinstance(feasibility, Mapping)
        or not isinstance(query_receipt, Mapping)
        or validate_ted_capacity_manifest(manifest, feasibility)
    ):
        print(json.dumps({"status": "FAIL", "error_code": "prerequisite_failed"}))
        return 3
    execution = execute_capacity_probe(
        manifest,
        query_receipt,
        transport_factory(),
        output_root=args.output_root,
        capacity_manifest_hash=content_sha256(manifest),
        feasibility_hash=content_sha256(feasibility),
        compliance_hash=str(feasibility["decision_basis_sha256"]),
        run_id=str(uuid4()),
    )
    print(
        json.dumps(
            {
                "status": execution.status,
                "run_id": execution.run_id,
                "error_code": execution.error_code,
            },
            sort_keys=True,
        )
    )
    return execution.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
