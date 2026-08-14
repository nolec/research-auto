from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol, Sequence, cast

from src.source_spike.adapters.base import (
    CollectionResult, CollectionStatus, InvalidItem, SegmentResult, TerminationReason,
)
from src.source_spike.protocol import content_sha256
from src.source_spike.raw_items import (
    IncrementalObservationSelector, author_hash, canonical_text_fingerprint,
    normalize_text, validate_raw_source_item,
)


@dataclass(frozen=True)
class ParsedSteamReview:
    item: Mapping[str, object] | None
    rejection: InvalidItem | None


@dataclass(frozen=True)
class SteamReviewPage:
    items: Sequence[Mapping[str, object]]
    response_bytes: int
    cursor: str | None

    def __post_init__(self) -> None:
        copied = json.loads(json.dumps(self.items, ensure_ascii=False, allow_nan=False))
        if not isinstance(self.response_bytes, int) or self.response_bytes < 0:
            raise ValueError("response_bytes must be non-negative")
        if self.cursor is not None and (not isinstance(self.cursor, str) or not self.cursor):
            raise ValueError("cursor must be null or non-empty")
        object.__setattr__(self, "items", tuple(copied))

    def to_items(self) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], json.loads(json.dumps(self.items)))


def _epoch(value: object, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an epoch integer")
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_steam_review(
    payload: Mapping[str, object], *, appid: int, app_name: str, author_secret: bytes,
    run_id: str, adapter_version: str, collected_at: datetime,
    published_after: datetime, published_before: datetime,
) -> ParsedSteamReview:
    recommendation = payload.get("recommendationid")
    source_id = f"{appid}:{recommendation}" if isinstance(recommendation, str) and recommendation else None
    if len(author_secret) < 32 or collected_at.tzinfo is None or not app_name or appid < 1:
        raise ValueError("invalid Steam parser configuration")
    if source_id is None:
        return ParsedSteamReview(None, InvalidItem(None, "missing_item_id", ("recommendationid is required",)))
    review = payload.get("review")
    text = normalize_text(review) if isinstance(review, str) else ""
    if not text:
        return ParsedSteamReview(None, InvalidItem(source_id, "missing_body", ("review text is missing or blank",)))
    if len(text) < 40:
        return ParsedSteamReview(None, InvalidItem(source_id, "short_text", ("normalized review text is shorter than 40 characters",)))
    try:
        published_text = _epoch(payload.get("timestamp_created"), "timestamp_created")
        published = datetime.fromisoformat(published_text.replace("Z", "+00:00"))
    except (ValueError, OSError, OverflowError) as error:
        return ParsedSteamReview(None, InvalidItem(source_id, "invalid_timestamp", (str(error),)))
    if not published_after <= published < published_before:
        return ParsedSteamReview(None, InvalidItem(source_id, "outside_time_window", ("review is outside the frozen publication window",)))
    updated = None
    if payload.get("timestamp_updated") is not None:
        try:
            updated = _epoch(payload.get("timestamp_updated"), "timestamp_updated")
        except (ValueError, OSError, OverflowError) as error:
            return ParsedSteamReview(None, InvalidItem(source_id, "invalid_timestamp", (str(error),)))
    author = payload.get("author")
    steamid = author.get("steamid") if isinstance(author, Mapping) else None
    author_key = str(steamid) if isinstance(steamid, str) and steamid else "__unknown__"
    original_length = len(text)
    stored = text[:20000]
    metadata = {
        "received_for_free": bool(payload.get("received_for_free", False)),
        "steam_purchase": bool(payload.get("steam_purchase", False)),
        "voted_up": bool(payload.get("voted_up", False)),
        "written_during_early_access": bool(payload.get("written_during_early_access", False)),
    }
    helpful = payload.get("votes_up")
    comments = payload.get("comment_count")
    engagement = {}
    if isinstance(helpful, int) and not isinstance(helpful, bool) and helpful >= 0:
        engagement["helpful"] = helpful
    if isinstance(comments, int) and not isinstance(comments, bool) and comments >= 0:
        engagement["comments"] = comments
    item: dict[str, object] = {
        "document_id": f"steam:{source_id}", "source": "steam",
        "source_item_id": source_id,
        "source_url": f"https://steamcommunity.com/app/{appid}/reviews/?recommendationid={recommendation}",
        "item_type": "review", "author_hash": author_hash("steam", author_key, author_secret),
        "community": str(appid), "thread_id": source_id, "parent_id": None,
        "title": app_name, "text": stored,
        "text_fingerprint": canonical_text_fingerprint(stored), "text_length": len(stored),
        "original_text_length": original_length, "text_truncated": original_length > len(stored),
        "published_at": published_text, "updated_at": updated, "language": "en",
        "engagement": engagement, "source_metadata": metadata,
        "collected_at": collected_at.isoformat().replace("+00:00", "Z"),
        "collector_version": adapter_version, "fetch_run_id": run_id,
    }
    errors = validate_raw_source_item(item)
    if errors:
        return ParsedSteamReview(None, InvalidItem(source_id, "invalid_item", tuple(errors)))
    return ParsedSteamReview(item, None)


class SteamTransport(Protocol):
    def fetch_reviews(self, appid: int, *, cursor: str, **kwargs: object) -> object: ...


class SteamReviewAdapter:
    source = "steam"
    adapter_version = "0.1.0"

    def __init__(self, transport: SteamTransport, *, author_secret: bytes,
                 compliance_record: Mapping[str, object],
                 manifest_validator: Callable[[Mapping[str, object], Mapping[str, object]], list[str]],
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._transport = transport
        self._author_secret = author_secret
        self._compliance = dict(compliance_record)
        self._manifest_validator = manifest_validator
        self._clock = clock

    def collect(self, source_config: Mapping[str, object], target_valid_count: int, *,
                run_id: str, manifest_version: str) -> CollectionResult:
        started = self._clock()
        manifest_hash, compliance_hash = content_sha256(source_config), content_sha256(self._compliance)
        errors = self._manifest_validator(source_config, self._compliance)
        if (source_config.get("adapter_version") != self.adapter_version
                or source_config.get("manifest_version") != manifest_version
                or target_valid_count != source_config.get("target_valid_records")
                or len(self._author_secret) < 32):
            errors.append("adapter prerequisites mismatch")
        apps = list(cast(Sequence[Mapping[str, object]], source_config.get("applications", [])))
        if errors:
            segments = [SegmentResult("application", str(x.get("appid")), int(x.get("quota", 0)), 0, 0, 0, 0) for x in apps]
            return self._result(run_id, manifest_version, target_valid_count, started, (), (), segments, TerminationReason.PREREQUISITE_FAILED, 0, 0, manifest_hash, compliance_hash, "; ".join(errors))

        request = cast(Mapping[str, object], source_config["request"])
        retry = cast(Mapping[str, object], source_config["retry"])
        after = datetime.fromisoformat(str(source_config["published_after"]).replace("Z", "+00:00"))
        before = datetime.fromisoformat(str(source_config["published_before"]).replace("Z", "+00:00"))
        selector = IncrementalObservationSelector(max_items_per_author=int(source_config["max_items_per_author"]))
        accepted: list[Mapping[str, object]] = []
        invalid: list[InvalidItem] = []
        counts = {str(x["appid"]): 0 for x in apps}
        fetched_by = {key: 0 for key in counts}; processed_by = {key: 0 for key in counts}; rejected_by = {key: 0 for key in counts}
        requests = successful = attempts = retries = response_bytes = pages = fetched = processed = rate_events = 0
        transport_events: list[Mapping[str, object]] = []
        termination: TerminationReason | None = None
        for app in apps:
            appid, name, quota, cursor = int(app["appid"]), str(app["name"]), int(app["quota"]), "*"
            key = str(appid)
            while counts[key] < quota:
                if requests >= int(request["max_requests"]): termination = TerminationReason.REQUEST_BUDGET_EXHAUSTED; break
                if pages >= int(request["max_pages_total"]): termination = TerminationReason.PAGE_BUDGET_EXHAUSTED; break
                if attempts >= int(request["max_http_attempts"]): termination = TerminationReason.TRANSPORT_ERROR; break
                if (self._clock() - started).total_seconds() >= float(request["max_total_elapsed_seconds"]):
                    termination = TerminationReason.SMOKE_DEADLINE_EXHAUSTED; break
                outcome = self._transport.fetch_reviews(
                    appid, cursor=cursor, num_per_page=int(request["num_per_page"]),
                    filter=request["filter"], language=request["language"],
                    review_type=request["review_type"], purchase_type=request["purchase_type"],
                    filter_offtopic_activity=request["filter_offtopic_activity"],
                    request_timeout_seconds=request["request_timeout_seconds"],
                    max_http_attempts=int(request["max_http_attempts"]) - attempts,
                    max_total_elapsed_seconds=float(request["max_total_elapsed_seconds"])
                    - (self._clock() - started).total_seconds(),
                    max_retries=retry["max_retries"], base_backoff_seconds=retry["base_backoff_seconds"],
                    max_backoff_seconds=retry["max_backoff_seconds"],
                    min_request_interval_seconds=request["min_request_interval_seconds"],
                )
                if isinstance(outcome, SteamReviewPage):
                    page = outcome; attempt_delta = 1; retry_delta = 0; outcome_bytes = page.response_bytes
                else:
                    page = getattr(outcome, "page", None)
                    attempt_delta = int(getattr(outcome, "http_attempt_count", 0))
                    retry_delta = int(getattr(outcome, "retry_count", 0))
                    outcome_bytes = int(getattr(outcome, "response_bytes", 0))
                    events = cast(Sequence[Mapping[str, object]], getattr(outcome, "events", ()))
                    transport_events.extend(events)
                    rate_events += sum(value.get("category") == "rate_limit" for value in events)
                    error_code = getattr(outcome, "error_code", None)
                    if error_code is not None:
                        termination = TerminationReason.SMOKE_DEADLINE_EXHAUSTED if error_code == "smoke_deadline_exhausted" else TerminationReason.TRANSPORT_ERROR
                if attempt_delta > 0: requests += 1
                attempts += attempt_delta; retries += retry_delta; response_bytes += outcome_bytes
                if termination is not None: break
                if not isinstance(page, SteamReviewPage): termination = TerminationReason.TRANSPORT_ERROR; break
                successful += 1; pages += 1
                payloads = page.to_items(); fetched += len(payloads); fetched_by[key] += len(payloads)
                for payload in payloads:
                    if counts[key] >= quota: break
                    processed += 1; processed_by[key] += 1
                    parsed = parse_steam_review(payload, appid=appid, app_name=name,
                        author_secret=self._author_secret, run_id=run_id,
                        adapter_version=self.adapter_version, collected_at=started,
                        published_after=after, published_before=before)
                    if parsed.rejection is not None:
                        invalid.append(parsed.rejection); rejected_by[key] += 1; continue
                    assert parsed.item is not None
                    rejection = selector.add(parsed.item)
                    if rejection is not None:
                        invalid.append(InvalidItem(str(parsed.item["source_item_id"]), rejection.reason, rejection.errors or (rejection.reason,)))
                        rejected_by[key] += 1; continue
                    accepted.append(parsed.item); counts[key] += 1
                if counts[key] >= quota: break
                if not page.cursor or page.cursor == cursor or not payloads:
                    termination = TerminationReason.SOURCE_EXHAUSTED; break
                cursor = page.cursor
            if termination is not None: break
        if len(accepted) == target_valid_count and all(counts[str(x["appid"])] == int(x["quota"]) for x in apps):
            termination = TerminationReason.TARGET_REACHED
        elif termination is None:
            termination = TerminationReason.SOURCE_EXHAUSTED
        segments = [SegmentResult("application", str(x["appid"]), int(x["quota"]), counts[str(x["appid"])], fetched_by[str(x["appid"])], processed_by[str(x["appid"])], rejected_by[str(x["appid"])]) for x in apps]
        return self._result(run_id, manifest_version, target_valid_count, started, accepted, invalid, segments, termination, requests, successful, manifest_hash, compliance_hash, None, fetched, processed, attempts, retries, response_bytes, rate_events, transport_events)

    def _result(self, run_id, manifest_version, target, started, items, invalid, segments,
                termination, requests, successful, manifest_hash, compliance_hash,
                error_message=None, fetched=0, processed=0, attempts=0, retries=0,
                response_bytes=0, rate_events=0, transport_events=()):
        status = CollectionStatus.SUCCESS if termination is TerminationReason.TARGET_REACHED else (CollectionStatus.PARTIAL if items else CollectionStatus.FAILED)
        return CollectionResult(source=self.source, run_id=run_id, started_at=started,
            finished_at=self._clock(), target_valid_count=target, status=status, items=items,
            invalid_items=invalid, request_count=requests, response_bytes=response_bytes,
            retry_count=retries, rate_limit_events=rate_events, successful_request_count=successful,
            http_attempt_count=attempts, transport_events=transport_events,
            error_code=None if status is CollectionStatus.SUCCESS else termination.value,
            error_message=error_message, manifest_version=manifest_version,
            adapter_version=self.adapter_version, termination_reason=termination,
            fetched_item_count=fetched, processed_item_count=processed,
            accepted_item_count=len(items), rejected_item_count=len(invalid),
            segment_results=segments, manifest_hash=manifest_hash, compliance_hash=compliance_hash)
