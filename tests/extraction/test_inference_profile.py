from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.extraction.inference_profile import load_inference_profile


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "configs/extraction/inference-profile-gpt-5.6-v1.json"


def test_frozen_profile_matches_the_approved_accuracy_first_experiment() -> None:
    profile = load_inference_profile(PROFILE)

    assert profile.provider == "openai"
    assert profile.model == "gpt-5.6"
    assert profile.input_count == 40
    assert profile.max_cost_usd == 5
    assert profile.max_wall_seconds == 1800
    assert profile.max_retries_per_document == 2
    assert profile.max_profiles == 1
    assert profile.max_metric_runs == 1
    assert profile.allow_metric_failure_fallback is False
    assert profile.allow_calibration_retuning is False
    assert profile.persist_raw_response is False
    assert profile.sources == ("github", "stackexchange", "steam", "ted")
    assert profile.source_role == "calibration_source"
    assert len(profile.output_schema_sha256) == 64
    assert profile.output_schema["additionalProperties"] is False
    assert len(profile.profile_sha256) == 64


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("experiment", "max_profiles"), 2, "max_profiles"),
        (("experiment", "allow_calibration_retuning"), True, "retuning"),
        (("experiment", "allow_metric_failure_fallback"), True, "metric"),
        (("retention", "persist_raw_response"), True, "raw response"),
        (("source_policy", "source_role"), "v1_selected_source", "calibration_source"),
    ],
)
def test_profile_rejects_scope_expansion(
    tmp_path: Path, path: tuple[str, str], value: object, message: str
) -> None:
    payload = json.loads(PROFILE.read_text(encoding="utf-8"))
    payload[path[0]][path[1]] = value
    candidate = tmp_path / "profile.json"
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_inference_profile(candidate)
