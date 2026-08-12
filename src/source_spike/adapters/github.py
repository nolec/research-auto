from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence, cast

from src.source_spike.adapters.base import InvalidItem
from src.source_spike.raw_items import (
    author_hash,
    canonical_text_fingerprint,
    normalize_text,
    validate_raw_source_item,
)


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(nested) for key, nested in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(nested) for nested in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(nested) for nested in value]
    return value


@dataclass(frozen=True)
class GitHubPage:
    items: Sequence[Mapping[str, object]]
    response_bytes: int
    has_next: bool

    def __post_init__(self) -> None:
        if any(not isinstance(item, Mapping) for item in self.items):
            raise ValueError("items must contain mappings")
        if (
            isinstance(self.response_bytes, bool)
            or not isinstance(self.response_bytes, int)
            or self.response_bytes < 0
        ):
            raise ValueError("response_bytes must be a non-negative integer")
        if not isinstance(self.has_next, bool):
            raise ValueError("has_next must be a boolean")
        try:
            copied = json.loads(
                json.dumps(self.items, ensure_ascii=False, allow_nan=False)
            )
        except (TypeError, ValueError) as error:
            raise ValueError("items must be JSON-compatible") from error
        object.__setattr__(
            self,
            "items",
            tuple(cast(Mapping[str, object], _freeze_json(item)) for item in copied),
        )

    def to_items(self) -> list[dict[str, object]]:
        return cast(
            list[dict[str, object]],
            json.loads(
                json.dumps(_thaw_json(self.items), ensure_ascii=False, allow_nan=False)
            ),
        )


class GitHubTransport(Protocol):
    def fetch_issues(
        self,
        repository: str,
        *,
        page: int,
        per_page: int,
        state: str,
        sort: str,
        direction: str,
    ) -> GitHubPage: ...


@dataclass(frozen=True)
class ParsedGitHubIssue:
    item: dict[str, object] | None
    rejection: InvalidItem | None

    def __post_init__(self) -> None:
        if (self.item is None) == (self.rejection is None):
            raise ValueError("exactly one of item or rejection is required")


def _source_item_id(payload: Mapping[str, object]) -> str | None:
    value = payload.get("id")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _reject(
    source_item_id: str | None, error_code: str, message: str
) -> ParsedGitHubIssue:
    return ParsedGitHubIssue(
        item=None,
        rejection=InvalidItem(source_item_id, error_code, (message,)),
    )


def _utc_timestamp(value: object, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _label_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for label in value:
        if isinstance(label, Mapping) and isinstance(label.get("name"), str):
            name = normalize_text(str(label["name"]))
            if name:
                names.append(name)
    return names


def _validate_parser_config(
    *,
    repository: str,
    author_secret: bytes,
    run_id: str,
    adapter_version: str,
    collected_at: datetime,
) -> None:
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise ValueError("repository must be a non-empty owner/name string")
    owner, name = repository.split("/", maxsplit=1)
    if not owner or not name:
        raise ValueError("repository must be a non-empty owner/name string")
    if not isinstance(author_secret, bytes) or len(author_secret) < 32:
        raise ValueError("author_secret must contain at least 32 bytes")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(adapter_version, str) or not adapter_version:
        raise ValueError("adapter_version must be a non-empty string")
    if (
        not isinstance(collected_at, datetime)
        or collected_at.tzinfo is None
        or collected_at.utcoffset() is None
    ):
        raise ValueError("collected_at must be timezone-aware")


def parse_github_issue(
    payload: Mapping[str, object],
    *,
    repository: str,
    author_secret: bytes,
    run_id: str,
    adapter_version: str,
    collected_at: datetime,
) -> ParsedGitHubIssue:
    _validate_parser_config(
        repository=repository,
        author_secret=author_secret,
        run_id=run_id,
        adapter_version=adapter_version,
        collected_at=collected_at,
    )
    source_item_id = _source_item_id(payload)
    if "pull_request" in payload:
        return _reject(source_item_id, "pr_not_issue", "pull_request field is present")

    body_value = payload.get("body")
    if not isinstance(body_value, str) or not normalize_text(body_value):
        return _reject(
            source_item_id, "missing_body", "issue body is missing or blank"
        )

    title_value = payload.get("title")
    title = normalize_text(title_value) if isinstance(title_value, str) else ""
    body = normalize_text(body_value)
    text = normalize_text(f"{title}\n\n{body}")
    if len(text) < 40:
        return _reject(
            source_item_id,
            "short_text",
            "normalized issue text is shorter than 40 characters",
        )

    try:
        published_at = _utc_timestamp(payload.get("created_at"))
    except (TypeError, ValueError, OverflowError):
        return _reject(
            source_item_id,
            "invalid_timestamp",
            "created_at must be a timezone-aware ISO 8601 timestamp",
        )
    try:
        updated_at = _utc_timestamp(payload.get("updated_at"), nullable=True)
    except (TypeError, ValueError, OverflowError):
        return _reject(
            source_item_id,
            "invalid_timestamp",
            "updated_at must be a timezone-aware ISO 8601 timestamp",
        )

    try:
        if source_item_id is None:
            raise ValueError("id is required")
        issue_number = payload["number"]
        if isinstance(issue_number, bool) or not isinstance(issue_number, int):
            raise ValueError("number must be an integer")
        source_url = payload["html_url"]
        if not isinstance(source_url, str) or not source_url:
            raise ValueError("html_url is required")
        user = payload.get("user")
        raw_author_id = "__unknown__"
        if isinstance(user, Mapping):
            user_id = user.get("id")
            if isinstance(user_id, (str, int)) and not isinstance(user_id, bool):
                raw_author_id = str(user_id)

        original_length = len(text)
        stored_text = text[:20000]
        item: dict[str, object] = {
            "document_id": f"github:{source_item_id}",
            "source": "github",
            "source_item_id": source_item_id,
            "source_url": source_url,
            "item_type": "issue",
            "author_hash": author_hash("github", raw_author_id, author_secret),
            "community": repository,
            "thread_id": f"{repository}:{issue_number}",
            "parent_id": None,
            "title": title or None,
            "text": stored_text,
            "text_fingerprint": canonical_text_fingerprint(stored_text),
            "text_length": len(stored_text),
            "original_text_length": original_length,
            "text_truncated": original_length > len(stored_text),
            "published_at": published_at,
            "updated_at": updated_at,
            "language": None,
            "engagement": {"comments": payload.get("comments", 0)},
            "source_metadata": {
                "state": payload.get("state"),
                "locked": payload.get("locked"),
                "labels": _label_names(payload.get("labels")),
            },
            "collected_at": collected_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "collector_version": adapter_version,
            "fetch_run_id": run_id,
        }
        validation_errors = validate_raw_source_item(item)
        if validation_errors:
            return ParsedGitHubIssue(
                item=None,
                rejection=InvalidItem(
                    source_item_id,
                    "invalid_item",
                    tuple(validation_errors[:20]),
                ),
            )
        return ParsedGitHubIssue(item=item, rejection=None)
    except (KeyError, TypeError, ValueError):
        return _reject(
            source_item_id,
            "invalid_item",
            "issue payload is missing required normalized fields",
        )
