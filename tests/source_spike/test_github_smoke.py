from __future__ import annotations

import json
from types import SimpleNamespace

from src.source_spike.adapters.base import CollectionStatus, SegmentResult, TerminationReason
from src.source_spike.github_smoke import build_qualification_report, write_report
from src.source_spike.github_smoke import exit_code_for_result


def test_qualification_report_excludes_text_identity_and_secrets(tmp_path) -> None:
    marker = "CANARY-TOKEN-USERNAME-BODY"
    item = {
        "source_item_id": "1",
        "source_url": "https://github.com/example/project/issues/1",
        "published_at": "2026-08-12T00:00:00Z",
        "text_fingerprint": "a" * 64,
        "text": marker,
        "title": marker,
    }
    result = SimpleNamespace(
        run_id="run-1", status=CollectionStatus.SUCCESS,
        termination_reason=TerminationReason.TARGET_REACHED,
        manifest_version="0.2.0", manifest_hash="b" * 64,
        compliance_hash="c" * 64, adapter_version="0.2.0",
        accepted_item_count=1, rejected_item_count=0, fetched_item_count=1,
        processed_item_count=1, request_count=1, successful_request_count=1,
        http_attempt_count=1, retry_count=0, rate_limit_events=0,
        segment_results=(SegmentResult("repository", "example/project", 1, 1, 1, 1, 0),),
        invalid_items=(), transport_events=(), items=(item,),
        to_dict=lambda: {"started_at": "2026-08-12T00:00:00Z", "finished_at": "2026-08-12T00:00:01Z"},
    )

    report = build_qualification_report(result)
    destination = tmp_path / "qualification.json"
    write_report(report, destination)
    serialized = destination.read_text()

    assert marker not in serialized
    assert set(report["accepted_references"][0]) == {
        "source_item_id", "source_url", "published_at", "text_fingerprint"
    }
    assert "items" not in report
    assert json.loads(serialized)["privacy_qualification"] == "PASS"


def test_prerequisite_result_uses_exit_code_three() -> None:
    result = SimpleNamespace(
        status=CollectionStatus.FAILED,
        termination_reason=TerminationReason.PREREQUISITE_FAILED,
    )
    assert exit_code_for_result(result) == 3


def test_report_replaces_unrecognized_event_strings_with_unknown() -> None:
    event = {
        "sequence": 1, "category": "CANARY", "attempt": 1,
        "status_code": 429, "retryable": True,
        "rate_limit": {
            "limit": 60, "remaining": 0, "reset_at": 1,
            "resource": "CANARY", "retry_after_seconds": 1,
        },
    }
    from src.source_spike.github_smoke import _safe_transport_event

    safe = _safe_transport_event(event)
    assert safe["category"] == "unknown"
    assert safe["rate_limit"]["resource"] == "unknown"
