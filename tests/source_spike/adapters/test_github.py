from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.source_spike.adapters.base import InvalidItem
from src.source_spike.adapters.github import parse_github_issue
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
