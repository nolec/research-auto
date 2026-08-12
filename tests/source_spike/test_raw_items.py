from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER
from src.source_spike.raw_items import (
    IncrementalObservationSelector,
    author_hash,
    canonical_text_fingerprint,
    normalize_text,
    select_observation_units,
    validate_raw_source_item,
)


ROOT = Path(__file__).resolve().parents[2]


def load_schema() -> dict:
    return json.loads(
        (ROOT / "schemas" / "raw-source-item.schema.json").read_text(encoding="utf-8")
    )


def make_item(suffix: str = "1", **overrides: object) -> dict:
    text = "A concrete problem statement with enough detail to be useful for evidence."
    item = {
        "document_id": f"github:{suffix}",
        "source": "github",
        "source_item_id": suffix,
        "source_url": f"https://github.com/example/project/issues/{suffix}",
        "item_type": "issue",
        "author_hash": f"{int(suffix):064x}",
        "community": "example/project",
        "thread_id": suffix,
        "parent_id": None,
        "title": "Concrete issue title",
        "text": text,
        "text_fingerprint": canonical_text_fingerprint(text),
        "text_length": len(text),
        "original_text_length": len(text),
        "text_truncated": False,
        "published_at": "2026-08-11T00:00:00Z",
        "updated_at": None,
        "language": "en",
        "engagement": {"comments": 3, "score": 4},
        "source_metadata": {"state": "open"},
        "collected_at": "2026-08-11T01:00:00Z",
        "collector_version": "github-v1",
        "fetch_run_id": "run-20260811",
    }
    item.update(overrides)
    if "text" in overrides:
        overridden_text = str(item["text"])
        if "text_fingerprint" not in overrides:
            item["text_fingerprint"] = canonical_text_fingerprint(overridden_text)
        if "text_length" not in overrides:
            item["text_length"] = len(overridden_text)
        if "original_text_length" not in overrides:
            item["original_text_length"] = len(overridden_text)
    return item


def validator() -> Draft202012Validator:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


def test_raw_source_item_contract_accepts_a_top_level_document() -> None:
    assert not list(validator().iter_errors(make_item()))


def test_raw_source_item_rejects_replies_short_text_and_raw_author_identity() -> None:
    reply = make_item(parent_id="parent-1")
    assert list(validator().iter_errors(reply))

    short = make_item(text="too short", text_length=9)
    assert list(validator().iter_errors(short))

    raw_author = make_item(author_username="alice")
    assert list(validator().iter_errors(raw_author))


def test_raw_source_item_allows_signed_score_but_nonnegative_counts() -> None:
    negative_score = make_item(engagement={"score": -2, "comments": 0})
    assert not list(validator().iter_errors(negative_score))

    negative_count = make_item(engagement={"comments": -1})
    assert list(validator().iter_errors(negative_count))


def test_semantic_validation_recomputes_identity_length_and_fingerprint() -> None:
    manipulated = make_item(
        document_id="wrong:identity",
        text_fingerprint="f" * 64,
        text_length=999,
    )

    errors = validate_raw_source_item(manipulated)

    assert "document_id must equal source:source_item_id (github:1)" in errors
    assert "text_length must equal the stored normalized text length" in errors
    assert "text_fingerprint does not match normalized text" in errors


def test_semantic_validation_rejects_blank_or_unnormalized_text() -> None:
    blank = make_item(
        text=" " * 40,
        text_length=40,
        original_text_length=40,
        text_fingerprint=canonical_text_fingerprint(" " * 40),
    )
    assert "text must contain at least 40 normalized characters" in validate_raw_source_item(blank)

    unnormalized = make_item(text="A   concrete problem statement with enough detail to remain useful.")
    assert "text must be normalized before storage" in validate_raw_source_item(unnormalized)


