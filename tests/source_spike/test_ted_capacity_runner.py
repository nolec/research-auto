from __future__ import annotations

import json
from pathlib import Path

from src.source_spike.adapters.ted_http import (
    TedPage,
    TedTransportFailure,
    TedTransportSuccess,
)
from src.source_spike.protocol import content_sha256
from src.source_spike.ted_capacity_runner import execute_capacity_probe
from src.source_spike.ted_query_validation import (
    build_query_set,
    build_validation_receipt,
    run_query_validation,
)


ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "12345678-1234-4234-8234-123456789abc"
RAW_MARKER = "PRIVATE-RAW-TED-MARKER"


def load_manifest() -> dict[str, object]:
    return json.loads(
        (ROOT / "config/source-spike/ted-capacity.json").read_text(encoding="utf-8")
    )


def valid_notice(stratum: str, index: int) -> dict[str, object]:
    prefixes = {
        "software_and_information_systems": "48",
        "business_services": "79",
        "health_and_social_services": "85",
        "repair_and_maintenance_services": "50",
    }
    return {
        "notice-identifier": f"notice-{stratum}-{index}",
        "procedure-identifier": f"procedure-{stratum}-{index}",
        "buyer-identifier": f"buyer-{stratum}-{index}",
        "publication-date": "20260601",
        "notice-type": "cn-standard",
        "form-type": "competition",
        "classification-cpv": [f"{prefixes[stratum]}000000"],
        "description-proc": f"{RAW_MARKER}-{index}",
    }


class SyntaxTransport:
    def validate_query_syntax(self, **kwargs):
        return TedTransportSuccess(TedPage((), 0, 1, False, "a" * 64, None), 1, 0, 10)


def query_receipt(manifest: dict[str, object], *, capacity_hash: str) -> dict[str, object]:
    result = run_query_validation(manifest, SyntaxTransport())
    return build_validation_receipt(
        result,
        run_id=RUN_ID,
        started_at="2026-08-21T00:00:00Z",
        finished_at="2026-08-21T00:00:01Z",
        elapsed_ms=1000,
        capacity_manifest_hash=capacity_hash,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
    )


class SuccessfulTransport:
    def __init__(self, manifest: dict[str, object]) -> None:
        self.calls: list[dict[str, object]] = []
        self.queries = {
            candidate.query: candidate.stratum
            for candidate in build_query_set(manifest).candidates
        }

    def fetch_notices(self, **kwargs):
        self.calls.append(kwargs)
        stratum = self.queries[str(kwargs["query"])]
        notices = tuple(valid_notice(stratum, index) for index in range(38))
        return TedTransportSuccess(
            TedPage(notices, 38, int(kwargs["page"]), False, str(len(self.calls)) * 64, None),
            1,
            0,
            1024,
        )


def test_success_uses_only_qualified_queries_and_persists_aggregate_receipt(tmp_path: Path) -> None:
    manifest = load_manifest()
    capacity_hash = content_sha256(manifest)
    transport = SuccessfulTransport(manifest)

    execution = execute_capacity_probe(
        manifest,
        query_receipt(manifest, capacity_hash=capacity_hash),
        transport,
        output_root=tmp_path / "capacity",
        capacity_manifest_hash=capacity_hash,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        run_id=RUN_ID,
        started_at="2026-08-21T00:00:00Z",
        finished_at="2026-08-21T00:00:02Z",
        elapsed_ms=2000,
    )

    assert execution.exit_code == 0
    assert execution.status == "PASS"
    assert [call["query"] for call in transport.calls] == [
        candidate.query for candidate in build_query_set(manifest).candidates
    ]
    receipt = json.loads(execution.receipt_path.read_text(encoding="utf-8"))
    assert receipt["run_sequence"] == 1
    assert receipt["termination_reason"] == "capacity_reached"
    assert set(receipt["strata"]) == {
        "software_and_information_systems",
        "business_services",
        "health_and_social_services",
        "repair_and_maintenance_services",
    }
    assert all(value["accepted"] == 38 for value in receipt["strata"].values())
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "capacity").rglob("*.json"))
    assert RAW_MARKER not in persisted
    assert "SORT BY" not in persisted
    assert "publication-date =" not in persisted


class FailingTransport:
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code

    def fetch_notices(self, **kwargs):
        return TedTransportFailure(self.error_code, 1, 0, 0)


