from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence

from jsonschema import Draft202012Validator


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads((_ROOT / "schemas/calibration-gate.schema.json").read_text())
_AUDIT_SCHEMA = json.loads((_ROOT / "schemas/calibration-audit.schema.json").read_text())
GATE_IMPLEMENTATION_PATHS = (
    "schemas/calibration-audit.schema.json",
    "schemas/calibration-gate.schema.json",
    "src/extraction/calibration_audit.py",
    "src/extraction/calibration_gate.py",
)


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical_digest(value: object) -> str:
    return _digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _validate_gate_config(
    payload: bytes, *, baseline_root: Path
) -> dict[str, object]:
    config = json.loads(payload.decode("utf-8"))
    errors = list(Draft202012Validator(_SCHEMA).iter_errors(config))
    if errors:
        raise ValueError(f"gate schema validation failed: {errors[0].message}")
    manifest = json.loads((baseline_root / "bundle-manifest.json").read_text())
    baseline = config["baseline"]
    if baseline["bundle_sha256"] != manifest.get("bundle_sha256"):
        raise ValueError("baseline bundle hash mismatch")
    if baseline["implementation_bundle_sha256"] != manifest.get(
        "implementation_bundle_sha256"
    ):
        raise ValueError("baseline implementation hash mismatch")
    if baseline["metrics_sha256"] != manifest.get("files", {}).get(
        "baseline-metrics.json"
    ):
        raise ValueError("baseline metrics hash mismatch")
    if _digest_bytes((baseline_root / "baseline-metrics.json").read_bytes()) != baseline[
        "metrics_sha256"
    ]:
        raise ValueError("baseline metrics file hash mismatch")
    return config


def load_gate_config(path: Path, *, baseline_root: Path) -> dict[str, object]:
    return _validate_gate_config(path.read_bytes(), baseline_root=baseline_root)


def _validate_candidate_binding(candidate: Mapping[str, object]) -> None:
    run_receipt = candidate.get("run_receipt")
    evaluation_receipt = candidate.get("evaluation_receipt")
    if not isinstance(run_receipt, Mapping) or not isinstance(
        evaluation_receipt, Mapping
    ):
        raise ValueError("candidate receipts are missing")
    run_sha256 = _canonical_digest(run_receipt)
    if candidate.get("candidate_run_sha256") != run_sha256:
        raise ValueError("candidate run receipt hash mismatch")
    if evaluation_receipt.get("status") != "success":
        raise ValueError("candidate evaluation receipt must be successful")
    if evaluation_receipt.get("upstream_run_receipt_sha256") != run_sha256:
        raise ValueError("candidate upstream run receipt hash mismatch")
    for name in ("input_count", "covered_count", "invalid_count"):
        if candidate.get(name) != evaluation_receipt.get(name):
            raise ValueError(f"candidate {name} receipt mismatch")
    report = {
        "metrics": candidate.get("metrics"),
        "source_metrics": candidate.get("source_metrics"),
    }
    if evaluation_receipt.get("report_sha256") != _canonical_digest(report):
        raise ValueError("candidate report hash mismatch")


def _metric(candidate: Mapping[str, object], name: str) -> Mapping[str, object]:
    metrics = candidate.get("metrics")
    if not isinstance(metrics, Mapping) or not isinstance(metrics.get(name), Mapping):
        raise ValueError(f"candidate metric is missing: {name}")
    return metrics[name]


def _validate_confusion(value: Mapping[str, object], *, actual_positive: int) -> None:
    try:
        tp, fp, tn, fn = (int(value[key]) for key in ("tp", "fp", "tn", "fn"))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("candidate confusion matrix is incomplete") from error
    if min(tp, fp, tn, fn) < 0 or tp + fp + tn + fn != 40:
        raise ValueError("candidate confusion matrix must total 40")
    if tp + fn != actual_positive or value.get("actual_positive") != actual_positive:
        raise ValueError("candidate confusion matrix actual-positive count mismatch")
    if value.get("predicted_positive") != tp + fp:
        raise ValueError("candidate confusion matrix predicted-positive count mismatch")


