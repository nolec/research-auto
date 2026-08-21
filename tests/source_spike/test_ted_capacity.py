from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.source_spike.ted_capacity import (
    TedPaginationState,
    TedRunBudget,
    TedSelectionState,
    build_capacity_receipt,
    build_stratum_summary,
    measure_notice,
    validate_capacity_receipt,
    validate_query_validation_preflight,
)


ROOT = Path(__file__).resolve().parents[2]


def test_capacity_preflight_requires_matching_four_stratum_pass_receipt() -> None:
    from src.source_spike.adapters.ted_http import TedPage, TedTransportSuccess
    from src.source_spike.ted_query_validation import build_validation_receipt, run_query_validation

    class Transport:
        def validate_query_syntax(self, **kwargs):
            return TedTransportSuccess(TedPage((), 0, 1, False, "d" * 64, None), 1, 0, 10)

    manifest = json.loads((ROOT / "config/source-spike/ted-capacity.json").read_text())
    result = run_query_validation(manifest, Transport())
    receipt = build_validation_receipt(
        result,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="c" * 64,
        compliance_hash="e" * 64,
    )

    assert validate_query_validation_preflight(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="c" * 64,
        compliance_hash="e" * 64,
        query_set_sha256=result.query_set_sha256,
    ) == []

    receipt["status"] = "FAIL"
    receipt["strata"].pop()
    errors = validate_query_validation_preflight(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="c" * 64,
        compliance_hash="e" * 64,
        query_set_sha256=result.query_set_sha256,
    )
    assert "query validation receipt is not PASS" in errors
    assert "query validation receipt strata mismatch" in errors


def test_capacity_preflight_rejects_historical_receipt_versions() -> None:
    from src.source_spike.adapters.ted_http import TedPage, TedTransportSuccess
    from src.source_spike.ted_query_validation import build_validation_receipt, run_query_validation

    class Transport:
        def validate_query_syntax(self, **kwargs):
            return TedTransportSuccess(TedPage((), 0, 1, False, "d" * 64, None), 1, 0, 10)

    manifest = json.loads((ROOT / "config/source-spike/ted-capacity.json").read_text())
    result = run_query_validation(manifest, Transport())
    receipt = build_validation_receipt(
        result,
        run_id="12345678-1234-4234-8234-123456789abc",
        started_at="2026-08-18T09:00:00Z",
        finished_at="2026-08-18T09:00:01Z",
        elapsed_ms=1000,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="c" * 64,
        compliance_hash="e" * 64,
    )
    receipt["validation_contract_version"] = "1.0.0"
    receipt["generator_version"] = "1.0.0"

    errors = validate_query_validation_preflight(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="c" * 64,
        compliance_hash="e" * 64,
        query_set_sha256=result.query_set_sha256,
    )

    assert "capacity preflight requires TED query contract 1.1.0" in errors


def valid_notice(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "notice-identifier": "notice-1",
        "procedure-identifier": "procedure-1",
        "buyer-identifier": "buyer-1",
        "publication-date": "20260601",
        "notice-type": "cn-standard",
        "form-type": "competition",
        "classification-cpv": ["48000000"],
        "description-proc": "Usable description",
    }
    value.update(overrides)
    return value


def selection_state() -> TedSelectionState:
    return TedSelectionState(
        published_from="20260520",
        published_before="20260818",
        allowed_notice_types=frozenset({"cn-standard", "cn-social"}),
        form_type="competition",
        cpv_prefix="48",
        max_items_per_buyer=2,
    )


