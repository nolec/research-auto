from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence, cast

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


class MoneySignalType(StrEnum):
    PURCHASE = "purchase"
    SUBSCRIPTION = "subscription"
    OUTSOURCING = "outsourcing"
    LABOR_COST = "labor_cost"
    LOSS = "loss"
    WILLINGNESS_TO_PAY = "willingness_to_pay"
    PRICE_COMPLAINT = "price_complaint"
    REPLACEMENT_SEARCH = "replacement_search"

_MANIFEST_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "source-spike-manifest.schema.json"
)
_COMPLIANCE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "source-compliance.schema.json"
)
_MANIFEST_VALIDATOR = Draft202012Validator(
    json.loads(_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
)
_COMPLIANCE_VALIDATOR = Draft202012Validator(
    json.loads(_COMPLIANCE_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FORMAT_CHECKER,
)


def content_sha256(value: Mapping[str, object]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


@dataclass(frozen=True)
class Label:
    money_signal: bool
    money_signal_type: MoneySignalType | None = None
    structural_money_signal: bool = False

    def __post_init__(self) -> None:
        if self.money_signal_type is not None:
            try:
                normalized_type = MoneySignalType(self.money_signal_type)
            except ValueError as error:
                raise ValueError(
                    f"unsupported money_signal_type: {self.money_signal_type}"
                ) from error
            object.__setattr__(self, "money_signal_type", normalized_type)
        if self.money_signal and self.money_signal_type is None:
            raise ValueError("money_signal_type is required when money_signal is true")
        if not self.money_signal and self.money_signal_type is not None:
            raise ValueError("money_signal_type requires money_signal to be true")
        if self.structural_money_signal and not self.money_signal:
            raise ValueError("structural_money_signal requires money_signal to be true")


@dataclass(frozen=True)
class MoneyDensity:
    raw: float
    adjusted: float


def money_density(labels: Sequence[Label]) -> MoneyDensity:
    if not labels:
        raise ValueError("at least one label is required")
    raw_count = sum(label.money_signal for label in labels)
    adjusted_count = sum(
        label.money_signal and not label.structural_money_signal for label in labels
    )
    return MoneyDensity(raw=raw_count / len(labels), adjusted=adjusted_count / len(labels))


@dataclass(frozen=True)
class AgreementResult:
    raw_agreement: float
    kappa: float | None
    kappa_status: Literal["calculated", "prevalence_limited"]
    passed: bool


def agreement_result(
    reviewer_a: Sequence[bool], reviewer_b: Sequence[bool]
) -> AgreementResult:
    if not reviewer_a or len(reviewer_a) != len(reviewer_b):
        raise ValueError("reviewer labels must be non-empty and have equal length")

    total = len(reviewer_a)
    raw = sum(a == b for a, b in zip(reviewer_a, reviewer_b, strict=True)) / total
    combined_positive = sum(reviewer_a) + sum(reviewer_b)
    combined_negative = (2 * total) - combined_positive
    prevalence_limited = min(combined_positive, combined_negative) < 2

    if prevalence_limited:
        return AgreementResult(
            raw_agreement=raw,
            kappa=None,
            kappa_status="prevalence_limited",
            passed=raw >= 0.8,
        )

    positive_a = sum(reviewer_a) / total
    positive_b = sum(reviewer_b) / total
    expected = positive_a * positive_b + (1 - positive_a) * (1 - positive_b)
    kappa = 1.0 if expected == 1.0 else (raw - expected) / (1 - expected)
    return AgreementResult(
        raw_agreement=raw,
        kappa=kappa,
        kappa_status="calculated",
        passed=raw >= 0.8 and kappa >= 0.6,
    )


@dataclass(frozen=True)
class SelectionResult:
    primary: list[str]
    fallback: list[str]
    success: bool


def select_primary_sources(
    candidates: Iterable[Mapping[str, object]], limit: int = 3
) -> SelectionResult:
    if limit < 1:
        raise ValueError("limit must be positive")
    candidate_list = list(candidates)
    source_names = [str(candidate["source"]) for candidate in candidate_list]
    duplicate_names = sorted(
        name for name, count in Counter(source_names).items() if count > 1
    )
    if duplicate_names:
        raise ValueError(f"duplicate source candidates: {', '.join(duplicate_names)}")
    ranked = sorted(
        candidate_list, key=lambda item: float(item["score"]), reverse=True
    )
    primary = [
        str(item["source"]) for item in ranked if item["eligibility"] == "pass"
    ][:limit]
    fallback = [
        str(item["source"])
        for item in ranked
        if item["eligibility"] == "provisional"
    ]
    return SelectionResult(primary=primary, fallback=fallback, success=len(primary) == limit)


def validate_manifest(
    manifest: Mapping[str, object],
    compliance_records: Mapping[str, Mapping[str, object]],
) -> list[str]:
    schema_errors = sorted(
        _MANIFEST_VALIDATOR.iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if schema_errors:
        return [
            f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
            for error in schema_errors
        ]

    errors: list[str] = []
    target = int(manifest["target_valid_records"])
    sources = cast(Sequence[Mapping[str, object]], manifest["sources"])
    source_names = [str(source["source"]) for source in sources]
    duplicate_names = sorted(
        name for name, count in Counter(source_names).items() if count > 1
    )
    if duplicate_names:
        errors.append(
            f"sources must have unique source names: {', '.join(duplicate_names)}"
        )

    for source in sources:
        source_name = str(source["source"])
        strata = cast(Sequence[Mapping[str, object]], source["strata"])
        stratum_names = [str(stratum["name"]) for stratum in strata]
        stratum_targets = [str(stratum["target"]) for stratum in strata]
        if len(set(stratum_names)) != len(stratum_names):
            errors.append(f"{source_name}: strata must have unique name values")
        if len(set(stratum_targets)) != len(stratum_targets):
            errors.append(f"{source_name}: strata must have unique target values")

        quota_total = sum(int(stratum["quota"]) for stratum in strata)
        if quota_total != target:
            errors.append(
                f"{source_name}: stratum quotas must total target_valid_records "
                f"({quota_total} != {target})"
            )

        compliance_ref = str(source["compliance_ref"])
        compliance_record = compliance_records.get(compliance_ref)
        if compliance_record is None:
            errors.append(f"{source_name}: missing compliance record {compliance_ref}")
            continue

        compliance_errors = sorted(
            _COMPLIANCE_VALIDATOR.iter_errors(compliance_record),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if compliance_errors:
            errors.extend(
                f"{source_name}: invalid compliance record {compliance_ref}: "
                f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: "
                f"{error.message}"
                for error in compliance_errors
            )
            continue

        if content_sha256(compliance_record) != source["compliance_hash"]:
            errors.append(f"{source_name}: compliance hash mismatch for {compliance_ref}")
        if compliance_record["source"] != source_name:
            errors.append(
                f"{source_name}: compliance source does not match "
                f"{compliance_record['source']}"
            )
        if compliance_record["decision"] != source["compliance_decision"]:
            errors.append(
                f"{source_name}: manifest decision {source['compliance_decision']} "
                f"does not match compliance decision {compliance_record['decision']}"
            )
    return errors
