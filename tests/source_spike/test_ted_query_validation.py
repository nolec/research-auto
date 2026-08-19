from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.source_spike.adapters.ted_http import (
    TedPage,
    TedTransportFailure,
    TedTransportSuccess,
)
from src.source_spike.ted_query_validation import (
    build_validation_receipt,
    build_query_set,
    execute_query_validation,
    main,
    run_query_validation,
    validate_validation_receipt,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/source-spike/ted-capacity.json"


def manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def success(page: int = 1) -> TedTransportSuccess:
    return TedTransportSuccess(
        TedPage((), 0, page, False, "a" * 64, None),
        http_attempt_count=1,
        retry_count=0,
        response_bytes=100,
    )


class RecordingTransport:
    def __init__(self, results: list[object] | None = None) -> None:
        self.results = iter(results or [success(), success(), success(), success()])
        self.calls: list[dict[str, object]] = []

    def validate_query_syntax(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return next(self.results)


def test_query_set_is_deterministic_and_contains_frozen_sort_order() -> None:
    first = build_query_set(manifest())
    second = build_query_set(manifest())

    assert first == second
    assert [candidate.stratum for candidate in first.candidates] == [
        "software_and_information_systems",
        "business_services",
        "health_and_social_services",
        "repair_and_maintenance_services",
    ]
    assert all(
        candidate.query.endswith(
            " SORT BY publication-date DESC, publication-number ASC"
        )
        for candidate in first.candidates
    )
    assert len(first.query_set_sha256) == 64
    assert all(len(candidate.query_sha256) == 64 for candidate in first.candidates)


def test_query_generator_rejects_sort_or_stratum_drift() -> None:
    sort_drift = manifest()
    sort_drift["sort"] = [
        {"field": "publication-number", "direction": "ASC"},
        {"field": "publication-date", "direction": "DESC"},
    ]
    with pytest.raises(ValueError, match="sort contract"):
        build_query_set(sort_drift)

    stratum_drift = manifest()
    strata = copy.deepcopy(stratum_drift["strata"])
    assert isinstance(strata, list)
    strata.pop()
    stratum_drift["strata"] = strata
    with pytest.raises(ValueError, match="strata contract"):
        build_query_set(stratum_drift)


def test_validation_checks_all_strata_with_separate_bounded_contract() -> None:
    transport = RecordingTransport()

    result = run_query_validation(manifest(), transport)

    assert result.status == "PASS"
    assert result.termination_reason == "validated"
    assert result.logical_requests == 4
    assert result.http_attempts == 4
    assert result.response_bytes == 400
    assert len(result.strata) == 4
    assert all(outcome.syntax_valid for outcome in result.strata)
    assert all("query" not in outcome.__dict__ for outcome in result.strata)
    assert all(call["max_http_attempts"] <= 2 for call in transport.calls)
    assert all(call["deadline_seconds"] <= 30 for call in transport.calls)
    assert all(call["max_response_bytes"] <= 2_097_152 for call in transport.calls)


def test_partial_failure_fails_closed_without_validating_later_strata() -> None:
    transport = RecordingTransport(
        [
            success(),
            TedTransportFailure("malformed_wrapper", 1, 0, 50),
            success(),
            success(),
        ]
    )

    result = run_query_validation(manifest(), transport)

    assert result.status == "FAIL"
    assert result.termination_reason == "malformed_wrapper"
    assert result.logical_requests == 2
    assert len(result.strata) == 2
    assert result.strata[-1].syntax_valid is False
    assert len(transport.calls) == 2


def test_partial_failure_receipt_preserves_original_error() -> None:
    result = run_query_validation(
        manifest(),
        RecordingTransport([TedTransportFailure("http_400", 1, 0, 222)]),
    )
    receipt = build_validation_receipt(
        result,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )

    assert receipt["status"] == "FAIL"
    assert receipt["termination_reason"] == "http_400"
    assert validate_validation_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        query_set_sha256=result.query_set_sha256,
    ) == []


def test_global_attempt_budget_stops_before_next_query() -> None:
    retried = TedTransportSuccess(
        TedPage((), 0, 1, False, "b" * 64, None),
        http_attempt_count=2,
        retry_count=1,
        response_bytes=100,
    )
    transport = RecordingTransport([retried, retried, retried, retried])

    result = run_query_validation(
        manifest(), transport, max_http_attempts=3
    )

    assert result.status == "FAIL"
    assert result.termination_reason == "attempt_budget_exhausted"
    assert result.logical_requests == 2
    assert result.http_attempts == 4
    assert len(transport.calls) == 2


def test_validation_receipt_is_exact_hash_bound_and_privacy_safe() -> None:
    manifest_value = manifest()
    result = run_query_validation(manifest_value, RecordingTransport())
    receipt = build_validation_receipt(
        result,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )

    assert validate_validation_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        query_set_sha256=result.query_set_sha256,
    ) == []
    serialized = json.dumps(receipt)
    assert "SORT BY" not in serialized
    assert "publication-date =" not in serialized
    assert receipt["request_contract"]["check_query_syntax"] is True
    assert receipt["request_contract"]["endpoint"] == "/v3/notices/search"
    assert receipt["retained_queries"] == 0
    assert receipt["retained_response_bodies"] == 0