def test_measurement_normalizes_scalar_list_and_language_map_in_input_order() -> None:
    measurement = measure_notice(
        {
            "notice-identifier": " notice-1 ",
            "procedure-identifier": ["procedure-1"],
            "buyer-identifier": ["buyer-1", "", "buyer-2"],
            "publication-date": "20260601",
            "notice-type": ["cn-standard"],
            "form-type": "competition",
            "classification-cpv": ["48000000", "48100000"],
            "notice-title": {
                "eng": ["First title", ""],
                "fra": "Deuxième titre",
            },
            "description-proc": {"eng": ["Description"]},
            "change-notice-version-identifier": [],
        }
    )

    assert measurement.processed == 1
    assert measurement.notice_id == "notice-1"
    assert measurement.procedure_id == "procedure-1"
    assert measurement.buyer_ids == ("buyer-1", "buyer-2")
    assert measurement.cpv_codes == ("48000000", "48100000")
    assert measurement.text_values == ("First title", "Deuxième titre", "Description")
    assert measurement.procedure_present is True
    assert measurement.buyer_present is True
    assert measurement.text_present is True
    assert measurement.shape_valid is True
    assert measurement.rejection_reason is None


def test_invalid_shape_is_processed_and_does_not_coerce_boolean_or_number() -> None:
    measurement = measure_notice(
        {
            "notice-identifier": "notice-2",
            "procedure-identifier": True,
            "buyer-identifier": 123,
            "notice-title": {"eng": {"nested": "not allowed"}},
        }
    )

    assert measurement.processed == 1
    assert measurement.procedure_id is None
    assert measurement.buyer_ids == ()
    assert measurement.text_values == ()
    assert measurement.procedure_present is False
    assert measurement.buyer_present is False
    assert measurement.text_present is False
    assert measurement.shape_valid is False
    assert measurement.rejection_reason == "invalid_field_shape"


def test_missing_fields_remain_in_measurement_completeness_denominator() -> None:
    measurement = measure_notice({"notice-identifier": "notice-3"})

    assert measurement.processed == 1
    assert measurement.notice_id == "notice-3"
    assert measurement.procedure_present is False
    assert measurement.buyer_present is False
    assert measurement.text_present is False
    assert measurement.shape_valid is True
    assert measurement.rejection_reason is None


def test_invalid_field_does_not_erase_other_completeness_observations() -> None:
    measurement = measure_notice(
        {
            "notice-identifier": "notice-4",
            "procedure-identifier": "procedure-4",
            "buyer-identifier": "buyer-4",
            "notice-title": {"eng": {"nested": "not allowed"}},
            "description-proc": "Usable description",
        }
    )

    assert measurement.shape_valid is False
    assert measurement.rejection_reason == "invalid_field_shape"
    assert measurement.procedure_present is True
    assert measurement.buyer_present is True
    assert measurement.text_present is True


@pytest.mark.parametrize(
    "field,values",
    (
        ("notice-identifier", ["notice-1", "notice-2"]),
        ("procedure-identifier", ["procedure-1", "procedure-2"]),
        ("publication-date", ["20260601", "20260602"]),
        ("notice-type", ["cn-standard", "cn-social"]),
        ("form-type", ["competition", "planning"]),
        ("procedure-identifier", ["", "procedure-1"]),
    ),
)
def test_single_value_fields_reject_multiple_values(field: str, values: list[str]) -> None:
    measurement = measure_notice({field: values})

    assert measurement.shape_valid is False
    assert measurement.rejection_reason == "invalid_field_shape"


def test_invalid_single_field_does_not_count_as_complete_or_erase_other_fields() -> None:
    measurement = measure_notice(
        {
            "procedure-identifier": ["procedure-1", "procedure-2"],
            "buyer-identifier": "buyer-1",
            "description-proc": "Usable description",
        }
    )

    assert measurement.procedure_id is None
    assert measurement.procedure_present is False
    assert measurement.buyer_present is True
    assert measurement.text_present is True


