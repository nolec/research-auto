from __future__ import annotations

import json
from types import SimpleNamespace

from src.source_spike.adapters.base import CollectionStatus, SegmentResult, TerminationReason
from src.source_spike.stackexchange_smoke import (
    build_qualification_report,
    exit_code_for_result,
    privacy_qualification_for_references,
    write_report,
)


def test_qualification_report_keeps_license_but_excludes_text_and_identity(tmp_path) -> None:
    marker = "CANARY-RAW-TEXT-OWNER"
    item = {"source_item_id":"1","community":"stackoverflow","source_url":"https://stackoverflow.com/questions/1/x","published_at":"2026-08-12T00:00:00Z","text_fingerprint":"a"*64,"text":marker,"source_metadata":{"content_license":"CC BY-SA 4.0"}}
    result = SimpleNamespace(run_id="run-1",status=CollectionStatus.SUCCESS,termination_reason=TerminationReason.TARGET_REACHED,manifest_version="0.1.0",manifest_hash="b"*64,compliance_hash="c"*64,adapter_version="0.1.0",accepted_item_count=1,rejected_item_count=0,fetched_item_count=1,processed_item_count=1,request_count=1,successful_request_count=1,http_attempt_count=1,retry_count=0,rate_limit_events=0,response_bytes=100,segment_results=(SegmentResult("site","stackoverflow",1,1,1,1,0),),invalid_items=(),transport_events=(),items=(item,),to_dict=lambda:{"started_at":"2026-08-12T00:00:00Z","finished_at":"2026-08-12T00:00:01Z"})
    report = build_qualification_report(result, quota_remaining=299)
    write_report(report, tmp_path / "qualification.json")
    serialized = (tmp_path / "qualification.json").read_text()
    assert marker not in serialized
    assert report["accepted_references"][0]["content_license"] == "CC BY-SA 4.0"
    assert report["license_completeness"] == "PASS"
    assert report["quota_remaining"] == 299


def test_qualification_report_rejects_vacuous_license_completeness() -> None:
    result = SimpleNamespace(
        run_id="run-empty",
        status=CollectionStatus.FAILED,
        termination_reason=TerminationReason.PREREQUISITE_FAILED,
        manifest_version="0.1.0",
        manifest_hash="b" * 64,
        compliance_hash="c" * 64,
        adapter_version="0.1.0",
        accepted_item_count=0,
        rejected_item_count=0,
        fetched_item_count=0,
        processed_item_count=0,
        request_count=0,
        successful_request_count=0,
        http_attempt_count=0,
        retry_count=0,
        rate_limit_events=0,
        response_bytes=0,
        segment_results=(),
        invalid_items=(),
        transport_events=(),
        items=(),
        to_dict=lambda: {
            "started_at": "2026-08-12T00:00:00Z",
            "finished_at": "2026-08-12T00:00:01Z",
        },
    )

    report = build_qualification_report(result, quota_remaining=None)

    assert report["license_completeness"] == "FAIL"


def test_privacy_qualification_requires_exact_safe_reference_shape() -> None:
    safe = {
        "source_item_id": "1",
        "site": "stackoverflow",
        "source_url": "https://stackoverflow.com/questions/1/x",
        "published_at": "2026-08-12T00:00:00Z",
        "text_fingerprint": "a" * 64,
        "content_license": "CC BY-SA 4.0",
    }

    assert privacy_qualification_for_references([safe]) == "PASS"
    assert privacy_qualification_for_references([{**safe, "display_name": "owner"}]) == "FAIL"
    assert privacy_qualification_for_references([{**safe, "text": "raw body"}]) == "FAIL"


def test_exit_codes_distinguish_success_partial_and_prerequisite() -> None:
    assert exit_code_for_result(SimpleNamespace(status=CollectionStatus.SUCCESS, termination_reason=TerminationReason.TARGET_REACHED)) == 0
    assert exit_code_for_result(SimpleNamespace(status=CollectionStatus.PARTIAL, termination_reason=TerminationReason.QUOTA_BUDGET_EXHAUSTED)) == 2
    assert exit_code_for_result(SimpleNamespace(status=CollectionStatus.FAILED, termination_reason=TerminationReason.PREREQUISITE_FAILED)) == 3