class EventfulTransportFailure:
    def fetch_notices(self, **kwargs):
        return TedTransportFailure(
            "transport_error",
            1,
            0,
            0,
            ({"category": "transport_error"},),
        )


class CrossStratumCollisionTransport(SuccessfulTransport):
    def fetch_notices(self, **kwargs):
        self.calls.append(kwargs)
        stratum = self.queries[str(kwargs["query"])]
        notices = [valid_notice(stratum, index) for index in range(44)]
        for index in (0, 1):
            notices[index]["buyer-identifier"] = "shared-buyer"
        notices[2]["notice-identifier"] = "shared-notice"
        notices[2]["procedure-identifier"] = "shared-procedure"
        notices[3]["procedure-identifier"] = "shared-procedure-only"
        return TedTransportSuccess(
            TedPage(tuple(notices), 44, int(kwargs["page"]), False, str(len(self.calls)) * 64, None),
            1,
            0,
            1024,
        )


def test_identity_and_buyer_limits_are_shared_across_strata(tmp_path: Path) -> None:
    manifest = load_manifest()
    capacity_hash = content_sha256(manifest)

    execution = execute_capacity_probe(
        manifest,
        query_receipt(manifest, capacity_hash=capacity_hash),
        CrossStratumCollisionTransport(manifest),
        output_root=tmp_path / "capacity",
        capacity_manifest_hash=capacity_hash,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        run_id=RUN_ID,
        started_at="2026-08-21T00:00:00Z",
        finished_at="2026-08-21T00:00:02Z",
        elapsed_ms=2000,
    )

    assert execution.status == "PASS"
    receipt = json.loads(execution.receipt_path.read_text(encoding="utf-8"))
    assert receipt["strata"]["software_and_information_systems"]["rejection_reason_counts"] == {}
    assert all(
        receipt["strata"][name]["rejection_reason_counts"] == {
            "buyer_limit_exceeded": 2,
            "duplicate_notice": 1,
            "duplicate_procedure": 1,
        }
        for name in (
            "business_services",
            "health_and_social_services",
            "repair_and_maintenance_services",
        )
    )


def test_transport_failure_persists_schema_valid_four_stratum_fail_receipt(tmp_path: Path) -> None:
    manifest = load_manifest()
    capacity_hash = content_sha256(manifest)

    execution = execute_capacity_probe(
        manifest,
        query_receipt(manifest, capacity_hash=capacity_hash),
        FailingTransport("http_503"),
        output_root=tmp_path / "capacity",
        capacity_manifest_hash=capacity_hash,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        run_id=RUN_ID,
        started_at="2026-08-21T00:00:00Z",
        finished_at="2026-08-21T00:00:01Z",
        elapsed_ms=1000,
    )

    assert execution.exit_code == 2
    receipt = json.loads(execution.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["termination_reason"] == "transport_failed"
    assert len(receipt["strata"]) == 4
    assert all(value["accepted"] == 0 for value in receipt["strata"].values())


def test_terminal_transport_event_is_counted_once(tmp_path: Path) -> None:
    manifest = load_manifest()
    capacity_hash = content_sha256(manifest)

    execution = execute_capacity_probe(
        manifest,
        query_receipt(manifest, capacity_hash=capacity_hash),
        EventfulTransportFailure(),
        output_root=tmp_path / "capacity",
        capacity_manifest_hash=capacity_hash,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        run_id=RUN_ID,
        started_at="2026-08-21T00:00:00Z",
        finished_at="2026-08-21T00:00:01Z",
        elapsed_ms=1000,
    )

    receipt = json.loads(execution.receipt_path.read_text(encoding="utf-8"))
    assert receipt["transport"]["transport_errors"] == 1


def test_preflight_hash_drift_stops_before_network(tmp_path: Path) -> None:
    manifest = load_manifest()
    capacity_hash = content_sha256(manifest)
    transport = SuccessfulTransport(manifest)
    receipt = query_receipt(manifest, capacity_hash=capacity_hash)
    receipt["strata"][0]["query_sha256"] = "f" * 64

    execution = execute_capacity_probe(
        manifest,
        receipt,
        transport,
        output_root=tmp_path / "capacity",
        capacity_manifest_hash=capacity_hash,
        feasibility_hash="b" * 64,
        compliance_hash="c" * 64,
        run_id=RUN_ID,
    )

    assert execution.exit_code == 3
    assert execution.error_code == "prerequisite_failed"
    assert execution.receipt_path is None
    assert transport.calls == []
