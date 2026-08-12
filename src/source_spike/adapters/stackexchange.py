from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol, Sequence, cast
from urllib.parse import urlparse

from src.source_spike.adapters.base import CollectionResult, CollectionStatus, InvalidItem, SegmentResult, TerminationReason
from src.source_spike.protocol import content_sha256
from src.source_spike.raw_items import IncrementalObservationSelector, author_hash, canonical_text_fingerprint, normalize_text, validate_raw_source_item
from src.source_spike.stackexchange_html import html_body_to_text, html_title_to_text
from src.source_spike.stackexchange_smoke_manifest import validate_stackexchange_smoke_manifest


@dataclass(frozen=True)
class ParsedQuestion:
    item: Mapping[str, object] | None
    rejection: InvalidItem | None


@dataclass(frozen=True)
class StackExchangePage:
    items: Sequence[Mapping[str, object]]
    response_bytes: int
    has_more: bool
    backoff: int | None
    quota_max: int
    quota_remaining: int

    def __post_init__(self) -> None:
        copied = json.loads(json.dumps(self.items, ensure_ascii=False, allow_nan=False))
        if not isinstance(self.response_bytes, int) or self.response_bytes < 0:
            raise ValueError("response_bytes must be non-negative")
        if not isinstance(self.has_more, bool):
            raise ValueError("has_more must be boolean")
        for name, value in (("quota_max", self.quota_max), ("quota_remaining", self.quota_remaining)):
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.backoff is not None and (not isinstance(self.backoff, int) or self.backoff < 0):
            raise ValueError("backoff must be null or non-negative")
        object.__setattr__(self, "items", tuple(copied))

    def to_items(self) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], json.loads(json.dumps(self.items)))


