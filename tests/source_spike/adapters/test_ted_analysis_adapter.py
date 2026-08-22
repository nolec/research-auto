import json
from datetime import datetime, timezone
from pathlib import Path

from src.source_spike.adapters.base import CollectionStatus, InvalidItem, TerminationReason
from src.source_spike.adapters.ted import ParsedTedNotice, TedNoticeAdapter
from src.source_spike.adapters.ted_http import TedPage, TedTransportSuccess
from src.source_spike.ted_analysis_manifest import validate_ted_analysis_manifest


def test_analysis_adapter_contract_is_available() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "config/source-spike/ted-analysis.json").read_text())
    assert TedNoticeAdapter.source == "ted"
    assert manifest["target_valid_records"] == 100


def _notice(prefix: str, index: int, *, publication_date: str = "20260801") -> dict[str, object]:
    identity = f"{prefix}-{index:02d}"
    return {
        "publication-number": f"{identity}-2026",
        "notice-identifier": f"notice-{identity}",
        "procedure-identifier": f"procedure-{identity}",
        "buyer-identifier": [f"buyer-{identity}"],
        "publication-date": publication_date,
        "notice-type": "cn-standard",
        "form-type": "competition",
        "classification-cpv": [f"{prefix}000000"],
        "notice-title": {"eng": [f"Synthetic notice {identity}"]},
        "description-proc": {"eng": ["A sufficiently detailed synthetic procurement problem description for adapter testing."]},
        "change-notice-version-identifier": [],
    }


class _BalancedTransport:
    def fetch_notices(self, **kwargs: object) -> TedTransportSuccess:
        query = str(kwargs["query"])
        prefix = next(value for value in ("48", "79", "85", "50") if f"= {value}*" in query)
        notices = tuple(_notice(prefix, index) for index in range(25))
        return TedTransportSuccess(
            TedPage(notices, 25, int(kwargs["page"]), False, prefix * 32, None),
            http_attempt_count=1,
            retry_count=0,
            response_bytes=100,
        )


def test_analysis_adapter_collects_balanced_quota_and_normalizes_date_only_as_utc() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "config/source-spike/ted-analysis.json").read_text())
    capacity = json.loads((root / "config/source-spike/ted-capacity.json").read_text())
    collected_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
    adapter = TedNoticeAdapter(
        _BalancedTransport(),
        capacity_manifest=capacity,
        author_secret=b"a" * 32,
        manifest_validator=validate_ted_analysis_manifest,
        clock=lambda: collected_at,
        monotonic=lambda: 0.0,
    )

    result = adapter.collect(manifest, 100, run_id="run-1", manifest_version="1.0.0")

    assert result.status is CollectionStatus.SUCCESS
    assert result.termination_reason is TerminationReason.TARGET_REACHED
    assert [segment.accepted_item_count for segment in result.segment_results] == [25] * 4
    assert result.request_count == result.http_attempt_count == 4
    assert {item["published_at"] for item in result.items} == {"2026-08-01T00:00:00Z"}


def test_analysis_adapter_fails_closed_on_residual_contact(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "config/source-spike/ted-analysis.json").read_text())
    capacity = json.loads((root / "config/source-spike/ted-capacity.json").read_text())
    collected_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "src.source_spike.adapters.ted.parse_ted_notice",
        lambda *args, **kwargs: ParsedTedNotice(
            None,
            InvalidItem("notice-private", "residual_contact", ("contact candidate remains",)),
        ),
    )
    adapter = TedNoticeAdapter(
        _BalancedTransport(),
        capacity_manifest=capacity,
        author_secret=b"a" * 32,
        manifest_validator=validate_ted_analysis_manifest,
        clock=lambda: collected_at,
        monotonic=lambda: 0.0,
    )

    result = adapter.collect(manifest, 100, run_id="run-private", manifest_version="1.0.0")

    assert result.status is CollectionStatus.FAILED
    assert result.termination_reason is TerminationReason.PRIVACY_FAILURE
    assert result.accepted_item_count == 0
    assert result.rejected_item_count == 1


def test_ted_date_with_offset_suffix_remains_a_calendar_date() -> None:
    from src.source_spike.adapters.ted import parse_ted_notice

    parsed = parse_ted_notice(
        _notice("48", 1, publication_date="2026-08-01+02:00"),
        stratum="software_and_information_systems",
        author_secret=b"a" * 32,
        run_id="run-date",
        adapter_version="0.2.0",
        collected_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )

    assert parsed.rejection is None
    assert parsed.item is not None
    assert parsed.item["published_at"] == "2026-08-01T00:00:00Z"
