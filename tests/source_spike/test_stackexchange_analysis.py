from __future__ import annotations

from types import SimpleNamespace
from types import MappingProxyType
from datetime import datetime, timezone

from src.source_spike.adapters.base import CollectionStatus, SegmentResult, TerminationReason
from src.source_spike.adapters.stackexchange import parse_stackexchange_question
from src.source_spike.stackexchange_analysis import preflight_capacity_receipt, qualify_stackexchange_analysis


def item(index: int, site: str) -> dict[str, object]:
    host = "softwareengineering.stackexchange.com" if site == "softwareengineering" else f"{site}.com"
    parsed = parse_stackexchange_question(
        {"question_id": index, "title": "Concrete operational problem", "body": "<p>This detailed question describes a repeatable technical problem needing a reliable solution.</p>", "creation_date": 1770000000, "link": f"https://{host}/questions/{index}/x", "owner": {"user_id": index}, "tags": ["testing"], "content_license": "CC BY-SA 4.0"},
        site=site, author_secret=b"s" * 32, run_id="run-1", adapter_version="0.1.0", collected_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
    )
    assert parsed.item is not None
    return dict(parsed.item)


def result(items):
    sites = ("stackoverflow", "superuser", "serverfault", "softwareengineering")
    return SimpleNamespace(
        status=CollectionStatus.SUCCESS, termination_reason=TerminationReason.TARGET_REACHED,
        accepted_item_count=100, items=items,
        segment_results=tuple(SegmentResult("site", site, 25, 25, 25, 25, 0) for site in sites),
        manifest_hash="a" * 64, compliance_hash="b" * 64,
    )


def test_qualification_requires_100_balanced_items_and_complete_license() -> None:
    sites = ("stackoverflow", "superuser", "serverfault", "softwareengineering")
    items = [item(offset + index, site) for offset, site in enumerate(sites) for index in range(25)]
    qualified = qualify_stackexchange_analysis(
        result(items), expected_manifest_hash="a" * 64, expected_compliance_hash="b" * 64
    )
    assert qualified["qualified"] is True
    items[0]["source_metadata"] = {}
    failed = qualify_stackexchange_analysis(
        result(items), expected_manifest_hash="a" * 64, expected_compliance_hash="b" * 64
    )
    assert failed["qualified"] is False
    assert "license_incomplete" in failed["failures"]


def test_qualification_rejects_invalid_raw_item_and_wrong_canonical_site_url() -> None:
    sites = ("stackoverflow", "superuser", "serverfault", "softwareengineering")
    items = [item(offset + index, site) for offset, site in enumerate(sites) for index in range(25)]
    items[0]["text"] = "short"
    items[25]["source_url"] = "https://stackoverflow.com/questions/999/wrong-site"

    qualified = qualify_stackexchange_analysis(
        result(items), expected_manifest_hash="a" * 64, expected_compliance_hash="b" * 64
    )

    assert qualified["qualified"] is False
    assert "raw_item_invalid" in qualified["failures"]
    assert "canonical_url_mismatch" in qualified["failures"]


def test_qualification_accepts_collection_result_frozen_item_representation() -> None:
    sites = ("stackoverflow", "superuser", "serverfault", "softwareengineering")
    items = [item(offset + index, site) for offset, site in enumerate(sites) for index in range(25)]
    frozen = [
        MappingProxyType({
            **value,
            "source_metadata": MappingProxyType({
                **value["source_metadata"],
                "tags": tuple(value["source_metadata"]["tags"]),
            }),
        })
        for value in items
    ]

    qualified = qualify_stackexchange_analysis(
        result(frozen), expected_manifest_hash="a" * 64, expected_compliance_hash="b" * 64
    )

    assert qualified["qualified"] is True


def test_analysis_preflight_rejects_missing_or_stale_capacity_receipt(tmp_path) -> None:
    expected = {
        "capacity_manifest_hash": "a" * 64,
        "analysis_manifest_hash": "b" * 64,
        "compliance_hash": "c" * 64,
        "filter_hash": "d" * 64,
    }
    assert preflight_capacity_receipt(tmp_path / "missing.json", **expected)
    receipt = {
        "schema_version": 1, "status": "PASS", "required_per_site": 38, "retained_items": 0,
        **expected,
        "sites": {site: {"fetched": 50, "processed": 45, "accepted": 38, "rejected": 7, "rejection_reason_counts": {"short_text": 7}, "capacity_pass": True} for site in ("stackoverflow", "superuser", "serverfault", "softwareengineering")},
        "transport": {"requests": 4, "attempts": 4, "retries": 0, "backoffs": 0, "quota_remaining": 250},
    }
    receipt["analysis_manifest_hash"] = "0" * 64
    path = tmp_path / "receipt.json"
    path.write_text(__import__("json").dumps(receipt))
    assert "analysis manifest hash mismatch" in preflight_capacity_receipt(path, **expected)
