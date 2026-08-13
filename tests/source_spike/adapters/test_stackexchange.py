from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.source_spike.adapters.base import CollectionStatus, TerminationReason
from src.source_spike.adapters.stackexchange import StackExchangePage, StackExchangeQuestionAdapter, parse_stackexchange_question
from src.source_spike.adapters.stackexchange_http import StackExchangeTransportSuccess
from src.source_spike.protocol import content_sha256
from src.source_spike.raw_items import author_hash, validate_raw_source_item
from src.source_spike.stackexchange_filter import REQUIRED_FIELDS, included_fields_sha256
from src.source_spike.stackexchange_smoke_manifest import validate_stackexchange_smoke_manifest


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/source_spike/stackexchange/questions.json"
SECRET = b"stackexchange-author-secret-32bytes"
NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


def fixtures() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text())


def parse(value: dict[str, object], site: str = "stackoverflow"):
    return parse_stackexchange_question(value, site=site, author_secret=SECRET, run_id="run-1", adapter_version="0.1.0", collected_at=NOW)


def test_parser_normalizes_question_license_and_identity() -> None:
    result = parse(fixtures()[0])
    assert result.rejection is None and result.item is not None
    item = result.item
    assert validate_raw_source_item(item) == []
    assert item["item_type"] == "question"
    assert item["source_item_id"] == "stackoverflow:101"
    assert item["document_id"] == "stackexchange:stackoverflow:101"
    assert item["text"].startswith("Tool & workflow stops unexpectedly")
    assert item["source_metadata"]["content_license"] == "CC BY-SA 4.0"
    assert item["author_hash"] == author_hash("stackexchange", "stackoverflow:9001", SECRET)
    serialized = json.dumps(item)
    assert "9001" not in serialized and "user_id" not in serialized


def test_parser_uses_source_scoped_unknown_owner_and_rejects_missing_evidence() -> None:
    unknown = parse(fixtures()[1], "superuser")
    assert unknown.item is not None
    assert unknown.item["author_hash"] == author_hash("stackexchange", "__unknown__", SECRET)
    assert [parse(value).rejection.error_code for value in fixtures()[2:]] == ["missing_body", "missing_license", "short_text"]


class FixtureTransport:
    def __init__(self, pages): self.pages, self.calls = pages, []
    def fetch_questions(self, site: str, *, page: int, **kwargs):
        self.calls.append((site, page))
        return self.pages.get((site, page), StackExchangePage((), 0, False, None, 10000, 9000))


def manifest():
    compliance = {"source": "stackexchange", "decision": "conditional"}
    filter_record = {"api_version":"2.3","filter_id":"!filter","filter_type":"safe","included_fields":list(REQUIRED_FIELDS),"included_fields_sha256":included_fields_sha256(REQUIRED_FIELDS),"created_at":"2026-08-13T00:00:00Z","verified_at":"2026-08-13T00:00:00Z"}
    value = {"manifest_version":"0.1.0","source":"stackexchange","adapter_version":"0.1.0","target_valid_records":10,"max_items_per_author":2,"published_after":"2026-05-15T00:00:00Z","published_before":"2026-08-13T00:00:00Z","sites":[{"name":"stackoverflow","quota":3},{"name":"superuser","quota":3},{"name":"serverfault","quota":2},{"name":"softwareengineering","quota":2}],"request":{"endpoint":"/2.3/questions","sort":"creation","order":"desc","page_size":30,"max_pages_total":8,"max_requests":12,"max_http_attempts":18,"request_timeout_seconds":10,"max_total_elapsed_seconds":60,"max_backoff_wait_seconds":10,"quota_reserve":100},"retry":{"max_retries":2,"base_backoff_seconds":1,"max_backoff_seconds":8},"filter_ref":"stackexchange-filter.json","filter_hash":content_sha256(filter_record),"compliance_ref":"compliance/stackexchange.json","compliance_hash":content_sha256(compliance),"compliance_decision":"conditional"}
    return value, compliance, filter_record


def question(index: int, site: str) -> dict[str, object]:
    host = "softwareengineering.stackexchange" if site == "softwareengineering" else site
    return {"question_id":index,"title":f"Repeated workflow failure {index}","body":f"<p>A concrete recurring workflow failure number {index} blocks operators from completing their task.</p>","creation_date":1786406400,"link":f"https://{host}.com/questions/{index}/failure","tags":["workflow"],"content_license":"CC BY-SA 4.0","owner":{"user_id":index}}