def _iso_epoch(value: object, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an epoch integer")
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_stackexchange_question(
    payload: Mapping[str, object], *, site: str, author_secret: bytes, run_id: str,
    adapter_version: str, collected_at: datetime,
) -> ParsedQuestion:
    source_id = str(payload.get("question_id")) if payload.get("question_id") is not None else None
    if len(author_secret) < 32 or collected_at.tzinfo is None or not site:
        raise ValueError("invalid Stack Exchange parser configuration")
    body = payload.get("body")
    if not isinstance(body, str) or not html_body_to_text(body):
        return ParsedQuestion(None, InvalidItem(source_id, "missing_body", ("question body is missing or blank",)))
    license_value = payload.get("content_license")
    if not isinstance(license_value, str) or not license_value.strip():
        return ParsedQuestion(None, InvalidItem(source_id, "missing_license", ("content_license is required",)))
    title_value = payload.get("title")
    title = html_title_to_text(title_value) if isinstance(title_value, str) else ""
    text = normalize_text(f"{title} {html_body_to_text(body)}")
    if len(text) < 40:
        return ParsedQuestion(None, InvalidItem(source_id, "short_text", ("normalized question text is shorter than 40 characters",)))
    try:
        published = _iso_epoch(payload.get("creation_date"), "creation_date")
    except (ValueError, OSError, OverflowError) as error:
        return ParsedQuestion(None, InvalidItem(source_id, "invalid_timestamp", (str(error),)))
    link = payload.get("link")
    parsed_url = urlparse(str(link)) if isinstance(link, str) else None
    if parsed_url is None or parsed_url.scheme != "https" or not parsed_url.netloc or "/questions/" not in parsed_url.path:
        return ParsedQuestion(None, InvalidItem(source_id, "invalid_url", ("link must be a canonical HTTPS question URL",)))
    owner = payload.get("owner")
    owner_id = owner.get("user_id") if isinstance(owner, Mapping) else None
    owner_key = f"{site}:{owner_id}" if isinstance(owner_id, int) and not isinstance(owner_id, bool) else "__unknown__"
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    original_length = len(text)
    stored = text[:20000]
    item: dict[str, object] = {
        "document_id": f"stackexchange:{source_id}", "source": "stackexchange",
        "source_item_id": source_id, "source_url": str(link), "item_type": "question",
        "author_hash": author_hash("stackexchange", owner_key, author_secret), "community": site,
        "thread_id": f"{site}:{source_id}", "parent_id": None, "title": title or None,
        "text": stored, "text_fingerprint": canonical_text_fingerprint(stored), "text_length": len(stored),
        "original_text_length": original_length, "text_truncated": original_length > len(stored),
        "published_at": published, "updated_at": None, "language": None, "engagement": {},
        "source_metadata": {"content_license": license_value.strip(), "tags": tags},
        "collected_at": collected_at.isoformat().replace("+00:00", "Z"), "collector_version": adapter_version,
        "fetch_run_id": run_id,
    }
    errors = validate_raw_source_item(item)
    if errors:
        return ParsedQuestion(None, InvalidItem(source_id, "invalid_item", tuple(errors)))
    return ParsedQuestion(item, None)


class StackExchangeTransport(Protocol):
    def fetch_questions(self, site: str, *, page: int, **kwargs: object) -> object: ...


class StackExchangeQuestionAdapter:
    source = "stackexchange"
    adapter_version = "0.1.0"

    def __init__(self, transport: StackExchangeTransport, *, author_secret: bytes,
                 compliance_record: Mapping[str, object], filter_record: Mapping[str, object],
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._transport, self._author_secret = transport, author_secret
        self._compliance, self._filter, self._clock = dict(compliance_record), dict(filter_record), clock

    def collect(self, source_config: Mapping[str, object], target_valid_count: int, *, run_id: str, manifest_version: str) -> CollectionResult:
        started = self._clock(); manifest_hash = content_sha256(source_config); compliance_hash = content_sha256(self._compliance)
        errors = validate_stackexchange_smoke_manifest(source_config, self._compliance, self._filter)
        if source_config.get("adapter_version") != self.adapter_version or source_config.get("manifest_version") != manifest_version or target_valid_count != source_config.get("target_valid_records") or len(self._author_secret) < 32:
            errors.append("adapter prerequisites mismatch")
        sites = list(cast(Sequence[Mapping[str, object]], source_config.get("sites", [])))
        if errors:
            return self._result(run_id, manifest_version, target_valid_count, started, (), (), [SegmentResult("site", str(x.get("name")), int(x.get("quota", 0)), 0) for x in sites] or [SegmentResult("source", self.source, target_valid_count, 0)], TerminationReason.PREREQUISITE_FAILED, 0, 0, 0, 0, 0, manifest_hash, compliance_hash, "; ".join(errors))
        request = cast(Mapping[str, object], source_config["request"]); selector = IncrementalObservationSelector(max_items_per_author=int(source_config["max_items_per_author"]))
        accepted: list[Mapping[str, object]] = []; invalid: list[InvalidItem] = []; counts = {str(x["name"]): 0 for x in sites}
        requests = successful = attempts = retries = fetched = processed = response_bytes = pages = rate_events = 0; termination = None
        transport_events: list[Mapping[str, object]] = []
        for site_value in sites:
            site, quota, page_number = str(site_value["name"]), int(site_value["quota"]), 1
            while counts[site] < quota:
                if requests >= int(request["max_requests"]): termination = TerminationReason.REQUEST_BUDGET_EXHAUSTED; break
                if pages >= int(request["max_pages_total"]): termination = TerminationReason.PAGE_BUDGET_EXHAUSTED; break
                if attempts >= int(request["max_http_attempts"]): termination = TerminationReason.TRANSPORT_ERROR; break
                remaining_elapsed = float(request["max_total_elapsed_seconds"]) - (self._clock() - started).total_seconds()
                if remaining_elapsed <= 0: termination = TerminationReason.SMOKE_DEADLINE_EXHAUSTED; break
                outcome = self._transport.fetch_questions(site=site, page=page_number, page_size=int(request["page_size"]), filter_id=str(self._filter["filter_id"]), sort="creation", order="desc", published_after=source_config["published_after"], published_before=source_config["published_before"], max_http_attempts=int(request["max_http_attempts"])-attempts, request_timeout_seconds=float(request["request_timeout_seconds"]), max_total_elapsed_seconds=remaining_elapsed, max_backoff_wait_seconds=float(request["max_backoff_wait_seconds"]), max_retries=int(cast(Mapping[str, object], source_config["retry"])["max_retries"]), base_backoff_seconds=float(cast(Mapping[str, object], source_config["retry"])["base_backoff_seconds"]), max_backoff_seconds=float(cast(Mapping[str, object], source_config["retry"])["max_backoff_seconds"]))
                if isinstance(outcome, StackExchangePage):
                    page = outcome; attempt_delta = 1; retry_delta = 0; outcome_bytes = page.response_bytes
                else:
                    attempt_delta = int(getattr(outcome, "http_attempt_count", 0)); retry_delta = int(getattr(outcome, "retry_count", 0)); outcome_bytes = int(getattr(outcome, "response_bytes", 0)); page = getattr(outcome, "page", None)
                    outcome_events = cast(Sequence[Mapping[str, object]], getattr(outcome, "events", ()))
                    transport_events.extend(outcome_events)
                    rate_events += sum(event.get("category") == "rate_limit" for event in outcome_events)
                    error_code = getattr(outcome, "error_code", None)
                    if error_code is not None:
                        termination = {"backoff_budget_exhausted":TerminationReason.BACKOFF_BUDGET_EXHAUSTED,"smoke_deadline_exhausted":TerminationReason.SMOKE_DEADLINE_EXHAUSTED}.get(str(error_code), TerminationReason.TRANSPORT_ERROR)
                if attempt_delta > 0: requests += 1
                attempts += attempt_delta; retries += retry_delta; response_bytes += outcome_bytes
                if termination is not None: break
                if not isinstance(page, StackExchangePage): termination = TerminationReason.TRANSPORT_ERROR; break
                successful += 1
                if page.backoff is not None: rate_events += 1
                pages += 1; payloads = page.to_items(); fetched += len(payloads)
                for payload in payloads:
                    if counts[site] >= quota: break
                    processed += 1
                    parsed = parse_stackexchange_question(payload, site=site, author_secret=self._author_secret, run_id=run_id, adapter_version=self.adapter_version, collected_at=started)
                    if parsed.rejection is not None: invalid.append(parsed.rejection); continue
                    assert parsed.item is not None
                    rejection = selector.add(parsed.item)
                    if rejection is not None:
                        invalid.append(InvalidItem(str(parsed.item["source_item_id"]), rejection.reason, rejection.errors or (rejection.reason,))); continue
                    accepted.append(parsed.item); counts[site] += 1
                if counts[site] >= quota: break
                remaining_request_budget = int(request["max_requests"]) - requests
                if page.quota_remaining < int(request["quota_reserve"]) + remaining_request_budget:
                    termination = TerminationReason.QUOTA_BUDGET_EXHAUSTED; break
                if not page.has_more: termination = TerminationReason.SOURCE_EXHAUSTED; break
                page_number += 1
            if termination is not None: break
        if len(accepted) == target_valid_count and all(counts[str(x["name"])] == int(x["quota"]) for x in sites): termination = TerminationReason.TARGET_REACHED
        elif termination is None: termination = TerminationReason.SOURCE_EXHAUSTED
        segments = [SegmentResult("site", str(x["name"]), int(x["quota"]), counts[str(x["name"])]) for x in sites]
        return self._result(run_id, manifest_version, target_valid_count, started, accepted, invalid, segments, termination, requests, successful, attempts, retries, response_bytes, manifest_hash, compliance_hash, None, fetched, processed, rate_events, transport_events)

    def _result(self, run_id, manifest_version, target, started, items, invalid, segments, termination, requests, successful, attempts, retries, response_bytes, manifest_hash, compliance_hash, error_message=None, fetched=0, processed=0, rate_events=0, transport_events=()):
        status = CollectionStatus.SUCCESS if termination is TerminationReason.TARGET_REACHED else (CollectionStatus.PARTIAL if items else CollectionStatus.FAILED)
        result_error = None if status is CollectionStatus.SUCCESS else termination.value
        return CollectionResult(source=self.source, run_id=run_id, started_at=started, finished_at=self._clock(), target_valid_count=target, status=status, items=items, invalid_items=invalid, request_count=requests, response_bytes=response_bytes, retry_count=retries, rate_limit_events=rate_events, successful_request_count=successful, http_attempt_count=attempts, transport_events=transport_events, error_code=result_error, error_message=error_message, manifest_version=manifest_version, adapter_version=self.adapter_version, termination_reason=termination, fetched_item_count=fetched, processed_item_count=processed, accepted_item_count=len(items), rejected_item_count=len(invalid), segment_results=segments, manifest_hash=manifest_hash, compliance_hash=compliance_hash)
