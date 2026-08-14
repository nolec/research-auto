from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[2]
RECORD_PATH = ROOT / "config/source-spike/compliance/steam.json"


def load_record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def test_steam_compliance_is_conditional_and_high_risk() -> None:
    schema = json.loads((ROOT / "schemas/source-compliance.schema.json").read_text())
    record = load_record()

    assert not list(
        Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(record)
    )
    assert record["source"] == "steam"
    assert record["official_api"] is True
    assert record["decision"] == "conditional"
    assert record["commercial_use_risk"] == "high"


def test_steam_compliance_excludes_identity_html_and_raw_redistribution() -> None:
    record = load_record()

    assert "user reviews json endpoint" in record["access_method"].casefold()
    assert "html scraping" in record["access_method"].casefold()
    assert "raw steamid" in record["raw_text_retention"].casefold()
    assert "local-only" in record["raw_text_retention"].casefold()
    assert "review text is not redistributed" in record["redistribution"].casefold()
    assert "marketing without reviewer permission" in record["redistribution"].casefold()
    assert "do not scrape steam html" in record["robots_or_automated_access_policy"].casefold()


def test_steam_compliance_cites_only_official_https_surfaces() -> None:
    references = load_record()["source_references"]
    allowed_hosts = {
        "partner.steamgames.com", "steamcommunity.com", "store.steampowered.com"
    }

    assert len(references) >= 6
    assert all(urlparse(value).scheme == "https" for value in references)
    assert all(urlparse(value).hostname in allowed_hosts for value in references)
    assert any("/doc/store/getreviews" in value for value in references)
    assert any("/dev/apiterms" in value for value in references)
    assert any("privacy_agreement" in value for value in references)
