from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.source_spike.adapters.base import CollectionStatus, TerminationReason
from src.source_spike.adapters.steam import SteamReviewAdapter, SteamReviewPage, parse_steam_review
from src.source_spike.raw_items import author_hash, validate_raw_source_item
from src.source_spike.steam_smoke_manifest import validate_steam_smoke_manifest


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/source_spike/steam/reviews.json"
SECRET = b"steam-review-author-secret-32-bytes"
NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)
AFTER = datetime(2026, 5, 16, tzinfo=timezone.utc)


def fixtures(): return json.loads(FIXTURE.read_text())


def parse(value, appid=730):
    return parse_steam_review(value, appid=appid, app_name="Example App",
        author_secret=SECRET, run_id="run-1", adapter_version="0.1.0",
        collected_at=NOW, published_after=AFTER, published_before=NOW)


def test_parser_retains_review_context_without_raw_identity_or_play_history() -> None:
    result = parse(fixtures()[0])
    assert result.rejection is None and result.item is not None
    item = result.item
    assert validate_raw_source_item(item) == []
    assert item["source_item_id"] == "730:1001"
    assert item["author_hash"] == author_hash("steam", "76561190000000001", SECRET)
    assert item["source_metadata"] == {"received_for_free": False, "steam_purchase": True, "voted_up": False, "written_during_early_access": False}
    serialized = json.dumps(item)
    assert "76561190000000001" not in serialized
    assert "playtime" not in serialized


def test_parser_rejects_missing_body_short_text_and_missing_id() -> None:
    assert [parse(value).rejection.error_code for value in fixtures()[2:]] == [
        "missing_body", "short_text", "missing_item_id"
    ]


class FixtureTransport:
    def __init__(self, pages): self.pages, self.calls = pages, []
    def fetch_reviews(self, appid, *, cursor, **kwargs):
        self.calls.append((appid, cursor))
        return self.pages.get((appid, cursor), SteamReviewPage((), 0, None))


def manifest():
    manifest = json.loads((ROOT / "config/source-spike/steam-smoke.json").read_text())
    compliance = json.loads((ROOT / "config/source-spike/compliance/steam.json").read_text())
    return manifest, compliance


def review(index, appid, author=None):
    return {"recommendationid":str(index),"author":{"steamid":author or str(index)},
        "review":f"A concrete recurring application failure number {index} prevents the customer from completing the expected workflow.",
        "timestamp_created":1786320000,"timestamp_updated":1786320000,
        "voted_up":False,"votes_up":1,"comment_count":0,"steam_purchase":True,
        "received_for_free":False,"written_during_early_access":False}


def test_fixture_collection_reaches_global_and_application_quotas() -> None:
    config, compliance = manifest(); pages = {}
    for app in config["applications"]:
        appid = app["appid"]
        pages[(appid,"*")] = SteamReviewPage([review(appid*10+i, appid) for i in range(4)], 800, "next")
    result = SteamReviewAdapter(FixtureTransport(pages), author_secret=SECRET,
        compliance_record=compliance, manifest_validator=validate_steam_smoke_manifest,
        clock=lambda: NOW).collect(config, 10, run_id="run-1", manifest_version="0.1.0")
    assert result.status is CollectionStatus.SUCCESS
    assert result.termination_reason is TerminationReason.TARGET_REACHED
    assert [x.accepted_item_count for x in result.segment_results] == [3,3,2,2]
    assert [x.processed_item_count for x in result.segment_results] == [3,3,2,2]
    assert result.fetched_item_count == 16
    assert result.accepted_item_count == 10


def test_fixture_collection_preserves_rejections_and_paginates_by_valid_count() -> None:
    config, compliance = manifest(); first = config["applications"][0]; appid = first["appid"]
    pages = {(appid,"*"):SteamReviewPage([fixtures()[2], review(9001,appid,"same")], 400, "next"),
             (appid,"next"):SteamReviewPage([review(9002,appid,"same"),review(9003,appid,"same"),review(9004,appid,"other")], 500, None)}
    result = SteamReviewAdapter(FixtureTransport(pages), author_secret=SECRET,
        compliance_record=compliance, manifest_validator=validate_steam_smoke_manifest,
        clock=lambda: NOW).collect(config, 10, run_id="run-1", manifest_version="0.1.0")
    assert result.status is CollectionStatus.PARTIAL
    assert result.termination_reason is TerminationReason.SOURCE_EXHAUSTED
    assert [x.error_code for x in result.invalid_items] == ["missing_body", "author_quota_exceeded"]
    assert result.segment_results[0].accepted_item_count == 3
    assert result.processed_item_count == result.accepted_item_count + result.rejected_item_count


def test_fixture_collection_stops_before_transport_after_deadline() -> None:
    config, compliance = manifest()
    times = iter((NOW, NOW.replace(minute=2), NOW.replace(minute=2)))

    class Transport:
        calls = 0
        def fetch_reviews(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("transport called after deadline")

    transport = Transport()
    result = SteamReviewAdapter(transport, author_secret=SECRET,
        compliance_record=compliance, manifest_validator=validate_steam_smoke_manifest,
        clock=lambda: next(times)).collect(config, 10, run_id="run-1", manifest_version="0.1.0")
    assert result.status is CollectionStatus.FAILED
    assert result.termination_reason is TerminationReason.SMOKE_DEADLINE_EXHAUSTED
    assert transport.calls == 0