def test_semantic_validation_rejects_nested_identity_metadata() -> None:
    item = make_item(source_metadata={"request": {"author_username": "alice"}})

    assert validate_raw_source_item(item) == [
        "source_metadata contains forbidden identity key: request.author_username"
    ]


def test_semantic_validation_canonicalizes_camel_case_identity_keys() -> None:
    item = make_item(
        source_metadata={
            "request": {
                "authorId": "123",
                "authorDisplayName": "Alice",
                "profileUrl": "https://example.com/alice",
                "userId": "456",
            }
        }
    )

    assert validate_raw_source_item(item) == [
        "source_metadata contains forbidden identity key: request.authorId",
        "source_metadata contains forbidden identity key: request.authorDisplayName",
        "source_metadata contains forbidden identity key: request.profileUrl",
        "source_metadata contains forbidden identity key: request.userId",
    ]


def test_semantic_validation_rejects_metadata_outside_source_allowlist() -> None:
    candidate_keys = [
        "authorChannelId",
        "authorProfileImageUrl",
        "authorFullname",
        "owner",
        "login",
        "creatorId",
        "milestone",
    ]

    for key in candidate_keys:
        errors = validate_raw_source_item(make_item(source_metadata={key: "private"}))
        assert errors, f"metadata key unexpectedly allowed: {key}"


def test_semantic_validation_accepts_only_known_safe_metadata_for_each_source() -> None:
    safe_cases = [
        ("github", {"state": "open", "locked": False}),
        ("stackexchange", {"tags": ["python"], "is_answered": True}),
        ("steam", {"steam_purchase": True, "received_for_free": False}),
        ("youtube", {"video_id": "video-1", "can_reply": True}),
        ("reddit", {"subreddit": "smallbusiness", "over_18": False}),
        ("hackernews", {"type": "story", "dead": False}),
    ]

    for source, metadata in safe_cases:
        item = make_item(
            source=source,
            document_id=f"{source}:1",
            source_metadata=metadata,
        )
        assert not validate_raw_source_item(item)


def test_semantic_validation_requires_strict_json_metadata() -> None:
    cases = [
        ({"payload": b"bytes"}, "source_metadata contains non-JSON value at payload: bytes"),
        ({"payload": (1, 2)}, "source_metadata contains non-JSON sequence at payload: tuple"),
        ({1: "value"}, "source_metadata contains non-string key at 1"),
        ({"score": float("nan")}, "source_metadata contains non-finite number at score"),
        ({"score": float("inf")}, "source_metadata contains non-finite number at score"),
    ]

    for metadata, expected in cases:
        assert expected in validate_raw_source_item(make_item(source_metadata=metadata))


def test_text_normalization_preserves_content_but_collapses_spacing() -> None:
    assert normalize_text("  A\tproblem\n\nwith   spacing  ") == "A problem with spacing"


def test_text_fingerprint_ignores_unicode_case_and_spacing_variation() -> None:
    left = canonical_text_fingerprint("Ｃｏｓｔ   Problem")
    right = canonical_text_fingerprint("cost problem")

    assert left == right
    assert len(left) == 64


def test_author_hash_is_secret_keyed_and_source_scoped() -> None:
    secret = b"x" * 32
    first = author_hash("github", "alice", secret)
    repeated = author_hash("github", "alice", secret)
    other_source = author_hash("reddit", "alice", secret)

    assert first == repeated
    assert first != other_source
    assert "alice" not in first
    assert len(first) == 64


def test_author_hash_rejects_a_low_entropy_secret() -> None:
    try:
        author_hash("github", "alice", b"short")
    except ValueError as error:
        assert str(error) == "author hash secret must contain at least 32 bytes"
    else:
        raise AssertionError("weak secret was accepted")


