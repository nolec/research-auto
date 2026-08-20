from __future__ import annotations

import copy
import json
from pathlib import Path

from src.source_spike.ted_capacity_manifest import (
    allocation_sha256,
    query_contract_sha256,
    required_capacity,
    validate_ted_capacity_manifest,
    window_sha256,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/source-spike/ted-capacity.json"
FEASIBILITY_PATH = ROOT / "config/source-spike/feasibility/ted.json"


def load() -> tuple[dict, dict]:
    return (
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
        json.loads(FEASIBILITY_PATH.read_text(encoding="utf-8")),
    )


def refresh_hashes(manifest: dict) -> None:
    manifest["allocation_hash"] = allocation_sha256(manifest["allocation"])
    manifest["window_hash"] = window_sha256(manifest["window"])
    manifest["query_contract_hash"] = query_contract_sha256(manifest)


def test_committed_ted_capacity_manifest_is_frozen_and_valid() -> None:
    manifest, feasibility = load()

    assert validate_ted_capacity_manifest(manifest, feasibility) == []
    assert required_capacity(25, 1.5) == 38
    assert manifest["allocation"] == {
        "provisional_quota_per_stratum": 25,
        "oversampling_factor": 1.5,
        "required_unique_per_stratum": 38,
        "target_unique_total": 152,
    }
    assert manifest["window"]["published_from"] == "2026-05-20T00:00:00Z"
    assert manifest["window"]["published_before"] == "2026-08-18T00:00:00Z"
    assert manifest["selection"] == {"max_items_per_buyer": 2}


def test_buyer_limit_cannot_change_and_be_rehashed() -> None:
    manifest, feasibility = load()
    changed = copy.deepcopy(manifest)
    changed["selection"] = {"max_items_per_buyer": 3}
    refresh_hashes(changed)

    errors = validate_ted_capacity_manifest(changed, feasibility)
    assert "TED selection contract mismatch" in errors


def test_strata_priority_query_and_quota_are_exact() -> None:
    manifest, _ = load()

    assert [value["name"] for value in manifest["strata"]] == [
        "software_and_information_systems",
        "business_services",
        "health_and_social_services",
        "repair_and_maintenance_services",
    ]
    assert [value["priority"] for value in manifest["strata"]] == [1, 2, 3, 4]
    assert [value["cpv_prefix"] for value in manifest["strata"]] == ["48", "79", "85", "50"]
    assert all(value["quota"] == 38 for value in manifest["strata"])
    assert all("publication-date = (20260520 <> 20260817)" in value["query"] for value in manifest["strata"])
    assert all("form-type = competition" in value["query"] for value in manifest["strata"])


def test_contact_fields_and_unfrozen_query_are_rejected() -> None:
    manifest, feasibility = load()
    changed = copy.deepcopy(manifest)
    changed["fields"].append("buyer-email")
    changed["strata"][0]["query"] = changed["strata"][0]["query"].replace("48*", "72*")
    refresh_hashes(changed)

    errors = validate_ted_capacity_manifest(changed, feasibility)
    assert "contact field is forbidden: buyer-email" in errors
    assert "stratum query mismatch: software_and_information_systems" in errors


def test_contact_policy_cannot_be_weakened_and_rehashed() -> None:
    manifest, feasibility = load()
    changed = copy.deepcopy(manifest)
    changed["forbidden_contact_fields"].remove("buyer-email")
    changed["fields"].append("buyer-email")
    refresh_hashes(changed)

    errors = validate_ted_capacity_manifest(changed, feasibility)
    assert "TED field allowlist mismatch" in errors
    assert "TED forbidden contact fields mismatch" in errors


def test_feasibility_action_and_hash_gate_probe_before_network() -> None:
    manifest, feasibility = load()
    changed_feasibility = copy.deepcopy(feasibility)
    changed_feasibility["operational_next_action"] = "implement_adapter"

    errors = validate_ted_capacity_manifest(manifest, changed_feasibility)
    assert "TED feasibility must route to probe_capacity" in errors
    assert "feasibility hash mismatch" in errors


def test_window_allocation_sort_and_budgets_cannot_drift() -> None:
    manifest, feasibility = load()
    changed = copy.deepcopy(manifest)
    changed["allocation"]["required_unique_per_stratum"] = 37
    changed["window"]["published_from"] = "2026-05-21T00:00:00Z"
    changed["sort"] = [{"field": "publication-date", "direction": "ASC"}]
    changed["pagination"]["max_http_attempts_total"] = 11
    refresh_hashes(changed)

    errors = validate_ted_capacity_manifest(changed, feasibility)
    assert "capacity allocation mismatch" in errors
    assert "published window must be exactly 90 days" in errors
    assert "capacity sort contract mismatch" in errors
    assert "max_http_attempts_total cannot be less than max_logical_requests_total" in errors


def test_query_dates_must_be_derived_from_declared_exclusive_window() -> None:
    manifest, feasibility = load()
    changed = copy.deepcopy(manifest)
    changed["window"]["query_from_date"] = "20200101"
    changed["window"]["query_to_date"] = "20200330"
    for stratum in changed["strata"]:
        stratum["query"] = stratum["query"].replace(
            "20260520 <> 20260817", "20200101 <> 20200330"
        )
    refresh_hashes(changed)

    errors = validate_ted_capacity_manifest(changed, feasibility)
    assert "query dates must match the declared exclusive window" in errors


def test_frozen_window_cannot_move_as_a_unit_and_be_rehashed() -> None:
    manifest, feasibility = load()
    changed = copy.deepcopy(manifest)
    changed["window"].update(
        published_from="2026-05-21T00:00:00Z",
        published_before="2026-08-19T00:00:00Z",
        query_from_date="20260521",
        query_to_date="20260818",
    )
    for stratum in changed["strata"]:
        stratum["query"] = stratum["query"].replace(
            "20260520 <> 20260817", "20260521 <> 20260818"
        )
    refresh_hashes(changed)

    errors = validate_ted_capacity_manifest(changed, feasibility)
    assert "TED frozen window mismatch" in errors


def test_probe_thresholds_and_budgets_cannot_be_weakened_and_rehashed() -> None:
    manifest, feasibility = load()
    changed = copy.deepcopy(manifest)
    changed["thresholds"]["acceptance_yield_min"] = 0
    changed["thresholds"]["processed_max_per_stratum"] = 1
    changed["pagination"]["max_logical_requests_per_stratum"] = 1
    changed["pagination"]["max_logical_requests_total"] = 1
    changed["pagination"]["max_attempts_per_logical_request"] = 1
    changed["pagination"]["max_http_attempts_total"] = 1
    changed["retry"]["max_retries_per_logical_request"] = 0
    refresh_hashes(changed)

    errors = validate_ted_capacity_manifest(changed, feasibility)
    assert "TED thresholds contract mismatch" in errors
    assert "TED pagination contract mismatch" in errors
    assert "TED retry contract mismatch" in errors
