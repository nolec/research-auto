from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.source_spike.adapters.base import InvalidItem
from src.source_spike.adapters.base import CollectionStatus, TerminationReason
from src.source_spike.adapters.github import (
    GitHubFixtureAdapter,
    GitHubPage,
    parse_github_issue,
)
from src.source_spike.protocol import content_sha256
from src.source_spike.raw_items import author_hash, validate_raw_source_item


FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures/source_spike/github/issues.json"
SECRET = b"github-smoke-author-secret-32-bytes"
COLLECTED_AT = datetime(2026, 8, 12, 3, 0, tzinfo=timezone.utc)


def fixtures() -> list[dict[str, object]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def parse(payload: dict[str, object]):
    return parse_github_issue(
        payload,
        repository="example/project",
        author_secret=SECRET,
        run_id="run-fixture",
        adapter_version="0.1.0",
        collected_at=COLLECTED_AT,
    )


def test_parser_normalizes_a_public_issue_without_retaining_raw_identity() -> None:
    parsed = parse(fixtures()[0])
    assert parsed.rejection is None
    assert parsed.item is not None
    assert validate_raw_source_item(parsed.item) == []
    assert parsed.item["source_item_id"] == "101"
    assert parsed.item["document_id"] == "github:101"
    assert parsed.item["thread_id"] == "example/project:11"
    assert parsed.item["title"] == "Search results lose keyboard focus"
    assert parsed.item["text"].startswith("Search results lose keyboard focus After")
    assert parsed.item["published_at"] == "2026-08-10T01:02:03Z"
    assert parsed.item["updated_at"] == "2026-08-10T02:03:04Z"
    assert parsed.item["author_hash"] == author_hash("github", "9001", SECRET)
    serialized = json.dumps(parsed.item, sort_keys=True)
    assert "private-login" not in serialized
    assert '"user"' not in serialized
    assert '"id": 9001' not in serialized


def test_parser_uses_one_source_scoped_hash_for_unknown_authors() -> None:
    payload = fixtures()[5]
    first = parse(payload)
    second = parse(dict(payload, id=107, number=17))
    assert first.item is not None
    assert second.item is not None
    assert first.item["author_hash"] == author_hash("github", "__unknown__", SECRET)
    assert second.item["author_hash"] == first.item["author_hash"]


def test_parser_records_conservative_rejection_reasons() -> None:
    results = [parse(payload) for payload in fixtures()[1:5]]
    assert [result.item for result in results] == [None, None, None, None]
    assert [result.rejection for result in results] == [
        InvalidItem("102", "pr_not_issue", ("pull_request field is present",)),
        InvalidItem("103", "missing_body", ("issue body is missing or blank",)),
        InvalidItem("104", "short_text", ("normalized issue text is shorter than 40 characters",)),
        InvalidItem("105", "invalid_timestamp", ("created_at must be a timezone-aware ISO 8601 timestamp",)),
    ]


def test_parser_turns_malformed_success_payload_into_invalid_item() -> None:
    payload = fixtures()[0]
    payload.pop("html_url")
    parsed = parse(payload)
    assert parsed.item is None
    assert parsed.rejection is not None
    assert parsed.rejection.error_code == "invalid_item"
    assert parsed.rejection.source_item_id == "101"
    assert parsed.rejection.errors


def test_parser_rejects_invalid_run_configuration_before_payload_handling() -> None:
    payload = fixtures()[0]

    with pytest.raises(ValueError, match="author_secret"):
        parse_github_issue(
            payload,
            repository="example/project",
            author_secret=b"short",
            run_id="run-fixture",
            adapter_version="0.1.0",
            collected_at=COLLECTED_AT,
        )

    with pytest.raises(ValueError, match="collected_at"):
        parse_github_issue(
            payload,
            repository="example/project",
            author_secret=SECRET,
            run_id="run-fixture",
            adapter_version="0.1.0",
            collected_at=COLLECTED_AT.replace(tzinfo=None),
        )


@pytest.mark.parametrize("repository", ["/", "owner/", "/repo"])
def test_parser_rejects_repository_with_an_empty_owner_or_name(
    repository: str,
) -> None:
    with pytest.raises(ValueError, match="repository"):
        parse_github_issue(
            fixtures()[0],
            repository=repository,
            author_secret=SECRET,
            run_id="run-fixture",
            adapter_version="0.1.0",
            collected_at=COLLECTED_AT,
        )


def test_parser_identifies_the_invalid_timestamp_field() -> None:
    payload = fixtures()[0]
    payload["updated_at"] = "not-a-timestamp"

    parsed = parse(payload)

    assert parsed.rejection == InvalidItem(
        "101",
        "invalid_timestamp",
        ("updated_at must be a timezone-aware ISO 8601 timestamp",),
    )


def test_github_page_is_isolated_from_input_and_output_mutation() -> None:
    payload = fixtures()[0]
    page = GitHubPage(items=[payload], response_bytes=2048, has_next=True)

    payload["title"] = "mutated input"
    first_items = page.to_items()
    first_items[0]["title"] = "mutated output"

    assert page.to_items()[0]["title"] == "  Search   results lose keyboard focus  "
    assert page.response_bytes == 2048
    assert page.has_next is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"items": ["not-a-mapping"]}, "items"),
        ({"response_bytes": -1}, "response_bytes"),
        ({"response_bytes": True}, "response_bytes"),
        ({"has_next": 1}, "has_next"),
        ({"items": [{"value": float("nan")}]}, "JSON-compatible"),
    ],
)
def test_github_page_rejects_invalid_transport_values(
    kwargs: dict[str, object], message: str
) -> None:
    arguments: dict[str, object] = {
        "items": [fixtures()[0]],
        "response_bytes": 100,
        "has_next": False,
    }
    arguments.update(kwargs)

    with pytest.raises(ValueError, match=message):
        GitHubPage(**arguments)