def test_observation_selection_rejects_duplicate_content_url_and_thread() -> None:
    first = make_item("1")
    same_url = make_item("2", source_url=first["source_url"])
    same_text = make_item("3")
    same_thread = make_item(
        "4",
        thread_id=first["thread_id"],
        text="A different concrete problem statement that is long enough to retain.",
    )
    same_thread["text_fingerprint"] = canonical_text_fingerprint(same_thread["text"])

    result = select_observation_units([first, same_url, same_text, same_thread])

    assert [item["document_id"] for item in result.accepted] == ["github:1"]
    assert [(entry.document_id, entry.reason) for entry in result.rejected] == [
        ("github:2", "duplicate_source_url"),
        ("github:3", "duplicate_text"),
        ("github:4", "duplicate_thread"),
    ]


def test_observation_selection_caps_each_author_at_two_items() -> None:
    shared_author = "a" * 64
    items = [
        make_item(
            str(index),
            author_hash=shared_author,
            text=f"Distinct concrete problem statement number {index} with enough useful detail.",
        )
        for index in range(1, 4)
    ]
    for item in items:
        item["text_fingerprint"] = canonical_text_fingerprint(item["text"])

    result = select_observation_units(items)

    assert [item["document_id"] for item in result.accepted] == ["github:1", "github:2"]
    assert [(entry.document_id, entry.reason) for entry in result.rejected] == [
        ("github:3", "author_quota_exceeded")
    ]


def test_incremental_selector_keeps_duplicate_state_between_add_calls() -> None:
    selector = IncrementalObservationSelector()
    first = make_item("1")
    duplicate_url = make_item("2", source_url=first["source_url"])

    assert selector.add(first) is None
    rejection = selector.add(duplicate_url)

    assert rejection is not None
    assert (rejection.index, rejection.document_id, rejection.reason) == (
        1,
        "github:2",
        "duplicate_source_url",
    )
    assert [item["document_id"] for item in selector.selection().accepted] == [
        "github:1"
    ]


def test_incremental_selector_keeps_author_quota_between_add_calls() -> None:
    selector = IncrementalObservationSelector(max_items_per_author=2)
    shared_author = "a" * 64
    items = [
        make_item(
            str(index),
            author_hash=shared_author,
            text=f"Distinct incremental problem number {index} with sufficient evidence detail.",
        )
        for index in range(1, 4)
    ]
    for item in items:
        item["text_fingerprint"] = canonical_text_fingerprint(item["text"])

    assert selector.add(items[0]) is None
    assert selector.add(items[1]) is None
    rejection = selector.add(items[2])

    assert rejection is not None
    assert rejection.reason == "author_quota_exceeded"
    assert [entry.index for entry in selector.selection().rejected] == [2]


def test_observation_selection_preserves_every_duplicate_id_rejection() -> None:
    item = make_item("1")

    result = select_observation_units([item, item, item])

    assert [(entry.index, entry.document_id, entry.reason) for entry in result.rejected] == [
        (1, "github:1", "duplicate_document_id"),
        (2, "github:1", "duplicate_document_id"),
    ]


def test_observation_selection_rejects_semantically_invalid_items() -> None:
    invalid = make_item("1", text_fingerprint="f" * 64)

    result = select_observation_units([invalid])

    assert result.accepted == []
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "invalid_item"
    assert "text_fingerprint does not match normalized text" in result.rejected[0].errors


def test_observation_selection_copies_accepted_items() -> None:
    item = make_item("1")
    result = select_observation_units([item])

    item["text"] = "mutated after validation"
    item["source_metadata"]["state"] = "closed"

    assert result.accepted[0]["text"] != item["text"]
    assert result.accepted[0]["source_metadata"] == {"state": "open"}


def test_semantic_validation_enforces_truncation_boundary() -> None:
    text = "x" * 20000
    valid = make_item(
        text=text,
        text_truncated=True,
        original_text_length=20001,
    )
    assert not validate_raw_source_item(valid)

    invalid = make_item(
        text=text,
        text_truncated=True,
        original_text_length=20000,
    )
    assert validate_raw_source_item(invalid) == [
        "truncated text must store 20000 characters and a larger original length"
    ]
