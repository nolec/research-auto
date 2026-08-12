from __future__ import annotations

from math import sqrt
import json
import os
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Mapping
from jsonschema import Draft202012Validator
from typing import Sequence

from src.contracts.validation import FORMAT_CHECKER
from src.source_spike.protocol import agreement_result


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config/source-spike/source-quality-policy.json"
POLICY_SCHEMA_PATH = ROOT / "schemas/source-quality-policy.schema.json"
LABEL_SCHEMA_PATH = ROOT / "schemas/source-label.schema.json"


def signal_density(values: Sequence[bool]) -> dict[str, object]:
    if not values:
        raise ValueError("at least one label is required")
    total = len(values)
    positive = sum(values)
    estimate = positive / total
    z = 1.959963984540054
    denominator = 1 + (z * z / total)
    center = (estimate + z * z / (2 * total)) / denominator
    margin = z * sqrt(estimate * (1 - estimate) / total + z * z / (4 * total * total)) / denominator
    return {
        "positive": positive,
        "total": total,
        "estimate": estimate,
        "wilson_95": [max(0.0, center - margin), min(1.0, center + margin)],
    }


def descriptive_agreement(primary: Sequence[bool], secondary: Sequence[bool]) -> dict[str, object]:
    result = agreement_result(primary, secondary)
    total = len(primary)
    return {
        "sample_size": total,
        "raw_agreement": result.raw_agreement,
        "kappa": result.kappa,
        "kappa_status": result.kappa_status,
        "positive_prevalence": (sum(primary) + sum(secondary)) / (2 * total),
        "interpretation": "descriptive_pilot",
    }


def build_development_report(
    development_labels: Path, *, provenance: Mapping[str, object]
) -> dict[str, object]:
    labels = [
        json.loads(line)
        for line in development_labels.read_text(encoding="utf-8").splitlines()
        if line
    ]
    label_schema = json.loads(LABEL_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(label_schema, format_checker=FORMAT_CHECKER)
    for value in labels:
        errors = list(validator.iter_errors(value))
        if errors:
            raise ValueError(f"invalid canonical development label: {errors[0].message}")
    if any(value["assignment_split"] != "development" for value in labels):
        raise ValueError("development report accepts only development split labels")
    primary = [value for value in labels if value["review_round"] == "primary"]
    if len(primary) != 10:
        raise ValueError("development report requires exactly 10 primary labels")
    if len({value["document_id"] for value in primary}) != 10:
        raise ValueError("development report requires 10 unique primary documents")
    by_primary = {value["document_id"]: value for value in primary}
    secondary = [value for value in labels if value["review_round"] == "secondary"]
    if len(secondary) != 5 or len({value["document_id"] for value in secondary}) != 5:
        raise ValueError("development report requires exactly 5 unique secondary documents")
    if any(value["document_id"] not in by_primary for value in secondary):
        raise ValueError("secondary labels must pair with development primary labels")
    if any(value["reviewer_id"] == by_primary[value["document_id"]]["reviewer_id"] for value in secondary):
        raise ValueError("secondary labels require an independent reviewer")
    pairs = [(by_primary[value["document_id"]], value) for value in secondary]
    fields = ("problem_signal", "money_signal", "usable_evidence", "noise")
    density = {field: signal_density([bool(value[field]) for value in primary]) for field in fields}
    adjusted_money = [
        bool(value["money_signal"] and not value["structural_money_signal"])
        for value in primary
    ]
    density["money_signal_adjusted"] = signal_density(adjusted_money)
    agreement: dict[str, object] = {}
    for field in fields:
        if pairs:
            agreement[field] = descriptive_agreement(
                [bool(left[field]) for left, _ in pairs],
                [bool(right[field]) for _, right in pairs],
            )
        else:
            agreement[field] = {
                "sample_size": 0,
                "status": "unavailable",
                "interpretation": "descriptive_pilot",
            }
    return {
        "population": "development_only",
        "primary_sample_size": 10,
        "holdout_status": "sealed",
        "density": density,
        "agreement": agreement,
        "provenance": dict(provenance),
    }


def load_source_quality_policy(path: Path = POLICY_PATH) -> dict[str, object]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(policy))
    if errors:
        raise ValueError(f"invalid source quality policy: {errors[0].message}")
    return policy


def policy_sha256(path: Path = POLICY_PATH) -> str:
    value = load_source_quality_policy(path)
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode()).hexdigest()


def write_development_report(root: Path, report: Mapping[str, object]) -> Path:
    destination = root / "report"
    temporary = root / ".report.tmp"
    if destination.exists() or temporary.exists():
        raise ValueError("development report artifact already exists")
    try:
        temporary.mkdir(parents=True)
        (temporary / "development-source-quality.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        lines = [
            "# Development Source Quality",
            "",
            f"Population: {report['population']}",
            f"Primary sample: {report['primary_sample_size']}",
            f"Holdout: {report['holdout_status']}",
            "",
            "Agreement is a descriptive pilot and is not a qualification gate.",
        ]
        (temporary / "development-source-quality.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination
