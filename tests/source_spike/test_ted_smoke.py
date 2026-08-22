import json
from pathlib import Path

from src.source_spike.adapters.ted_http import TedPage, TedTransportSuccess
from src.source_spike.ted_smoke import build_ted_smoke_report, execute_ted_smoke, validate_ted_smoke_report


def test_smoke_report_is_aggregate_only_and_qualifies_exact_target() -> None:
    report = build_ted_smoke_report(run_id="run-1", counts={"software_and_information_systems": 3, "business_services": 3, "health_and_social_services": 2, "repair_and_maintenance_services": 2}, target=10, accepted_refs=[{"source_item_id": str(i), "source_url": f"https://ted.europa.eu/en/notice/-/detail/{i}", "published_at": "2026-08-01T00:00:00Z"} for i in range(10)], transport={"logical_requests": 4, "http_attempts": 4, "retries": 0, "rate_limit_events": 0, "transport_errors": 0, "response_bytes": 1000, "max_logical_requests": 8, "max_http_attempts": 16, "deadline_seconds": 45, "max_response_bytes": 10485760}, provenance={"manifest_hash": "a" * 64, "capacity_manifest_hash": "b" * 64, "authorization_hash": "c" * 64})
    assert report["status"] == "PASS"
    assert report["termination_reason"] == "target_reached"
    assert report["accepted"] == 10
    serialized = str(report)
    assert "author_hash" not in serialized
    assert "normalized_text" not in serialized
    assert "buyer-identifier" not in serialized
    assert validate_ted_smoke_report(report) == []


def test_smoke_report_rejects_incomplete_references_and_provenance() -> None:
    report = build_ted_smoke_report(
        run_id="run-1",
        counts={"software_and_information_systems": 3, "business_services": 3, "health_and_social_services": 2, "repair_and_maintenance_services": 2},
        target=10,
        accepted_refs=[{} for _ in range(10)],
        transport={},
        provenance={},
    )
    assert report["status"] == "FAIL"
    assert validate_ted_smoke_report(report)


class _Transport:
    def fetch_notices(self, **kwargs: object) -> TedTransportSuccess:
        query = str(kwargs["query"])
        prefix = next(value for value in ("48", "79", "85", "50") if f"= {value}*" in query)
        notices = []
        for index in range(5):
            notices.append({
                "publication-number": f"{prefix}{index:04d}-2026",
                "notice-identifier": f"notice-{prefix}-{index}",
                "procedure-identifier": f"procedure-{prefix}-{index}",
                "publication-date": "2026-08-01+00:00",
                "notice-type": "cn-standard", "form-type": "competition",
                "classification-cpv": [f"{prefix}000000"],
                "buyer-identifier": [f"buyer-{prefix}-{index}"],
                "notice-title": {"eng": f"Procurement {prefix} {index}"},
                "description-proc": {"eng": "A sufficiently detailed public procurement requirement for qualified suppliers."},
            })
        page = TedPage(notices, len(notices), int(kwargs["page"]), False, prefix, None)
        return TedTransportSuccess(page, 1, 0, 1000)


class _OutOfContractTransport(_Transport):
    def fetch_notices(self, **kwargs: object) -> TedTransportSuccess:
        response = super().fetch_notices(**kwargs)
        if "= 48*" not in str(kwargs["query"]):
            return response
        invalid = [dict(response.page.notices[0]) for _ in range(3)]
        invalid[0].update({"notice-identifier": "invalid-window", "procedure-identifier": "invalid-window-procedure", "publication-date": "2025-01-01+00:00"})
        invalid[1].update({"notice-identifier": "invalid-cpv", "procedure-identifier": "invalid-cpv-procedure", "classification-cpv": ["79000000"]})
        invalid[2].update({"notice-identifier": "invalid-change", "procedure-identifier": "invalid-change-procedure", "change-notice-version-identifier": ["change-1"]})
        notices = invalid + list(response.page.notices)
        return TedTransportSuccess(TedPage(notices, len(notices), 1, False, "out-of-contract", None), 1, 0, 1000)


def test_execute_ted_smoke_reaches_all_stratum_quotas_without_persisting_items() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "config/source-spike/ted-smoke.json").read_text())
    capacity = json.loads((root / "config/source-spike/ted-capacity.json").read_text())
    report = execute_ted_smoke(manifest, capacity, _Transport(), author_secret=b"x" * 32, run_id="run-1", authorization_hash="c" * 64)
    assert report["status"] == "PASS"
    assert report["strata"] == {"software_and_information_systems": 3, "business_services": 3, "health_and_social_services": 2, "repair_and_maintenance_services": 2}
    assert report["raw_text_persisted"] == 0
    assert report["raw_author_persisted"] == 0


def test_execute_ted_smoke_rejects_out_of_contract_notices() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "config/source-spike/ted-smoke.json").read_text())
    capacity = json.loads((root / "config/source-spike/ted-capacity.json").read_text())
    report = execute_ted_smoke(manifest, capacity, _OutOfContractTransport(), author_secret=b"x" * 32, run_id="run-1", authorization_hash="c" * 64)
    ids = {ref["source_item_id"] for ref in report["accepted_refs"]}
    assert report["status"] == "PASS"
    assert not {"invalid-window", "invalid-cpv", "invalid-change"} & ids
