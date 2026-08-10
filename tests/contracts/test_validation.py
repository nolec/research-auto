import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from src.contracts.validation import validate_contract


ROOT = Path(__file__).resolve().parents[2]


def load_schema(name: str) -> dict:
    with (ROOT / "schemas" / name).open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("source_url", "https://?missing-host"),
        ("source_url", "https://[broken"),
        ("source_url", "https://example.com:bad-port"),
        ("source_url", "ftp://example.com/file"),
        ("source_url", "https://example.com/has space"),
        ("published_at", "2026-02-31T10:00:00Z"),
    ],
)
def test_contract_validator_rejects_semantically_invalid_formats(
    field: str,
    invalid_value: str,
) -> None:
    evidence = {
        "evidence_id": "ev-001",
        "document_id": "doc-001",
        "source_url": "https://example.com/posts/1",
        "published_at": "2026-08-01T09:00:00Z",
        "author_hash": "sha256:001",
        "community": "community-1",
        "evidence_group_id": "group-1",
        "kind": "problem",
        "quote": "A source-backed problem statement.",
        "interpretation": "The actor reports a recurring problem.",
        "confidence": 0.9,
    }
    evidence[field] = invalid_value

    with pytest.raises(ValidationError):
        validate_contract(evidence, load_schema("evidence.schema.json"))
