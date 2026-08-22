import json
from pathlib import Path
from types import SimpleNamespace

from src.source_spike.ted_analysis import analysis_exit_code, qualify_ted_analysis, write_privacy_failure_receipt
from src.source_spike.adapters.base import CollectionStatus, SegmentResult, TerminationReason


def _result(items: list[dict[str, object]]) -> SimpleNamespace:
    return SimpleNamespace(items=items, status=CollectionStatus.SUCCESS, termination_reason=TerminationReason.TARGET_REACHED, accepted_item_count=len(items), manifest_hash="a" * 64, compliance_hash="b" * 64, segment_results=tuple(SegmentResult("cpv_stratum", value, 25, 25, 25, 25, 0) for value in ("software_and_information_systems", "business_services", "health_and_social_services", "repair_and_maintenance_services")))


def test_qualification_rejects_residual_contact_without_persisting_corpus(tmp_path: Path) -> None:
    value = qualify_ted_analysis(_result([]), expected_manifest_hash="a" * 64, expected_compliance_hash="b" * 64, secrets=())
    assert value["qualified"] is False
    receipt = write_privacy_failure_receipt(tmp_path, run_id="run-1", reason_code="residual_contact", aggregate_count=1, manifest_hash="a" * 64, provenance_hash="b" * 64, occurred_at="2026-08-22T00:00:00Z")
    assert receipt.is_file()
    assert not (tmp_path / "ted-analysis/runs/run-1/raw-source-items.jsonl").exists()
    assert "jane@example.com" not in receipt.read_text()


def test_analysis_exit_code_requires_collection_and_qualification_success() -> None:
    successful = SimpleNamespace(
        status=CollectionStatus.SUCCESS,
        termination_reason=TerminationReason.TARGET_REACHED,
    )
    prerequisite_failure = SimpleNamespace(
        status=CollectionStatus.FAILED,
        termination_reason=TerminationReason.PREREQUISITE_FAILED,
    )

    assert analysis_exit_code(successful, qualified=True) == 0
    assert analysis_exit_code(successful, qualified=False) == 2
    assert analysis_exit_code(prerequisite_failure, qualified=False) == 3