class FixtureTransport:
    def __init__(self, pages: dict[tuple[str, int], GitHubPage]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, int]] = []

    def fetch_issues(self, repository: str, *, page: int, **_: object) -> GitHubPage:
        self.calls.append((repository, page))
        return self.pages.get((repository, page), GitHubPage((), 0, False))


def issue(index: int, repository: str) -> dict[str, object]:
    payload = fixtures()[0]
    payload.update(
        id=index,
        number=index,
        html_url=f"https://github.com/{repository}/issues/{index}",
        title=f"Workflow failure {index}",
        body=f"Repeated concrete workflow friction number {index} causes measurable delays for operators.",
        user={"id": index},
    )
    return payload


def smoke_manifest() -> tuple[dict[str, object], dict[str, object]]:
    compliance = {"source": "github", "decision": "conditional"}
    manifest: dict[str, object] = {
        "manifest_version": "0.2.0",
        "source": "github",
        "adapter_version": "0.2.0",
        "target_valid_records": 10,
        "max_items_per_author": 2,
        "repositories": [
            {"name": "microsoft/vscode", "quota": 5},
            {"name": "python/cpython", "quota": 5},
        ],
        "request": {
            "endpoint": "/repos/{owner}/{repo}/issues",
            "state": "open",
            "sort": "created",
            "direction": "desc",
            "per_page": 30,
            "max_pages_total": 4,
            "max_requests": 8,
            "max_http_attempts": 12,
            "request_timeout_seconds": 10,
            "max_total_elapsed_seconds": 45,
            "max_rate_limit_wait_seconds": 8,
        },
        "retry": {"max_retries": 2, "base_backoff_seconds": 1, "max_backoff_seconds": 8},
        "compliance_ref": "compliance/github.json",
        "compliance_hash": content_sha256(compliance),
        "compliance_decision": "conditional",
    }
    return manifest, compliance


