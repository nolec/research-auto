from __future__ import annotations

from types import SimpleNamespace

from src.source_spike.adapters.base import CollectionStatus, TerminationReason
from src.source_spike.github_analysis import exit_code_for_result


def test_analysis_exit_codes_distinguish_success_partial_and_prerequisite() -> None:
    assert exit_code_for_result(SimpleNamespace(
        status=CollectionStatus.SUCCESS, termination_reason=TerminationReason.TARGET_REACHED
    )) == 0
    assert exit_code_for_result(SimpleNamespace(
        status=CollectionStatus.PARTIAL, termination_reason=TerminationReason.REQUEST_BUDGET_EXHAUSTED
    )) == 2
    assert exit_code_for_result(SimpleNamespace(
        status=CollectionStatus.FAILED, termination_reason=TerminationReason.PREREQUISITE_FAILED
    )) == 3
