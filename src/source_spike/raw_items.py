from __future__ import annotations

import hmac
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


_WHITESPACE = re.compile(r"\s+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "raw-source-item.schema.json"
_VALIDATOR = Draft202012Validator(
    json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FORMAT_CHECKER,
)
_FORBIDDEN_IDENTITY_KEYS = {
    "account_id",
    "author",
    "author_display_name",
    "author_id",
    "author_username",
    "by",
    "display_name",
    "email",
    "profile_url",
    "steamid",
    "user",
    "user_id",
    "user_name",
    "username",
}
_ALLOWED_METADATA_PATHS = {
    "github": {"labels", "locked", "state"},
    "stackexchange": {"accepted_answer_id", "closed_reason", "content_license", "is_answered", "tags"},
    "steam": {
        "playtime_forever",
        "received_for_free",
        "steam_purchase",
        "voted_up",
        "written_during_early_access",
    },
    "youtube": {"can_reply", "is_public", "video_id"},
    "reddit": {"link_flair_text", "locked", "over_18", "stickied", "subreddit"},
    "hackernews": {"dead", "deleted", "type"},
}


def normalize_text(value: str) -> str:
    """Normalize display text without changing its letter case."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


def canonical_text_fingerprint(value: str) -> str:
    """Return a stable fingerprint for case- and whitespace-insensitive deduplication."""
    canonical = normalize_text(value).casefold().encode("utf-8")
    return sha256(canonical).hexdigest()


def author_hash(source: str, source_author_id: str, secret: bytes) -> str:
    """Create a stable source-scoped author identifier without retaining raw identity."""
    if not source or not source_author_id:
        raise ValueError("source and source_author_id must be non-empty")
    if len(secret) < 32:
        raise ValueError("author hash secret must contain at least 32 bytes")
    message = f"{source}\0{source_author_id}".encode("utf-8")
    return hmac.new(secret, message, sha256).hexdigest()


def _canonical_metadata_key(value: str) -> str:
    separated = _CAMEL_BOUNDARY.sub("_", value)
    return _NON_ALPHANUMERIC.sub("_", separated.casefold()).strip("_")


def _identity_paths(value: object, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            normalized_key = _canonical_metadata_key(key_text)
            if normalized_key in _FORBIDDEN_IDENTITY_KEYS:
                paths.append(path)
            paths.extend(_identity_paths(nested_value, path))
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            path = f"{prefix}[{index}]"
            paths.extend(_identity_paths(nested_value, path))
    return paths


def _metadata_key_paths(value: object, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            paths.append(path)
            paths.extend(_metadata_key_paths(nested_value, path))
    elif isinstance(value, list):
        for nested_value in value:
            paths.extend(_metadata_key_paths(nested_value, prefix))
    return paths


def _json_compatibility_errors(value: object, prefix: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if not isinstance(key, str):
                errors.append(f"source_metadata contains non-string key at {key}")
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            errors.extend(_json_compatibility_errors(nested_value, path))
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            path = f"{prefix}[{index}]"
            errors.extend(_json_compatibility_errors(nested_value, path))
    elif isinstance(value, tuple):
        errors.append(
            f"source_metadata contains non-JSON sequence at {prefix or '$'}: tuple"
        )
    elif isinstance(value, float):
        if not math.isfinite(value):
            errors.append(
                f"source_metadata contains non-finite number at {prefix or '$'}"
            )
    elif value is None or isinstance(value, (str, bool, int)):
        pass
    else:
        errors.append(
            f"source_metadata contains non-JSON value at {prefix or '$'}: "
            f"{type(value).__name__}"
        )
    return errors


def validate_raw_source_item(item: Mapping[str, object]) -> list[str]:
    schema_errors = sorted(
        _VALIDATOR.iter_errors(item),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if schema_errors:
        return [
            f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
            for error in schema_errors
        ]

    errors: list[str] = []
    source = str(item["source"])
    source_item_id = str(item["source_item_id"])
    expected_document_id = f"{source}:{source_item_id}"
    if item["document_id"] != expected_document_id:
        errors.append(
            f"document_id must equal source:source_item_id ({expected_document_id})"
        )

    text = str(item["text"])
    normalized_text = normalize_text(text)
    if len(normalized_text) < 40:
        errors.append("text must contain at least 40 normalized characters")
    if text != normalized_text:
        errors.append("text must be normalized before storage")
    if item["text_length"] != len(text):
        errors.append("text_length must equal the stored normalized text length")
    if item["text_fingerprint"] != canonical_text_fingerprint(text):
        errors.append("text_fingerprint does not match normalized text")

    original_length = int(item["original_text_length"])
    is_truncated = bool(item["text_truncated"])
    if is_truncated:
        if len(text) != 20000 or original_length <= len(text):
            errors.append(
                "truncated text must store 20000 characters and a larger original length"
            )
    elif original_length != len(text):
        errors.append("untruncated original_text_length must equal text_length")

    identity_paths = _identity_paths(item["source_metadata"])
    for path in identity_paths:
        errors.append(f"source_metadata contains forbidden identity key: {path}")
    if not identity_paths:
        allowed_paths = _ALLOWED_METADATA_PATHS.get(source, set())
        for path in _metadata_key_paths(item["source_metadata"]):
            canonical_path = ".".join(
                _canonical_metadata_key(part) for part in path.split(".")
            )
            if canonical_path not in allowed_paths:
                errors.append(
                    f"source_metadata key is not allowed for {source}: {path}"
                )
    errors.extend(_json_compatibility_errors(item["source_metadata"]))
    return errors


@dataclass(frozen=True)
class ObservationSelection:
    accepted: list[Mapping[str, object]]
    rejected: list[ObservationRejection]


@dataclass(frozen=True)
class ObservationRejection:
    index: int
    document_id: str
    reason: str
    errors: tuple[str, ...] = ()


class IncrementalObservationSelector:
    """Apply observation independence rules while retaining state across pages."""

    def __init__(self, *, max_items_per_author: int = 2) -> None:
        if max_items_per_author < 1:
            raise ValueError("max_items_per_author must be positive")
        self._max_items_per_author = max_items_per_author
        self._accepted: list[Mapping[str, object]] = []
        self._rejected: list[ObservationRejection] = []
        self._seen_document_ids: set[str] = set()
        self._seen_urls: set[str] = set()
        self._seen_fingerprints: set[str] = set()
        self._seen_threads: set[tuple[str, str]] = set()
        self._author_counts: Counter[tuple[str, str]] = Counter()
        self._next_index = 0

    def add(self, item: Mapping[str, object]) -> ObservationRejection | None:
        index = self._next_index
        self._next_index += 1
        document_id = str(item.get("document_id", f"<missing:{index}>"))
        validation_errors = validate_raw_source_item(item)
        if validation_errors:
            return self._reject(
                ObservationRejection(
                    index=index,
                    document_id=document_id,
                    reason="invalid_item",
                    errors=tuple(validation_errors),
                )
            )

        source = str(item["source"])
        source_url = str(item["source_url"])
        fingerprint = str(item["text_fingerprint"])
        thread_key = (source, str(item["thread_id"]))
        author_key = (source, str(item["author_hash"]))

        reason: str | None = None
        if document_id in self._seen_document_ids:
            reason = "duplicate_document_id"
        elif source_url in self._seen_urls:
            reason = "duplicate_source_url"
        elif fingerprint in self._seen_fingerprints:
            reason = "duplicate_text"
        elif thread_key in self._seen_threads:
            reason = "duplicate_thread"
        elif self._author_counts[author_key] >= self._max_items_per_author:
            reason = "author_quota_exceeded"

        if reason is not None:
            return self._reject(
                ObservationRejection(
                    index=index,
                    document_id=document_id,
                    reason=reason,
                )
            )

        copied = json.loads(json.dumps(item, ensure_ascii=False, allow_nan=False))
        self._accepted.append(copied)
        self._seen_document_ids.add(document_id)
        self._seen_urls.add(source_url)
        self._seen_fingerprints.add(fingerprint)
        self._seen_threads.add(thread_key)
        self._author_counts[author_key] += 1
        return None

    def _reject(self, rejection: ObservationRejection) -> ObservationRejection:
        self._rejected.append(rejection)
        return rejection

    def selection(self) -> ObservationSelection:
        accepted = json.loads(
            json.dumps(self._accepted, ensure_ascii=False, allow_nan=False)
        )
        return ObservationSelection(
            accepted=accepted,
            rejected=list(self._rejected),
        )


def select_observation_units(
    items: Sequence[Mapping[str, object]], *, max_items_per_author: int = 2
) -> ObservationSelection:
    """Apply deterministic independence and duplicate limits in input order."""
    selector = IncrementalObservationSelector(
        max_items_per_author=max_items_per_author
    )
    for item in items:
        selector.add(item)
    return selector.selection()