def test_fixture_collection_reaches_global_and_repository_quotas() -> None:
    manifest, compliance = smoke_manifest()
    pages = {
        (repository, 1): GitHubPage(
            [issue(offset + index, repository) for index in range(6)], 1000, False
        )
        for repository, offset in (("microsoft/vscode", 1000), ("python/cpython", 2000))
    }
    adapter = GitHubFixtureAdapter(
        FixtureTransport(pages), author_secret=SECRET, compliance_record=compliance,
        clock=lambda: COLLECTED_AT,
    )

    result = adapter.collect(
        manifest, 10, run_id="run-fixture", manifest_version="0.2.0"
    )

    assert result.status is CollectionStatus.SUCCESS
    assert result.termination_reason is TerminationReason.TARGET_REACHED
    assert result.accepted_item_count == 10
    assert [segment.accepted_item_count for segment in result.segment_results] == [5, 5]
    assert result.fetched_item_count == 12
    assert result.processed_item_count == 10
    assert result.invalid_items == ()
    assert result.manifest_hash == content_sha256(manifest)
    assert result.compliance_hash == content_sha256(compliance)


def test_fixture_collection_returns_partial_when_repository_is_exhausted() -> None:
    manifest, compliance = smoke_manifest()
    pages = {
        ("microsoft/vscode", 1): GitHubPage(
            [issue(1000 + index, "microsoft/vscode") for index in range(3)], 500, False
        )
    }
    adapter = GitHubFixtureAdapter(
        FixtureTransport(pages), author_secret=SECRET, compliance_record=compliance,
        clock=lambda: COLLECTED_AT,
    )

    result = adapter.collect(
        manifest, 10, run_id="run-fixture", manifest_version="0.2.0"
    )

    assert result.status is CollectionStatus.PARTIAL
    assert result.termination_reason is TerminationReason.REPOSITORY_QUOTA_UNREACHABLE
    assert result.accepted_item_count == 3


def test_fixture_collection_fails_before_fetch_on_invalid_prerequisite() -> None:
    manifest, compliance = smoke_manifest()
    manifest["compliance_hash"] = "0" * 64
    transport = FixtureTransport({})
    adapter = GitHubFixtureAdapter(
        transport, author_secret=SECRET, compliance_record=compliance,
        clock=lambda: COLLECTED_AT,
    )

    result = adapter.collect(
        manifest, 10, run_id="run-fixture", manifest_version="0.2.0"
    )

    assert result.status is CollectionStatus.FAILED
    assert result.termination_reason is TerminationReason.PREREQUISITE_FAILED
    assert result.accepted_item_count == 0
    assert transport.calls == []


@pytest.mark.parametrize("failure", ["empty_repository", "short_author_secret"])
def test_fixture_collection_rejects_all_prerequisites_before_fetch(failure: str) -> None:
    manifest, compliance = smoke_manifest()
    secret = SECRET
    if failure == "empty_repository":
        manifest["repositories"][0]["name"] = ""  # type: ignore[index]
    else:
        secret = b"short"
    transport = FixtureTransport({})
    adapter = GitHubFixtureAdapter(
        transport, author_secret=secret, compliance_record=compliance,
        clock=lambda: COLLECTED_AT,
    )

    result = adapter.collect(
        manifest, 10, run_id="run-fixture", manifest_version="0.2.0"
    )

    assert result.status is CollectionStatus.FAILED
    assert result.termination_reason is TerminationReason.PREREQUISITE_FAILED
    assert transport.calls == []


def test_fixture_collection_records_the_first_page_budget_terminal_event() -> None:
    manifest, compliance = smoke_manifest()
    manifest["request"]["max_pages_total"] = 1  # type: ignore[index]
    pages = {
        ("microsoft/vscode", 1): GitHubPage(
            [issue(1000, "microsoft/vscode")], 200, True
        )
    }
    adapter = GitHubFixtureAdapter(
        FixtureTransport(pages), author_secret=SECRET, compliance_record=compliance,
        clock=lambda: COLLECTED_AT,
    )

    result = adapter.collect(
        manifest, 10, run_id="run-fixture", manifest_version="0.2.0"
    )

    assert result.status is CollectionStatus.PARTIAL
    assert result.termination_reason is TerminationReason.PAGE_BUDGET_EXHAUSTED
    assert result.request_count == 1
    assert result.accepted_item_count == 1