@pytest.mark.parametrize(
    "payload,reason",
    (
        ({"procedure-identifier": ["p1", "p2"]}, "invalid_field_shape"),
        ({"notice-identifier": None}, "missing_notice_id"),
        ({"procedure-identifier": None}, "missing_procedure_id"),
        ({"buyer-identifier": None}, "missing_buyer_id"),
        ({"description-proc": None}, "missing_text"),
        ({"publication-date": "20260818"}, "outside_window"),
        ({"publication-date": "20260699"}, "outside_window"),
        ({"notice-type": "pin-only"}, "wrong_notice_scope"),
        ({"classification-cpv": ["79000000"]}, "wrong_cpv_stratum"),
        ({"classification-cpv": ["48evil"]}, "wrong_cpv_stratum"),
        ({"change-notice-version-identifier": ["change-1"]}, "change_notice"),
    ),
)
def test_selection_rejects_ineligible_measurements_with_stable_reason(
    payload: dict[str, object], reason: str
) -> None:
    decision = selection_state().select(measure_notice(valid_notice(**payload)))

    assert decision.accepted is False
    assert decision.rejection_reason == reason


def test_selection_accepts_ted_publication_date_with_numeric_offset() -> None:
    decision = selection_state().select(
        measure_notice(valid_notice(**{"publication-date": "2026-06-01+02:00"}))
    )

    assert decision.accepted is True
    assert decision.rejection_reason is None


@pytest.mark.parametrize("value", ("2026-06-01+99:99", "2026-06-01+24:00"))
def test_selection_rejects_invalid_numeric_offset(value: str) -> None:
    decision = selection_state().select(
        measure_notice(valid_notice(**{"publication-date": value}))
    )

    assert decision.accepted is False
    assert decision.rejection_reason == "outside_window"


def test_selection_deduplicates_notice_then_procedure_in_observation_order() -> None:
    state = selection_state()

    first = state.select(measure_notice(valid_notice()))
    duplicate_notice = state.select(
        measure_notice(valid_notice(**{"procedure-identifier": "procedure-2"}))
    )
    duplicate_procedure = state.select(
        measure_notice(valid_notice(**{"notice-identifier": "notice-2"}))
    )

    assert first.accepted is True
    assert duplicate_notice.rejection_reason == "duplicate_notice"
    assert duplicate_procedure.rejection_reason == "duplicate_procedure"


def test_buyer_limit_rejects_multi_buyer_candidate_without_consuming_other_buyer() -> None:
    state = selection_state()
    for index in range(2):
        assert state.select(
            measure_notice(
                valid_notice(
                    **{
                        "notice-identifier": f"notice-a-{index}",
                        "procedure-identifier": f"procedure-a-{index}",
                    }
                )
            )
        ).accepted

    rejected = state.select(
        measure_notice(
            valid_notice(
                **{
                    "notice-identifier": "notice-ab",
                    "procedure-identifier": "procedure-ab",
                    "buyer-identifier": ["buyer-1", "buyer-2"],
                }
            )
        )
    )
    assert rejected.rejection_reason == "buyer_limit_exceeded"

    for index in range(2):
        assert state.select(
            measure_notice(
                valid_notice(
                    **{
                        "notice-identifier": f"notice-b-{index}",
                        "procedure-identifier": f"procedure-b-{index}",
                        "buyer-identifier": "buyer-2",
                    }
                )
            )
        ).accepted


def test_run_budget_shares_attempt_and_byte_allowance_across_requests() -> None:
    clock = [10.0]
    budget = TedRunBudget(
        max_logical_requests=3,
        max_http_attempts=3,
        deadline_seconds=10,
        max_response_bytes=100,
        monotonic=lambda: clock[0],
    )

    first = budget.begin_request(max_attempts_per_request=2)
    assert first.allowed is True
    assert first.max_http_attempts == 2
    assert first.deadline_seconds == 10
    assert first.max_response_bytes == 100
    assert budget.record(http_attempts=2, response_bytes=60) is None

    clock[0] = 14.0
    second = budget.begin_request(max_attempts_per_request=2)
    assert second.allowed is True
    assert second.max_http_attempts == 1
    assert second.deadline_seconds == 6
    assert second.max_response_bytes == 40
    assert budget.record(http_attempts=1, response_bytes=40) is None

    exhausted = budget.begin_request(max_attempts_per_request=2)
    assert exhausted.allowed is False
    assert exhausted.termination_reason == "attempt_budget_exhausted"
    assert budget.logical_requests == 2
    assert budget.http_attempts == 3
    assert budget.response_bytes == 100


