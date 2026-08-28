from __future__ import annotations

import json
from dataclasses import dataclass, field as dataclass_field
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from src.contracts.validation import validate_contract


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads(
    (_ROOT / "schemas/inference-profile.schema.json").read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class InferenceProfile:
    profile_id: str
    provider: str
    api: str
    model: str
    reasoning_effort: str
    prompt_path: str
    prompt_sha256: str
    prompt_text: str = dataclass_field(repr=False)
    extraction_schema_version: str
    output_schema_sha256: str
    output_schema_json: str = dataclass_field(repr=False)
    source_role: str
    sources: tuple[str, ...]
    max_profiles: int
    max_metric_runs: int
    allow_metric_failure_fallback: bool
    allow_calibration_retuning: bool
    input_count: int
    max_retries_per_document: int
    max_cost_usd: float
    max_wall_seconds: int
    max_output_tokens: int
    input_usd_per_million: float
    output_usd_per_million: float
    persist_raw_response: bool
    secret_environment_variable: str
    profile_sha256: str

    @property
    def output_schema(self) -> dict[str, object]:
        value = json.loads(self.output_schema_json)
        if not isinstance(value, dict):
            raise ValueError("frozen output schema must be an object")
        return value


def _digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_inference_profile(path: Path) -> InferenceProfile:
    raw = path.read_bytes()
    payload = json.loads(raw)
    try:
        validate_contract(payload, _SCHEMA)
    except Exception as error:
        path_text = ".".join(str(part) for part in getattr(error, "path", ()))
        readable_path = path_text.replace("_", " ")
        raise ValueError(
            "inference profile contract violation at "
            f"{path_text} ({readable_path}): {error.message}"
        ) from error

    experiment = payload["experiment"]
    retention = payload["retention"]
    source_policy = payload["source_policy"]
    if experiment["max_profiles"] != 1:
        raise ValueError("max_profiles must remain one")
    if experiment["allow_calibration_retuning"] is not False:
        raise ValueError("calibration retuning must remain disabled")
    if experiment["allow_metric_failure_fallback"] is not False:
        raise ValueError("metric failure fallback must remain disabled")
    if retention["persist_raw_response"] is not False:
        raise ValueError("raw response persistence must remain disabled")
    if source_policy["source_role"] != "calibration_source":
        raise ValueError("source role must remain calibration_source")

    prompt = payload["prompt"]
    prompt_path = (_ROOT / prompt["path"]).resolve()
    if _ROOT not in prompt_path.parents:
        raise ValueError("prompt path escapes the repository")
    prompt_bytes = prompt_path.read_bytes()
    if _digest(prompt_bytes) != prompt["sha256"]:
        raise ValueError("prompt hash mismatch")

    extraction_schema = payload["extraction_schema"]
    output_schema_path = (_ROOT / extraction_schema["path"]).resolve()
    if _ROOT not in output_schema_path.parents:
        raise ValueError("output schema path escapes the repository")
    output_schema = json.loads(output_schema_path.read_bytes())
    if not isinstance(output_schema, dict):
        raise ValueError("output schema must contain an object")
    Draft202012Validator.check_schema(output_schema)
    output_schema_json = _canonical_json(output_schema)
    if _digest(output_schema_json.encode("utf-8")) != extraction_schema["sha256"]:
        raise ValueError("output schema hash mismatch")

    limits = payload["limits"]
    pricing = payload["pricing"]
    return InferenceProfile(
        profile_id=payload["profile_id"],
        provider=payload["provider"],
        api=payload["api"],
        model=payload["model"],
        reasoning_effort=payload["reasoning_effort"],
        prompt_path=prompt["path"],
        prompt_sha256=prompt["sha256"],
        prompt_text=prompt_bytes.decode("utf-8"),
        extraction_schema_version=extraction_schema["version"],
        output_schema_sha256=extraction_schema["sha256"],
        output_schema_json=output_schema_json,
        source_role=source_policy["source_role"],
        sources=tuple(source_policy["sources"]),
        max_profiles=experiment["max_profiles"],
        max_metric_runs=experiment["max_metric_runs"],
        allow_metric_failure_fallback=experiment["allow_metric_failure_fallback"],
        allow_calibration_retuning=experiment["allow_calibration_retuning"],
        input_count=limits["input_count"],
        max_retries_per_document=limits["max_retries_per_document"],
        max_cost_usd=limits["max_cost_usd"],
        max_wall_seconds=limits["max_wall_seconds"],
        max_output_tokens=limits["max_output_tokens"],
        input_usd_per_million=pricing["input_usd_per_million"],
        output_usd_per_million=pricing["output_usd_per_million"],
        persist_raw_response=retention["persist_raw_response"],
        secret_environment_variable=payload["secret"]["environment_variable"],
        profile_sha256=_digest(raw),
    )