def test_validation_receipt_rejects_incomplete_or_drifted_pass() -> None:
    result = run_query_validation(manifest(), RecordingTransport())
    receipt = build_validation_receipt(
        result,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )
    receipt["strata"].pop()
    receipt["request_contract"]["check_query_syntax"] = False

    errors = validate_validation_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        query_set_sha256=result.query_set_sha256,
    )

    assert any("strata" in error for error in errors)
    assert any("request contract" in error for error in errors)


def test_validation_receipt_rejects_stratum_hash_drift_and_budget_overrun() -> None:
    result = run_query_validation(manifest(), RecordingTransport())
    receipt = build_validation_receipt(
        result,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )
    receipt["strata"][0]["query_sha256"] = "f" * 64
    receipt["metrics"]["http_attempts"] = 999
    receipt["metrics"]["response_bytes"] = 999_999_999

    errors = validate_validation_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        query_set_sha256=result.query_set_sha256,
    )

    assert "receipt query set hash mismatch" in errors
    assert "receipt HTTP attempt budget exceeded" in errors
    assert "receipt response byte budget exceeded" in errors


def test_receipt_records_the_budget_actually_used_by_validation() -> None:
    result = run_query_validation(
        manifest(),
        RecordingTransport(),
        max_logical_requests=4,
        max_http_attempts=5,
        deadline_seconds=12,
        max_response_bytes=4096,
    )
    receipt = build_validation_receipt(
        result,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )

    assert receipt["budget"] == {
        "max_logical_requests": 4,
        "max_http_attempts": 5,
        "deadline_seconds": 12,
        "max_response_bytes": 4096,
    }


def test_pass_receipt_requires_measured_requests_bytes_and_clean_outcomes() -> None:
    result = run_query_validation(manifest(), RecordingTransport())
    receipt = build_validation_receipt(
        result,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )
    receipt["metrics"] = {
        "logical_requests": 0,
        "http_attempts": 0,
        "retries": 0,
        "response_bytes": 0,
    }
    receipt["strata"][0]["error_code"] = "fabricated"

    errors = validate_validation_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        query_set_sha256=result.query_set_sha256,
    )

    assert "PASS receipt logical request count mismatch" in errors
    assert "PASS receipt HTTP attempt arithmetic mismatch" in errors
    assert "PASS receipt requires positive response bytes" in errors
    assert "PASS receipt contains an outcome error" in errors


def test_execute_preflights_output_before_network_and_returns_code_3(tmp_path: Path) -> None:
    invalid_output = tmp_path / "not-a-directory"
    invalid_output.write_text("occupied", encoding="utf-8")
    transport = RecordingTransport()

    execution = execute_query_validation(
        manifest(),
        transport,
        output_root=invalid_output,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
    )

    assert execution.exit_code == 3
    assert execution.receipt_path is None
    assert transport.calls == []


def test_execute_writes_run_receipt_and_latest_without_query_text(tmp_path: Path) -> None:
    output = tmp_path / "query-validation"
    execution = execute_query_validation(
        manifest(),
        RecordingTransport(),
        output_root=output,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
    )

    assert execution.exit_code == 0
    assert execution.receipt_path == output / "runs" / execution.run_id / "receipt.json"
    assert execution.receipt_path.is_file()
    assert (output / "latest.json").is_file()
    persisted = execution.receipt_path.read_text(encoding="utf-8")
    assert "SORT BY" not in persisted
    assert "publication-date =" not in persisted
    assert not list(output.rglob("*.tmp"))


def test_cli_reports_aggregate_pass_without_query_text(tmp_path: Path, capsys) -> None:
    manifest_path = tmp_path / "manifest.json"
    feasibility_path = tmp_path / "feasibility.json"
    output = tmp_path / "output"
    manifest_value = manifest()
    feasibility_value = json.loads(
        (ROOT / "config/source-spike/feasibility/ted.json").read_text(encoding="utf-8")
    )
    manifest_path.write_text(json.dumps(manifest_value), encoding="utf-8")
    feasibility_path.write_text(json.dumps(feasibility_value), encoding="utf-8")

    code = main(
        [
            "--manifest", str(manifest_path),
            "--feasibility", str(feasibility_path),
            "--output-root", str(output),
        ],
        transport_factory=RecordingTransport,
    )

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["status"] == "PASS"
    assert captured.err == ""
    assert "SORT BY" not in captured.out
    assert "publication-date =" not in captured.out
    assert (output / "latest.json").is_file()
