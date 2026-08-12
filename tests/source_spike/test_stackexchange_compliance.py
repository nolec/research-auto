from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[2]


def test_stackexchange_compliance_is_conditional_and_attribution_bound() -> None:
    record = json.loads(
        (ROOT / "config/source-spike/compliance/stackexchange.json").read_text(encoding="utf-8")
    )
    schema = json.loads((ROOT / "schemas/source-compliance.schema.json").read_text())
    assert not list(Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(record))
    assert record["source"] == "stackexchange"
    assert record["official_api"] is True
    assert record["decision"] == "conditional"
    assert "attribution" in record["attribution"].casefold()
    assert "content_license" in record["attribution"]
    assert "raw owner" in record["raw_text_retention"].casefold()
    refs = record["source_references"]
    assert len(refs) >= 6
    assert all(urlparse(value).scheme == "https" for value in refs)
