from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import time
from typing import Mapping, Protocol, Sequence, cast

from src.source_spike.adapters.base import CollectionResult, CollectionStatus, InvalidItem, SegmentResult, TerminationReason
from src.source_spike.adapters.ted_http import TedTransportFailure, TedTransportSuccess
from src.source_spike.protocol import content_sha256
from src.source_spike.raw_items import author_hash, canonical_text_fingerprint, normalize_text, validate_raw_source_item
from src.source_spike.ted_capacity import TedIdentityState, TedRunBudget, TedSelectionState, measure_notice
from src.source_spike.ted_contact_redaction import LANGUAGE_VERSION, POLICY_VERSION, redact_contacts, residual_contact_count, select_language
from src.source_spike.ted_query_validation import build_query_set


@dataclass(frozen=True)
class ParsedTedNotice:
    item: Mapping[str, object] | None
    rejection: InvalidItem | None


def _strings(value: object) -> list[str]:
    if isinstance(value, str): return [value]
    if isinstance(value, Mapping): return [x for x in value.values() if isinstance(x, str)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: list[str] = []
        for part in value: result.extend(_strings(part))
        return result
    return []


def parse_ted_notice(payload: Mapping[str, object], *, stratum: str, author_secret: bytes, run_id: str, adapter_version: str, collected_at: datetime) -> ParsedTedNotice:
    publication = payload.get("publication-number")
    notice_id = payload.get("notice-identifier")
    procedure = payload.get("procedure-identifier")
    if not all(isinstance(x, str) and x.strip() for x in (publication, notice_id, procedure)):
        return ParsedTedNotice(None, InvalidItem(None, "missing_item_id", ("publication, notice and procedure identifiers are required",)))
    buyers = sorted({value.strip() for value in _strings(payload.get("buyer-identifier")) if value.strip()}, key=lambda x: x.encode("utf-8"))
    if not buyers: return ParsedTedNotice(None, InvalidItem(str(notice_id), "missing_buyer_id", ("buyer identifier is required",)))
    title_source = select_language(payload.get("notice-title"))
    description_source = select_language(payload.get("description-proc"))
    title_redaction = redact_contacts(title_source)
    description_redaction = redact_contacts(description_source)
    title = normalize_text(title_redaction.text) or None
    text = normalize_text(" ".join(value for value in (title_redaction.text, description_redaction.text) if value))
    redacted_contact_count = title_redaction.count + description_redaction.count
    if residual_contact_count(text):
        return ParsedTedNotice(None, InvalidItem(str(notice_id), "residual_contact", ("contact candidate remains after redaction",)))
    if len(text) < 40: return ParsedTedNotice(None, InvalidItem(str(notice_id), "short_text", ("normalized notice text is shorter than 40 characters",)))
    date_value = payload.get("publication-date")
    try:
        raw_date = str(date_value)
        if re.fullmatch(r"\d{8}", raw_date):
            parsed_date = datetime.strptime(raw_date, "%Y%m%d").replace(tzinfo=timezone.utc)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[+-]\d{2}:\d{2})?", raw_date):
            parsed_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            parsed_date = datetime.fromisoformat(raw_date)
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=timezone.utc)
        published = parsed_date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return ParsedTedNotice(None, InvalidItem(str(notice_id), "invalid_timestamp", ("publication-date is invalid",)))
    material = "ted-buyers-v1\0" + "\0".join(buyers)
    stored = text[:20000]
    item: dict[str, object] = {
        "document_id": f"ted:{notice_id}", "source": "ted", "source_item_id": notice_id,
        "source_url": f"https://ted.europa.eu/en/notice/-/detail/{publication}", "item_type": "notice",
        "author_hash": author_hash("ted", material, author_secret), "community": stratum,
        "thread_id": procedure, "parent_id": None, "title": title, "text": stored,
        "text_fingerprint": canonical_text_fingerprint(stored), "text_length": len(stored),
        "original_text_length": len(text), "text_truncated": len(text) > len(stored),
        "published_at": published, "updated_at": None, "language": None, "engagement": {},
        "source_metadata": {"redacted_contact_count": redacted_contact_count, "redaction_policy_version": POLICY_VERSION, "language_selection_version": LANGUAGE_VERSION}, "collected_at": collected_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "collector_version": adapter_version, "fetch_run_id": run_id,
    }
    errors = validate_raw_source_item(item)
    return ParsedTedNotice(None, InvalidItem(str(notice_id), "invalid_item", tuple(errors))) if errors else ParsedTedNotice(item, None)