def test_collection_reaches_global_and_site_quotas() -> None:
    config, compliance, filter_record = manifest()
    pages = {}
    for site, offset in (("stackoverflow",1000),("superuser",2000),("serverfault",3000),("softwareengineering",4000)):
        pages[(site,1)] = StackExchangePage([question(offset+i, site) for i in range(4)], 1000, False, None, 10000, 9000)
    adapter = StackExchangeQuestionAdapter(FixtureTransport(pages), author_secret=SECRET, compliance_record=compliance, filter_record=filter_record, manifest_validator=validate_stackexchange_smoke_manifest, clock=lambda: NOW)
    result = adapter.collect(config, 10, run_id="run-1", manifest_version="0.1.0")
    assert result.status is CollectionStatus.SUCCESS
    assert result.termination_reason is TerminationReason.TARGET_REACHED
    assert [segment.accepted_item_count for segment in result.segment_results] == [3,3,2,2]
    assert [segment.fetched_item_count for segment in result.segment_results] == [4,4,4,4]
    assert [segment.processed_item_count for segment in result.segment_results] == [3,3,2,2]
    assert result.accepted_item_count == 10


def test_collection_stops_before_next_request_when_quota_reserve_is_at_risk() -> None:
    config, compliance, filter_record = manifest()
    pages = {("stackoverflow",1): StackExchangePage([question(1000,"stackoverflow")], 100, True, None, 10000, 105)}
    adapter = StackExchangeQuestionAdapter(FixtureTransport(pages), author_secret=SECRET, compliance_record=compliance, filter_record=filter_record, manifest_validator=validate_stackexchange_smoke_manifest, clock=lambda: NOW)
    result = adapter.collect(config, 10, run_id="run-1", manifest_version="0.1.0")
    assert result.status is CollectionStatus.PARTIAL
    assert result.termination_reason is TerminationReason.QUOTA_BUDGET_EXHAUSTED
    assert result.request_count == 1


def test_collection_accepts_canonical_rate_limit_event_and_counts_it() -> None:
    config, compliance, filter_record = manifest()
    page = StackExchangePage(
        [question(1000 + index, "stackoverflow") for index in range(3)],
        100,
        False,
        None,
        10000,
        9000,
    )
    event = {
        "sequence": 1,
        "category": "rate_limit",
        "attempt": 1,
        "status_code": 429,
        "retryable": True,
        "rate_limit": {
            "limit": None,
            "remaining": None,
            "reset_at": None,
            "resource": None,
            "retry_after_seconds": None,
        },
    }

    class Transport:
        def fetch_questions(self, **kwargs):
            if kwargs["site"] != "stackoverflow":
                return StackExchangePage((), 0, False, None, 10000, 9000)
            return StackExchangeTransportSuccess(page, 2, 1, 100, (event,))

    adapter = StackExchangeQuestionAdapter(
        Transport(),
        author_secret=SECRET,
        compliance_record=compliance,
        filter_record=filter_record,
        manifest_validator=validate_stackexchange_smoke_manifest,
        clock=lambda: NOW,
    )
    result = adapter.collect(config, 10, run_id="run-1", manifest_version="0.1.0")

    assert result.status is CollectionStatus.PARTIAL
    assert result.rate_limit_events == 1
    assert result.transport_events == (event,)


def test_collection_stops_before_zero_remaining_http_attempt_call() -> None:
    config, compliance, filter_record = manifest()
    page = StackExchangePage([question(1000, "stackoverflow")], 100, True, None, 10000, 9000)

    class AttemptBudgetTransport:
        calls = 0

        def fetch_questions(self, **kwargs):
            self.calls += 1
            if kwargs["max_http_attempts"] <= 0:
                raise AssertionError("transport called with exhausted attempt budget")
            return StackExchangeTransportSuccess(page, 18, 17, 100)

    transport = AttemptBudgetTransport()
    adapter = StackExchangeQuestionAdapter(
        transport,
        author_secret=SECRET,
        compliance_record=compliance,
        filter_record=filter_record,
        manifest_validator=validate_stackexchange_smoke_manifest,
        clock=lambda: NOW,
    )
    result = adapter.collect(config, 10, run_id="run-1", manifest_version="0.1.0")

    assert result.status is CollectionStatus.PARTIAL
    assert result.termination_reason is TerminationReason.TRANSPORT_ERROR
    assert result.http_attempt_count == 18
    assert transport.calls == 1


def test_collection_stops_before_transport_when_smoke_deadline_is_exhausted() -> None:
    config, compliance, filter_record = manifest()
    times = iter((NOW, NOW.replace(minute=1), NOW.replace(minute=1)))

    class Transport:
        calls = 0

        def fetch_questions(self, **kwargs):
            self.calls += 1
            raise AssertionError("transport called after smoke deadline")

    transport = Transport()
    adapter = StackExchangeQuestionAdapter(
        transport,
        author_secret=SECRET,
        compliance_record=compliance,
        filter_record=filter_record,
        manifest_validator=validate_stackexchange_smoke_manifest,
        clock=lambda: next(times),
    )

    result = adapter.collect(config, 10, run_id="run-1", manifest_version="0.1.0")

    assert result.status is CollectionStatus.FAILED
    assert result.termination_reason is TerminationReason.SMOKE_DEADLINE_EXHAUSTED
    assert transport.calls == 0