@pytest.mark.parametrize(
    "budget_kwargs,advance,reason",
    (
        ({"max_logical_requests": 1}, 0, "request_budget_exhausted"),
        ({"deadline_seconds": 1}, 2, "deadline_exhausted"),
        ({"max_response_bytes": 1}, 0, "response_byte_budget_exhausted"),
    ),
)
def test_run_budget_stops_before_an_over_budget_request(
    budget_kwargs: dict[str, int], advance: int, reason: str
) -> None:
    clock = [0.0]
    values = {
        "max_logical_requests": 2,
        "max_http_attempts": 2,
        "deadline_seconds": 10,
        "max_response_bytes": 10,
    }
    values.update(budget_kwargs)
    budget = TedRunBudget(**values, monotonic=lambda: clock[0])
    first = budget.begin_request(max_attempts_per_request=1)
    assert first.allowed is True
    if reason == "response_byte_budget_exhausted":
        assert budget.record(http_attempts=1, response_bytes=1) is None
    else:
        assert budget.record(http_attempts=0, response_bytes=0) is None
    clock[0] += advance

    decision = budget.begin_request(max_attempts_per_request=1)

    assert decision.allowed is False
    assert decision.termination_reason == reason


def test_run_budget_uses_one_clock_observation_for_allowance() -> None:
    observations = iter((0.0, 0.5, 2.0))
    budget = TedRunBudget(
        max_logical_requests=1,
        max_http_attempts=1,
        deadline_seconds=1,
        max_response_bytes=1,
        monotonic=lambda: next(observations),
    )

    decision = budget.begin_request(max_attempts_per_request=1)

    assert decision.allowed is True
    assert decision.deadline_seconds == 0.5


def test_run_budget_detects_deadline_crossed_by_completed_request() -> None:
    clock = [0.0]
    budget = TedRunBudget(
        max_logical_requests=1,
        max_http_attempts=1,
        deadline_seconds=1,
        max_response_bytes=10,
        monotonic=lambda: clock[0],
    )
    assert budget.begin_request(max_attempts_per_request=1).allowed is True
    clock[0] = 2.0

    assert budget.record(http_attempts=1, response_bytes=1) == "deadline_exhausted"


def test_pagination_tracks_only_aggregate_continuity_metrics() -> None:
    pagination = TedPaginationState()

    assert pagination.observe(
        page_number=1,
        payload_signature="signature-a",
        total_notice_count=100,
        has_more=True,
    ) is None
    assert pagination.observe(
        page_number=2,
        payload_signature="signature-b",
        total_notice_count=101,
        has_more=True,
    ) is None
    termination = pagination.observe(
        page_number=3,
        payload_signature="signature-a",
        total_notice_count=101,
        has_more=True,
    )

    assert termination == "pagination_repeated"
    assert pagination.summary() == {
        "pages_observed": 3,
        "unique_page_signatures": 2,
        "repeated_page_signatures": 1,
        "total_count_change_events": 1,
        "source_exhausted": False,
        "mode": "PAGE_NUMBER",
        "interpretation": "single_run_capacity_only",
    }
    assert "signature-a" not in str(pagination.summary())


def test_pagination_marks_source_exhaustion_without_exposing_signature() -> None:
    pagination = TedPaginationState()

    assert pagination.observe(
        page_number=1,
        payload_signature="private-signature",
        total_notice_count=1,
        has_more=False,
    ) is None

    assert pagination.summary()["source_exhausted"] is True
    assert "private-signature" not in str(pagination.summary())


def test_pagination_rejects_non_progressing_page_number() -> None:
    pagination = TedPaginationState()
    assert pagination.observe(
        page_number=1,
        payload_signature="signature-a",
        total_notice_count=100,
        has_more=True,
    ) is None

    assert pagination.observe(
        page_number=1,
        payload_signature="signature-b",
        total_notice_count=100,
        has_more=True,
    ) == "pagination_repeated"