def evaluate_gate(
    candidate: Mapping[str, object],
    audit: Mapping[str, object],
    config: Mapping[str, object],
) -> dict[str, object]:
    _validate_candidate_binding(candidate)
    thresholds = config["thresholds"]
    diagnostics = config["diagnostics"]
    problem = _metric(candidate, "problem_signal")
    evidence = _metric(candidate, "usable_evidence")
    money = _metric(candidate, "money_signal")
    _validate_confusion(problem, actual_positive=33)
    _validate_confusion(evidence, actual_positive=33)
    _validate_confusion(money, actual_positive=9)
    failures: list[str] = []
    warnings: list[str] = []

    p_predicted = int(problem["predicted_positive"])
    e_predicted = int(evidence["predicted_positive"])
    p_tp = int(problem["tp"])
    e_tp = int(evidence["tp"])
    if p_predicted < thresholds["problem_min_predicted_positive"]:
        failures.append("problem_predicted_positive")
    elif 100 * p_tp < thresholds["problem_precision_percent"] * p_predicted:
        failures.append("problem_precision")
    if e_predicted < thresholds["evidence_min_predicted_positive"]:
        failures.append("evidence_predicted_positive")
    elif 100 * e_tp < thresholds["evidence_precision_percent"] * e_predicted:
        failures.append("evidence_precision")
    if p_tp + e_tp < thresholds["macro_min_tp_sum"]:
        failures.append("macro_tp_sum")
    if e_tp < thresholds["evidence_min_tp"]:
        failures.append("evidence_tp")
    if int(candidate.get("covered_count", -1)) < thresholds["covered_min_count"]:
        failures.append("covered_count")
    if int(candidate.get("invalid_count", -1)) > thresholds["invalid_max_count"]:
        failures.append("invalid_count")
    if failures:
        return {"status": "FAIL", "hard_failures": failures, "warnings": []}

    audit_validator = Draft202012Validator(
        {"$ref": "#/$defs/aggregateReceipt", "$defs": _AUDIT_SCHEMA["$defs"]}
    )
    if audit.get("status") == "complete" and list(audit_validator.iter_errors(audit)):
        raise ValueError("audit aggregate receipt schema mismatch")
    if audit.get("status") != "complete":
        return {"status": "BLOCKED", "hard_failures": [], "warnings": [], "reason": "incomplete_audit"}
    candidate_run = candidate.get("candidate_run_sha256")
    if not isinstance(candidate_run, str) or not re.fullmatch(r"[a-f0-9]{64}", candidate_run):
        raise ValueError("candidate run hash is missing or invalid")
    if audit.get("candidate_run_sha256") != candidate_run:
        return {
            "status": "BLOCKED", "hard_failures": [], "warnings": [],
            "reason": "audit_candidate_mismatch",
        }
    audited = int(audit.get("audited_count", -1))
    unsupported = int(audit.get("unsupported_count", -1))
    if audited < thresholds["audit_min_count"]:
        return {"status": "BLOCKED", "hard_failures": [], "warnings": [], "reason": "insufficient_audit_evidence"}
    if audited != e_predicted:
        return {"status": "BLOCKED", "hard_failures": [], "warnings": [], "reason": "audit_population_mismatch"}
    if int(audit.get("supported_count", -1)) + unsupported != audited:
        return {"status": "BLOCKED", "hard_failures": [], "warnings": [], "reason": "audit_count_mismatch"}
    if 100 * unsupported > thresholds["unsupported_max_percent"] * audited:
        failures.append("unsupported_evidence")

    m_predicted = int(money["predicted_positive"])
    m_tp = int(money["tp"])
    if (
        m_predicted < diagnostics["money_min_predicted_positive"]
        or m_tp < diagnostics["money_min_tp"]
        or (m_predicted and 100 * m_tp < diagnostics["money_precision_percent"] * m_predicted)
    ):
        warnings.append("money_regression")
    source_metrics = candidate.get("source_metrics", {})
    if not isinstance(source_metrics, Mapping):
        raise ValueError("candidate source_metrics must be an object")
    required_sources = diagnostics["required_sources"]
    if set(source_metrics) != set(required_sources):
        raise ValueError("candidate source diagnostics membership mismatch")
    for source, values in sorted(source_metrics.items()):
        if not isinstance(values, Mapping):
            raise ValueError("source metric must be an object")
        if "coverage" not in values or "invalid_count" not in values:
            raise ValueError(f"{source} source diagnostics are incomplete")
        if float(values.get("coverage", 0)) * 100 < diagnostics[
            "source_coverage_warning_percent"
        ]:
            warnings.append(f"{source}_coverage")
        if int(values.get("invalid_count", 0)):
            warnings.append(f"{source}_invalid")
        source_evidence = values.get("usable_evidence")
        if not isinstance(source_evidence, Mapping) or "predicted_positive" not in source_evidence:
            raise ValueError(f"{source} source evidence diagnostics are incomplete")
        if int(source_evidence["predicted_positive"]) < diagnostics[
            "source_precision_min_denominator"
        ]:
            warnings.append(f"{source}_evidence_denominator")

    status = "FAIL" if failures else "REVIEW_REQUIRED" if warnings else "PASS"
    return {
        "status": status,
        "hard_failures": failures,
        "warnings": warnings,
        "audited_count": audited,
        "unsupported_count": unsupported,
    }


