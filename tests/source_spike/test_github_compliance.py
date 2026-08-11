from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[2]
RECORD_PATH = ROOT / "config" / "source-spike" / "compliance" / "github.json"
SCHEMA_PATH = ROOT / "schemas" / "source-compliance.schema.json"


def load_record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def test_github_compliance_record_satisfies_the_shared_contract() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    record = load_record()
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)

    assert not list(validator.iter_errors(record))
    assert record["source"] == "github"
    assert record["official_api"] is True
    assert record["decision"] == "conditional"
    assert record["commercial_use_risk"] == "medium"


def test_github_compliance_record_limits_access_retention_and_redistribution() -> None:
    record = load_record()

    assert "official rest api" in record["access_method"].casefold()
    assert "public" in record["access_method"].casefold()
    assert "environment" in record["authentication"].casefold()
    assert "local" in record["raw_text_retention"].casefold()
    assert "raw author" in record["raw_text_retention"].casefold()
    assert "derived" in record["redistribution"].casefold()
    assert "source url" in record["attribution"].casefold()
    assert "removal request" in record["deletion_handling"].casefold()
    assert "official rest api only" in record[
        "robots_or_automated_access_policy"
    ].casefold()


def test_github_compliance_record_cites_current_official_policy_surfaces() -> None:
    references = load_record()["source_references"]

    assert len(references) >= 5
    assert all(urlparse(url).scheme == "https" for url in references)
    assert all(urlparse(url).hostname == "docs.github.com" for url in references)
    assert any("/rest/issues/issues" in url for url in references)
    assert any("rate-limits-for-the-rest-api" in url for url in references)
    assert any("github-terms-of-service" in url for url in references)
    assert any("github-acceptable-use-policies" in url for url in references)
    assert any("github-general-privacy-statement" in url for url in references)