def test_pagination_requires_page_one_as_first_observation() -> None:
    pagination = TedPaginationState()

    assert pagination.observe(
        page_number=2,
        payload_signature="signature-a",
        total_notice_count=100,
        has_more=True,
    ) == "pagination_repeated"


def passing_stratum() -> dict[str, object]:
    return build_stratum_summary(
        fetched=40,
        processed=40,
        accepted=38,
        rejection_reason_counts={"duplicate_procedure": 2},
        procedure_present_count=40,
        buyer_present_count=38,
        text_present_count=40,
        required=38,
        thresholds={
            "procedure_completeness_min": 0.95,
            "buyer_completeness_min": 0.8,
            "text_completeness_min": 0.8,
            "acceptance_yield_min": 0.25,
            "processed_max_per_stratum": 300,
        },
    )


def passing_receipt() -> dict[str, object]:
    strata = {
        name: passing_stratum()
        for name in (
            "software_and_information_systems",
            "business_services",
            "health_and_social_services",
            "repair_and_maintenance_services",
        )
    }
    return build_capacity_receipt(
        run_id="36f5bfed-1a0b-45c7-86ea-aff73409d3c2",
        run_sequence=1,
        started_at="2026-08-18T00:00:00Z",
        finished_at="2026-08-18T00:00:10Z",
        elapsed_ms=10_000,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        required_per_stratum=38,
        strata=strata,
        transport={
            "logical_requests": 4,
            "http_attempts": 4,
            "retries": 0,
            "rate_limit_events": 0,
            "transport_errors": 0,
            "response_bytes": 4_000,
            "max_logical_requests": 12,
            "max_http_attempts": 24,
            "deadline_seconds": 60,
            "max_response_bytes": 10_485_760,
            "deadline_exhausted": False,
        },
        pagination={
            "pages_observed": 4,
            "unique_page_signatures": 4,
            "repeated_page_signatures": 0,
            "total_count_change_events": 0,
            "source_exhausted": False,
            "mode": "PAGE_NUMBER",
            "interpretation": "single_run_capacity_only",
        },
        failure_reason=None,
    )


def test_capacity_receipt_is_exact_hash_bound_and_aggregate_only() -> None:
    receipt = passing_receipt()

    assert receipt["status"] == "PASS"
    assert receipt["termination_reason"] == "capacity_reached"
    assert receipt["retained_items"] == 0
    assert receipt["raw_text_persisted"] == 0
    assert receipt["raw_author_persisted"] == 0
    assert validate_capacity_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    ) == []
    serialized = json.dumps(receipt, sort_keys=True)
    assert "private-title-marker" not in serialized
    assert "buyer-identifier" not in serialized


def test_capacity_receipt_rejects_extra_raw_fields_hash_drift_and_arithmetic_drift() -> None:
    extra = passing_receipt()
    extra["query"] = "private-title-marker"
    assert validate_capacity_receipt(
        extra,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )

    hash_drift = passing_receipt()
    hash_drift["capacity_manifest_hash"] = "d" * 64
    assert "capacity manifest hash mismatch" in validate_capacity_receipt(
        hash_drift,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )

    arithmetic = passing_receipt()
    strata = arithmetic["strata"]
    assert isinstance(strata, dict)
    first = strata["software_and_information_systems"]
    assert isinstance(first, dict)
    first["processed"] = 39
    assert any(
        "arithmetic" in error
        for error in validate_capacity_receipt(
            arithmetic,
            capacity_manifest_hash="a" * 64,
            feasibility_hash="b" * 64,
            compliance_hash="c" * 64,
        )
    )


def test_capacity_receipt_rejects_non_uuid_run_id() -> None:
    receipt = passing_receipt()
    receipt["run_id"] = "private-title-marker / buyer-identifier"

    assert validate_capacity_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_capacity_receipt_rejects_non_finite_ratios(non_finite: float) -> None:
    receipt = passing_receipt()
    strata = receipt["strata"]
    assert isinstance(strata, dict)
    first = strata["software_and_information_systems"]
    assert isinstance(first, dict)
    first["procedure_completeness"] = non_finite
    first["capacity_pass"] = False
    receipt["status"] = "FAIL"
    receipt["termination_reason"] = "quality_threshold_failed"

    assert validate_capacity_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_capacity_receipt_rejects_non_finite_deadline(non_finite: float) -> None:
    receipt = passing_receipt()
    transport = receipt["transport"]
    assert isinstance(transport, dict)
    transport["deadline_seconds"] = non_finite

    assert validate_capacity_receipt(
        receipt,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )


def test_capacity_receipt_handles_arbitrarily_large_integers_without_crashing() -> None:
    deadline = passing_receipt()
    deadline_transport = deadline["transport"]
    assert isinstance(deadline_transport, dict)
    deadline_transport["deadline_seconds"] = 10**1000
    assert validate_capacity_receipt(
        deadline,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    ) == []

    ratio = passing_receipt()
    ratio_strata = ratio["strata"]
    assert isinstance(ratio_strata, dict)
    first = ratio_strata["software_and_information_systems"]
    assert isinstance(first, dict)
    first["procedure_completeness"] = 10**1000
    assert validate_capacity_receipt(
        ratio,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )


def test_capacity_receipt_cannot_claim_pass_when_quality_or_pagination_fails() -> None:
    quality = passing_receipt()
    quality_strata = quality["strata"]
    assert isinstance(quality_strata, dict)
    first = quality_strata["software_and_information_systems"]
    assert isinstance(first, dict)
    first["capacity_pass"] = False
    assert "PASS receipt has a failed stratum" in validate_capacity_receipt(
        quality,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )

    pagination = passing_receipt()
    pagination_value = pagination["pagination"]
    assert isinstance(pagination_value, dict)
    pagination_value["repeated_page_signatures"] = 1
    assert "PASS receipt has pagination failure" in validate_capacity_receipt(
        pagination,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )


def test_capacity_receipt_recomputes_pass_and_transport_pagination_arithmetic() -> None:
    capacity = passing_receipt()
    capacity_strata = capacity["strata"]
    assert isinstance(capacity_strata, dict)
    first = capacity_strata["software_and_information_systems"]
    assert isinstance(first, dict)
    first["accepted"] = 37
    first["rejected"] = 3
    first["rejection_reason_counts"] = {"duplicate_procedure": 3}
    assert "stratum capacity pass mismatch: software_and_information_systems" in validate_capacity_receipt(
        capacity,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )

    transport = passing_receipt()
    transport_value = transport["transport"]
    assert isinstance(transport_value, dict)
    transport_value["retries"] = 5
    assert "capacity receipt transport arithmetic mismatch" in validate_capacity_receipt(
        transport,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )

    pagination = passing_receipt()
    pagination_value = pagination["pagination"]
    assert isinstance(pagination_value, dict)
    pagination_value["pages_observed"] = 5
    assert "capacity receipt pagination arithmetic mismatch" in validate_capacity_receipt(
        pagination,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )


def test_failed_receipt_remains_valid_and_preserves_only_failure_enum() -> None:
    receipt = passing_receipt()
    failed = build_capacity_receipt(
        run_id=str(receipt["run_id"]),
        run_sequence=int(receipt["run_sequence"]),
        started_at=str(receipt["started_at"]),
        finished_at=str(receipt["finished_at"]),
        elapsed_ms=int(receipt["elapsed_ms"]),
        capacity_manifest_hash=str(receipt["capacity_manifest_hash"]),
        feasibility_hash=str(receipt["feasibility_hash"]),
        compliance_hash=str(receipt["compliance_hash"]),
        required_per_stratum=int(receipt["required_per_stratum"]),
        strata=copy.deepcopy(receipt["strata"]),
        transport=copy.deepcopy(receipt["transport"]),
        pagination=copy.deepcopy(receipt["pagination"]),
        failure_reason="source_exhausted",
    )

    assert failed["status"] == "FAIL"
    assert failed["termination_reason"] == "source_exhausted"
    assert validate_capacity_receipt(
        failed,
        capacity_manifest_hash="a" * 64,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    ) == []
