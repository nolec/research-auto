from datetime import datetime, timezone

from src.source_spike.adapters.ted import parse_ted_notice


def test_parse_ted_notice_builds_canonical_item_and_order_independent_buyer_hash() -> None:
    payload = {"publication-number": "123456-2026", "notice-identifier": "notice-1", "procedure-identifier": "procedure-1", "publication-date": "2026-08-01+00:00", "notice-type": "cn-standard", "form-type": "competition", "classification-cpv": ["48000000"], "buyer-identifier": [" buyer-b ", "buyer-a", "buyer-a"], "notice-title": {"eng": "Software platform procurement"}, "description-proc": {"eng": "A detailed procurement notice for a software platform and related implementation services."}}
    kwargs = dict(stratum="software_and_information_systems", author_secret=b"x" * 32, run_id="run-1", adapter_version="0.1.0", collected_at=datetime(2026, 8, 22, tzinfo=timezone.utc))
    first = parse_ted_notice(payload, **kwargs)
    payload["buyer-identifier"] = ["buyer-a", "buyer-b"]
    second = parse_ted_notice(payload, **kwargs)
    assert first.rejection is None
    assert first.item is not None and second.item is not None
    assert first.item["item_type"] == "notice"
    assert first.item["source_url"] == "https://ted.europa.eu/en/notice/-/detail/123456-2026"
    assert first.item["author_hash"] == second.item["author_hash"]
    assert "buyer-a" not in str(first.item)