def test_fixture_collection_records_request_budget_before_another_fetch() -> None:
    manifest, compliance = smoke_manifest()
    manifest["request"]["max_requests"] = 1  # type: ignore[index]
    manifest["retry"]["max_retries"] = 0  # type: ignore[index]
    pages = {
        ("microsoft/vscode", 1): GitHubPage(
            [issue(1000, "microsoft/vscode")], 200, True
        )
    }
    transport = FixtureTransport(pages)
    adapter = GitHubFixtureAdapter(
        transport, author_secret=SECRET, compliance_record=compliance,
        clock=lambda: COLLECTED_AT,
    )

    result = adapter.collect(
        manifest, 10, run_id="run-fixture", manifest_version="0.2.0"
    )

    assert result.termination_reason is TerminationReason.REQUEST_BUDGET_EXHAUSTED
    assert result.request_count == 1
    assert transport.calls == [("microsoft/vscode", 1)]


def test_fixture_collection_preserves_parser_then_selector_rejection_order() -> None:
    manifest, compliance = smoke_manifest()
    pull_request = issue(1000, "microsoft/vscode")
    pull_request["pull_request"] = {"url": "https://api.github.test/pr/1"}
    accepted = issue(1001, "microsoft/vscode")
    duplicate_text = issue(1002, "microsoft/vscode")
    duplicate_text["title"] = accepted["title"]
    duplicate_text["body"] = accepted["body"]
    pages = {
        ("microsoft/vscode", 1): GitHubPage(
            [pull_request, accepted, duplicate_text], 300, False
        )
    }
    adapter = GitHubFixtureAdapter(
        FixtureTransport(pages), author_secret=SECRET, compliance_record=compliance,
        clock=lambda: COLLECTED_AT,
    )

    result = adapter.collect(
        manifest, 10, run_id="run-fixture", manifest_version="0.2.0"
    )

    assert [item.error_code for item in result.invalid_items] == [
        "pr_not_issue",
        "duplicate_text",
    ]


class ZeroAttemptDeadlineTransport:
    def fetch_issues(self, *_args: object, **_kwargs: object):
        from src.source_spike.adapters.github_http import GitHubTransportFailure

        return GitHubTransportFailure(
            "smoke_deadline_exhausted", 0, 0, 0, 0, ()
        )


def test_zero_attempt_deadline_does_not_count_a_logical_request() -> None:
    manifest, compliance = smoke_manifest()
    adapter = GitHubFixtureAdapter(
        ZeroAttemptDeadlineTransport(), author_secret=SECRET,
        compliance_record=compliance, clock=lambda: COLLECTED_AT,
    )

    result = adapter.collect(
        manifest, 10, run_id="run-fixture", manifest_version="0.2.0"
    )

    assert result.termination_reason is TerminationReason.SMOKE_DEADLINE_EXHAUSTED
    assert result.request_count == 0
    assert result.http_attempt_count == 0


def test_adapter_uses_injected_manifest_validator() -> None:
    manifest, compliance = smoke_manifest()
    calls: list[str] = []

    def validator(_manifest, _compliance):
        calls.append("validated")
        return ["analysis profile rejected"]

    adapter = GitHubFixtureAdapter(
        FixtureTransport({}), author_secret=SECRET,
        compliance_record=compliance, clock=lambda: COLLECTED_AT,
        manifest_validator=validator,
    )

    result = adapter.collect(
        manifest, 10, run_id="run-fixture", manifest_version="0.2.0"
    )

    assert calls == ["validated"]
    assert result.termination_reason is TerminationReason.PREREQUISITE_FAILED
    assert result.error_message == "analysis profile rejected"


def test_analysis_profile_rejects_items_after_frozen_cutoff() -> None:
    manifest, compliance = smoke_manifest()
    manifest["published_before"] = "2026-08-12T00:00:00Z"
    later = issue(999, "microsoft/vscode")
    later["created_at"] = "2026-08-12T00:00:01Z"
    pages = {
        ("microsoft/vscode", 1): GitHubPage([later], 100, False),
    }
    adapter = GitHubFixtureAdapter(
        FixtureTransport(pages), author_secret=SECRET,
        compliance_record=compliance, clock=lambda: COLLECTED_AT,
        manifest_validator=lambda _manifest, _compliance: [],
    )

    result = adapter.collect(
        manifest, 10, run_id="run-analysis", manifest_version="0.2.0"
    )

    assert result.accepted_item_count == 0
    assert [item.error_code for item in result.invalid_items] == ["after_cutoff"]