class TedTransport(Protocol):
    def fetch_notices(self, **kwargs: object) -> TedTransportSuccess | TedTransportFailure: ...


class TedNoticeAdapter:
    source = "ted"
    adapter_version = "0.2.0"

    def __init__(self, transport: TedTransport, *, capacity_manifest: Mapping[str, object], author_secret: bytes, manifest_validator, clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic) -> None:
        self._transport = transport
        self._capacity = dict(capacity_manifest)
        self._secret = author_secret
        self._validate = manifest_validator
        self._clock = clock
        self._monotonic = monotonic

    def collect(self, source_config: Mapping[str, object], target_valid_count: int, *, run_id: str, manifest_version: str) -> CollectionResult:
        started = self._clock()
        manifest_hash = content_sha256(source_config)
        compliance_hash = str(source_config.get("compliance_hash", "")) or None
        strata = cast(Sequence[Mapping[str, object]], source_config.get("strata", []))
        errors = self._validate(source_config, self._capacity)
        if len(self._secret) < 32 or target_valid_count != 100 or manifest_version != source_config.get("manifest_version") or source_config.get("adapter_version") != self.adapter_version:
            errors.append("adapter prerequisites mismatch")
        if errors:
            segments = tuple(SegmentResult("cpv_stratum", str(value.get("name")), int(value.get("quota", 0)), 0, 0, 0, 0) for value in strata)
            return self._result(run_id, manifest_version, target_valid_count, started, (), (), segments, TerminationReason.PREREQUISITE_FAILED, manifest_hash, compliance_hash, error_message="; ".join(errors))

        query_set = build_query_set(self._capacity)
        request = cast(Mapping[str, object], source_config["request"])
        retry = cast(Mapping[str, object], source_config["retry"])
        api = cast(Mapping[str, object], self._capacity["api"])
        scope = cast(Mapping[str, object], self._capacity["notice_scope"])
        window = cast(Mapping[str, object], source_config["window"])
        budget = TedRunBudget(max_logical_requests=int(request["max_logical_requests"]), max_http_attempts=int(request["max_http_attempts"]), deadline_seconds=float(request["deadline_seconds"]), max_response_bytes=int(request["max_response_bytes"]), monotonic=self._monotonic)
        identity = TedIdentityState(max_items_per_buyer=int(source_config["max_items_per_buyer"]))
        accepted: list[Mapping[str, object]] = []
        invalid: list[InvalidItem] = []
        counts = {str(value["name"]): 0 for value in strata}
        fetched_by = {key: 0 for key in counts}; processed_by = {key: 0 for key in counts}; rejected_by = {key: 0 for key in counts}
        successful = retries = rate_events = transport_errors = 0
        termination: TerminationReason | None = None
        for candidate, stratum in zip(query_set.candidates, strata, strict=True):
            name, quota = str(stratum["name"]), int(stratum["quota"])
            selection = TedSelectionState(published_from=str(window["query_from_date"]), published_before=datetime.fromisoformat(str(window["published_before"]).replace("Z", "+00:00")).strftime("%Y%m%d"), allowed_notice_types=frozenset(cast(Sequence[str], scope["allowed_notice_types"])), form_type=str(scope["form_type"]), cpv_prefix=str(stratum["cpv_prefix"]), max_items_per_buyer=int(source_config["max_items_per_buyer"]), identity_state=identity)
            for page_number in range(1, int(request["max_pages_per_stratum"]) + 1):
                if counts[name] >= quota: break
                allowance = budget.begin_request(max_attempts_per_request=2)
                if not allowance.allowed:
                    termination = self._budget_reason(allowance.termination_reason); break
                response = self._transport.fetch_notices(query=candidate.query, fields=cast(Sequence[str], source_config["fields"]), page=page_number, page_size=int(request["page_size"]), scope=str(api["scope"]), check_query_syntax=False, pagination_mode=str(api["pagination_mode"]), max_http_attempts=allowance.max_http_attempts, request_timeout_seconds=float(request["request_timeout_seconds"]), deadline_seconds=allowance.deadline_seconds, max_response_bytes=allowance.max_response_bytes, max_retries=min(int(retry["max_retries_per_logical_request"]), max(0, allowance.max_http_attempts - 1)), base_backoff_seconds=float(retry["base_backoff_seconds"]), max_backoff_seconds=float(retry["max_backoff_seconds"]), reject_unknown_wrapper_fields=True, allow_nullable_total=False)
                retries += response.retry_count
                rate_events += sum(event.get("category") == "rate_limit" for event in response.events)
                transport_errors += sum(event.get("category") == "transport_error" for event in response.events)
                budget_failure = budget.record(http_attempts=response.http_attempt_count, response_bytes=response.response_bytes)
                if budget_failure:
                    termination = self._budget_reason(budget_failure); break
                if isinstance(response, TedTransportFailure):
                    termination = TerminationReason.TRANSPORT_ERROR; transport_errors += 1; break
                successful += 1
                payloads = response.page.notices
                fetched_by[name] += len(payloads)
                for payload in payloads:
                    if counts[name] >= quota: break
                    processed_by[name] += 1
                    parsed = parse_ted_notice(payload, stratum=name, author_secret=self._secret, run_id=run_id, adapter_version=self.adapter_version, collected_at=started)
                    if parsed.rejection is not None:
                        invalid.append(parsed.rejection); rejected_by[name] += 1
                        if parsed.rejection.error_code == "residual_contact": termination = TerminationReason.PRIVACY_FAILURE; break
                        continue
                    assert parsed.item is not None
                    decision = selection.select(measure_notice(payload))
                    if not decision.accepted:
                        reason = decision.rejection_reason or "selection_rejected"
                        invalid.append(InvalidItem(str(parsed.item["source_item_id"]), reason, (reason,))); rejected_by[name] += 1; continue
                    accepted.append(parsed.item); counts[name] += 1
                if termination is not None: break
                if not response.page.has_more and counts[name] < quota:
                    termination = TerminationReason.SOURCE_EXHAUSTED; break
            if termination is not None: break
        if len(accepted) == target_valid_count and all(counts[str(value["name"])] == int(value["quota"]) for value in strata): termination = TerminationReason.TARGET_REACHED
        elif termination is None: termination = TerminationReason.SOURCE_EXHAUSTED
        segments = tuple(SegmentResult("cpv_stratum", str(value["name"]), int(value["quota"]), counts[str(value["name"])], fetched_by[str(value["name"])], processed_by[str(value["name"])], rejected_by[str(value["name"])]) for value in strata)
        return self._result(run_id, manifest_version, target_valid_count, started, accepted, invalid, segments, termination, manifest_hash, compliance_hash, requests=budget.logical_requests, successful=successful, attempts=budget.http_attempts, retries=retries, response_bytes=budget.response_bytes, rate_events=rate_events, transport_errors=transport_errors)

    @staticmethod
    def _budget_reason(reason: str | None) -> TerminationReason:
        return {"request_budget_exhausted": TerminationReason.REQUEST_BUDGET_EXHAUSTED, "attempt_budget_exhausted": TerminationReason.TRANSPORT_ERROR, "deadline_exhausted": TerminationReason.SMOKE_DEADLINE_EXHAUSTED, "response_byte_budget_exhausted": TerminationReason.TRANSPORT_ERROR}.get(reason, TerminationReason.TRANSPORT_ERROR)

    def _result(self, run_id, manifest_version, target, started, items, invalid, segments, termination, manifest_hash, compliance_hash, *, error_message=None, requests=0, successful=0, attempts=0, retries=0, response_bytes=0, rate_events=0, transport_errors=0):
        status = CollectionStatus.SUCCESS if termination is TerminationReason.TARGET_REACHED else (CollectionStatus.PARTIAL if items else CollectionStatus.FAILED)
        fetched = sum(value.fetched_item_count for value in segments); processed = sum(value.processed_item_count for value in segments)
        return CollectionResult(source=self.source, run_id=run_id, started_at=started, finished_at=self._clock(), target_valid_count=target, status=status, items=items, invalid_items=invalid, request_count=requests, response_bytes=response_bytes, retry_count=retries, rate_limit_events=rate_events, successful_request_count=successful, http_attempt_count=attempts, transport_events=(), error_code=None if status is CollectionStatus.SUCCESS else termination.value, error_message=error_message, manifest_version=manifest_version, adapter_version=self.adapter_version, termination_reason=termination, fetched_item_count=fetched, processed_item_count=processed, accepted_item_count=len(items), rejected_item_count=len(invalid), segment_results=segments, manifest_hash=manifest_hash, compliance_hash=compliance_hash)