def build_freeze_receipt(
    *,
    config_path: Path,
    baseline_root: Path,
    code_commit_sha: str,
) -> dict[str, object]:
    if not re.fullmatch(r"[a-f0-9]{40}", code_commit_sha):
        raise ValueError("code checkpoint must be a 40-character commit SHA")
    config_payload = config_path.read_bytes()
    config = _validate_gate_config(config_payload, baseline_root=baseline_root)
    baseline = config["baseline"]
    manifest = json.loads((baseline_root / "bundle-manifest.json").read_text())
    if manifest.get("bundle_sha256") != baseline["bundle_sha256"]:
        raise ValueError("baseline bundle changed before freeze")
    files = {
        relative: _digest_bytes((_ROOT / relative).read_bytes())
        for relative in GATE_IMPLEMENTATION_PATHS
    }
    receipt = {
        "schema_version": "calibration-gate-freeze/v1",
        "gate_id": config["gate_id"],
        "status": "frozen",
        "code_commit_sha": code_commit_sha,
        "baseline_implementation_bundle_sha256": baseline[
            "implementation_bundle_sha256"
        ],
        "baseline_bundle_sha256": baseline["bundle_sha256"],
        "baseline_metrics_sha256": baseline["metrics_sha256"],
        "config_sha256": _digest_bytes(config_payload),
        "implementation_files": dict(sorted(files.items())),
        "thresholds": config["thresholds"],
        "model_calls": 0,
    }
    validator = Draft202012Validator(
        {"$ref": "#/$defs/freezeReceipt", "$defs": _SCHEMA["$defs"]}
    )
    errors = list(validator.iter_errors(receipt))
    if errors:
        raise ValueError(f"freeze receipt schema failed: {errors[0].message}")
    return receipt


def _write_immutable(path: Path, value: object) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(
                f"refusing to overwrite existing receipt: {path}"
            ) from error
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _confirmed_checkpoint(repo_root: Path, expected: str) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    if head != expected:
        raise ValueError("requested code checkpoint does not match HEAD")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repo_root, check=True, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("tracked worktree must be clean before freeze")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count-aware extraction calibration gate")
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--config", type=Path, required=True)
    evaluate.add_argument("--baseline", type=Path, required=True)
    evaluate.add_argument("--candidate", type=Path, required=True)
    evaluate.add_argument("--audit", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--config", type=Path, required=True)
    freeze.add_argument("--baseline", type=Path, required=True)
    freeze.add_argument("--code-commit", required=True)
    freeze.add_argument("--output", type=Path, required=True)
    ingest = commands.add_parser("audit-ingest")
    ingest.add_argument("--root", type=Path, required=True)
    ingest.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "evaluate":
            config = load_gate_config(args.config, baseline_root=args.baseline)
            result = evaluate_gate(
                json.loads(args.candidate.read_text()),
                json.loads(args.audit.read_text()),
                config,
            )
        elif args.command == "audit-ingest":
            from src.extraction.calibration_audit import ingest_audit_submission

            result = ingest_audit_submission(args.root)
        else:
            _confirmed_checkpoint(_ROOT, args.code_commit)
            result = build_freeze_receipt(
                config_path=args.config,
                baseline_root=args.baseline, code_commit_sha=args.code_commit,
            )
        _write_immutable(args.output, result)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
