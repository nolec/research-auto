"""Explicit, one-shot development diagnostic. Exit 0 is measurement, not quality PASS."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from src.extraction import codex_cli_diagnostic as cli
from src.extraction.baseline_calibration import validate_artifact
from src.extraction.baseline_manifest import load_baseline_manifest
from src.extraction.baseline_provenance import build_implementation_bundle
from src.extraction.calibration_evaluator import evaluate_calibration
from src.extraction.calibration_gate import load_gate_config
from src.extraction.development_slice import (
    DevelopmentGoldSidecar, DevelopmentInference, ExtractionValidationError,
    build_development_gold_sidecar, build_development_inference, validate_extraction,
)

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "codex-cli-gpt-6-sol-metric-v1"
RUN_ROOT = ROOT / "artifacts/extraction/calibration/audit-local" / RUN_ID
PREFLIGHT_ROOT = cli.V5_CUSTODY_ROOT
APPROVED_PREFLIGHT_SHA256 = "6bc8874ddc936149b280dfda54f4ff33999ee011a391f09707c354169bb6afd1"
GATE_CONFIG_PATH = ROOT / "configs/extraction/calibration-gate-v1.json"
BASELINE_ROOT = ROOT / "artifacts/extraction/calibration/rule-v1/555d9a2e0881d2ea7d92b9882de34b7d6fa1a1d85ad9da616f28775f99acaa98"
SOURCES = ("github", "stackexchange", "steam", "ted")
STATES = ("valid_extraction", "valid_abstention", "invalid", "operational_failure",
          "attempt_started", "attempted_unknown", "not_attempted")
POLICY = {"input_count": 40, "max_model_processes": 40, "concurrency": 1,
          "wrapper_retries": 0, "timeout_seconds": 120, "max_run_seconds": 1800,
          "provider_retry_control": "UNAVAILABLE", "cost_limit_status": "UNENFORCED"}
EXIT_CODES = {"MEASURED": 0, "INCOMPLETE": 1, "PREREQUISITE_FAIL": 2,
              "ALREADY_CONSUMED": 2, "COMPLETED_NOT_EVALUABLE": 3, "STORAGE_FAILURE": 4}
_ERROR_CODES = frozenset({"CLI_OUTPUT_SCHEMA_INVALID", "CLI_DOCUMENT_ID_MISMATCH", "CLI_TIMEOUT",
    "CLI_NONZERO_EXIT", "CLI_ERROR_EVENT", "CLI_TERMINAL_EVENT_INVALID", "CLI_OUTPUT_MISSING",
    "CLI_TOOL_EVENT", "CLI_ISOLATION_VIOLATION", "CLI_INTERNAL_ERROR", "CLI_EXECUTABLE_NOT_FOUND"})


class MetricBlocked(RuntimeError):
    """Only fixed local error codes may cross the public boundary."""


@dataclass(frozen=True)
class Prepared:
    inference: DevelopmentInference
    gold: DevelopmentGoldSidecar
    prompt_bytes: bytes
    schema_bytes: bytes
    bindings: dict[str, str]
    baseline: dict[str, object]


def _digest(value: object) -> str:
    return cli._digest(value)


def _read(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise MetricBlocked("PREREQUISITE_INVALID")
    return value


def _run_receipt(inference: DevelopmentInference, outputs: list[dict]) -> dict:
    return {"variant_id": RUN_ID, "status": "success", "input_count": 40,
            "output_count": len(outputs), "output_sha256": _digest(tuple(outputs)),
            "inference_corpus_sha256": inference.receipt["inference_corpus_sha256"]}


def _load_baseline(inference, gold, manifest_hash):
    config = load_gate_config(GATE_CONFIG_PATH, baseline_root=BASELINE_ROOT)
    manifest = _read(BASELINE_ROOT / "bundle-manifest.json")
    names = {"preflight-receipt.json", "baseline-run-receipt.json", "baseline-metrics.json", "baseline-evaluation-receipt.json"}
    if set(manifest["files"]) != names or _digest(manifest["files"]) != manifest["bundle_sha256"]:
        raise MetricBlocked("BASELINE_BINDING_INVALID")
    values = {}
    for name in sorted(names):
        raw = (BASELINE_ROOT / name).read_bytes()
        if sha256(raw).hexdigest() != manifest["files"][name]:
            raise MetricBlocked("BASELINE_BINDING_INVALID")
        values[name] = json.loads(raw)
        validate_artifact(name, values[name])
    validate_artifact("bundle-manifest.json", manifest)
    evaluation = values["baseline-evaluation-receipt.json"]
    preflight = values["preflight-receipt.json"]
    metrics = values["baseline-metrics.json"]
    if (evaluation["inference_corpus_sha256"] != inference.receipt["inference_corpus_sha256"]
        or evaluation["gold_sidecar_sha256"] != gold.receipt["gold_sidecar_sha256"]
        or preflight["manifest_sha256"] != manifest_hash
        or evaluation["upstream_run_receipt_sha256"] != _digest(values["baseline-run-receipt.json"])
        or evaluation["metrics_sha256"] != _digest(metrics)):
        raise MetricBlocked("BASELINE_BINDING_INVALID")
    return ({k: metrics[k] for k in ("coverage", "metrics", "source_metrics")},
            {"baseline_bundle_sha256": config["baseline"]["bundle_sha256"],
             "baseline_metrics_sha256": config["baseline"]["metrics_sha256"],
             "evaluation_policy_sha256": sha256(GATE_CONFIG_PATH.read_bytes()).hexdigest()})


def prepare() -> Prepared:
    """Verify all custody and evaluator prerequisites before any model process or metric claim."""
    try:
        loaded = load_baseline_manifest(cli.BASELINE_PATH, repo_root=ROOT)
        inference = build_development_inference(loaded.sources)
        gold = build_development_gold_sidecar(loaded.sources)
        ids = [d["document_id"] for d in inference.corpus]
        quotas = {s: 10 for s in SOURCES}
        if (len(ids) != 40 or len(set(ids)) != 40 or ids != sorted(ids)
            or set(ids) != {r["document_id"] for r in gold.labels} or len(gold.labels) != 40
            or inference.receipt["selected_count"] != 40 or gold.receipt["selected_count"] != 40
            or _digest(inference.corpus) != inference.receipt["inference_corpus_sha256"]
            or _digest(gold.labels) != gold.receipt["gold_sidecar_sha256"]):
            raise MetricBlocked("MEMBERSHIP_INVALID")
        fields = {"document_id", "source", "title", "text", "published_at", "source_url"}
        if any(set(d) != fields or not isinstance(d["document_id"], str) or not isinstance(d["text"], str) for d in inference.corpus):
            raise MetricBlocked("INFERENCE_FIELDS_INVALID")
        if {s: sum(d["source"] == s for d in inference.corpus) for s in SOURCES} != quotas:
            raise MetricBlocked("SOURCE_QUOTA_INVALID")
        for receipt in (inference.receipt, gold.receipt):
            if receipt["source_counts"] != quotas or receipt["packet_validation"] != "PASS":
                raise MetricBlocked("SOURCE_QUOTA_INVALID")
        if inference.receipt["source_spike_reserved_emitted"] != 0:
            raise MetricBlocked("MEMBERSHIP_INVALID")
        for key in ("source_dataset_sha256", "source_qualification_sha256", "source_packet_manifest_sha256"):
            if inference.receipt[key] != gold.receipt[key]:
                raise MetricBlocked("SOURCE_BINDING_INVALID")
        for row in gold.labels:
            if any(type(row[k]) is not bool for k in ("problem_signal", "money_signal", "usable_evidence", "noise")):
                raise MetricBlocked("GOLD_INVALID")
        prompt = cli.PROMPT_PATH.read_bytes()
        schema = cli.SCHEMA_PATH.read_bytes()
        schema_value = json.loads(schema)
        Draft202012Validator.check_schema(schema_value)
        raw = (PREFLIGHT_ROOT / "preflight.receipt.json").read_bytes()
        if sha256(raw).hexdigest() != APPROVED_PREFLIGHT_SHA256:
            raise MetricBlocked("PREFLIGHT_HASH_INVALID")
        preflight = json.loads(raw)
        claim = _read(PREFLIGHT_ROOT / "preflight.claim.json")
        expected = {"diagnostic_version": "codex-cli-gpt-6-sol-preflight-v5", "execution_mode": "preflight_only",
                    "requested_model": cli.MODEL, "model_binding": "explicit_cli_argument",
                    "prompt_sha256": sha256(prompt).hexdigest(), "output_schema_sha256": sha256(schema).hexdigest(),
                    "baseline_manifest_sha256": loaded.receipt["manifest_sha256"],
                    "inference_corpus_sha256": inference.receipt["inference_corpus_sha256"],
                    "gold_sidecar_sha256": gold.receipt["gold_sidecar_sha256"]}
        if (preflight["status"] != "PREFLIGHT_PASS" or preflight["output_contract_valid"] is not True
            or preflight["abstained"] is not False or preflight["positive_sanity_valid"] is not True
            or preflight["claim_sha256"] != _digest(claim)
            or any(preflight.get(k) != v for k, v in claim.items())
            or any(claim.get(k) != v for k, v in expected.items())):
            raise MetricBlocked("PREFLIGHT_BINDING_INVALID")
        version = cli.subprocess.run(["codex", "--version"], capture_output=True, text=True,
                                     timeout=10, check=True).stdout.strip()
        if version != claim["cli_version"]:
            raise MetricBlocked("CLI_VERSION_CHANGED")
        # Full abstention fixtures verify membership, hashes and label types, without model calls.
        probes = [{**{k: None for k in schema_value["required"]}, "document_id": d["document_id"],
                   "abstention_reason": "offline compatibility probe"} for d in inference.corpus]
        for doc, result in zip(inference.corpus, probes, strict=True):
            Draft202012Validator(schema_value).validate(result)
            validate_extraction(doc, result)
        evaluate_calibration(inference, gold, probes, _run_receipt(inference, probes))
        baseline, baseline_bindings = _load_baseline(inference, gold, loaded.receipt["manifest_sha256"])
        implementation = build_implementation_bundle(ROOT, [Path(__file__), Path(cli.__file__),
            ROOT / "src/extraction/calibration_evaluator.py", ROOT / "src/extraction/development_slice.py",
            ROOT / "src/extraction/baseline_manifest.py", ROOT / "src/extraction/baseline_calibration.py",
            ROOT / "src/extraction/baseline_provenance.py", ROOT / "src/extraction/calibration_gate.py",
            ROOT / "schemas/baseline-calibration-artifacts.schema.json"])
        bindings = {**{k: v for k, v in expected.items() if k.endswith("_sha256")}, **baseline_bindings,
                    "preflight_receipt_sha256": sha256(raw).hexdigest(), "preflight_claim_sha256": _digest(claim),
                    "ordered_ids_sha256": _digest(ids), "implementation_bundle_sha256": implementation["implementation_bundle_sha256"],
                    "policy_sha256": _digest(POLICY)}
        return Prepared(inference, gold, prompt, schema, bindings, baseline)
    except MetricBlocked:
        raise
    except Exception:
        raise MetricBlocked("PREREQUISITE_INVALID") from None


def _save_progress(root: Path, progress: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".progress-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(progress, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, root / "progress.json")
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _counts(rows: list[dict], *, project_unknown: bool = False) -> dict[str, int]:
    if len(rows) != 40 or [r["ordinal"] for r in rows] != list(range(1, 41)):
        raise MetricBlocked("PROGRESS_INVALID")
    result = {s: 0 for s in STATES}
    for row in rows:
        state = row["state"]
        if project_unknown and state == "attempt_started":
            state = "attempted_unknown"
        if state not in result:
            raise MetricBlocked("PROGRESS_INVALID")
        result[state] += 1
    return result


def _blank_rows():
    return [{"ordinal": n, "state": "not_attempted", "error_code": None,
             "elapsed_seconds": 0.0, "token_usage": {}} for n in range(1, 41)]


def _report(status, reason, rows, bindings, evaluation_status="INCOMPLETE", evaluation_reason="RUN_INCOMPLETE", evaluation=None):
    counts = _counts(rows, project_unknown=True)
    attempted = 40 - counts["not_attempted"]
    totals = {}
    missing = 0
    for row in rows:
        if row["state"] == "not_attempted":
            continue
        usage = row["token_usage"]
        missing += not all(k in usage for k in ("input_tokens", "output_tokens"))
        for key, value in usage.items():
            totals[key] = totals.get(key, 0) + value
    result = {"schema_version": "codex-cli-metric-receipt/v1", "run_id": RUN_ID, "status": status,
            "reason": reason, "input_count": 40, "counts": counts, "local_attempt_count": attempted,
            "bindings": bindings, "evaluation_status": evaluation_status, "evaluation_reason": evaluation_reason,
            "evaluation": evaluation, "token_usage": totals, "unobserved_usage_calls": missing,
            "usage_status": "OBSERVED" if attempted and missing == 0 else "PARTIAL" if totals else "UNAVAILABLE",
            "requested_model": cli.MODEL, "model_binding": "explicit_cli_argument", "resolved_model": "UNAVAILABLE",
            "provider_request_count": "UNAVAILABLE", "cost_status": "UNAVAILABLE",
            "quality_gate_status": "NOT_EVALUATED", "opportunity_card_status": "NOT_EVALUATED"}
    terminal = [cli._safe_terminal_metadata(row["terminal_diagnostics"]) for row in rows
                if isinstance(row.get("terminal_diagnostics"), dict)]
    if terminal:
        # No document identifiers or row ordinals enter the public summary.
        result["terminal_diagnostics"] = terminal
    return result


def _publish_receipt(root: Path, receipt: dict) -> None:
    """Publish complete JSON atomically, without replacing any existing terminal evidence."""
    fd, name = tempfile.mkstemp(prefix=".receipt-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, root / "metric.receipt.json")
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read_terminal(path: Path) -> dict:
    value = _read(path)
    expected_keys = set(_report("INCOMPLETE", "NO_TERMINAL_RECEIPT", _blank_rows(), {}))
    counts = value.get("counts")
    status = value.get("status")
    if (set(value) - {"terminal_diagnostics"} != expected_keys or value.get("schema_version") != "codex-cli-metric-receipt/v1"
        or value.get("run_id") != RUN_ID or value.get("input_count") != 40
        or status not in ("MEASURED", "INCOMPLETE", "COMPLETED_NOT_EVALUABLE")
        or value.get("reason") not in ("COMPLETE", "RUN_DEADLINE", "OPERATIONAL_FAILURE")
        or not isinstance(counts, dict) or set(counts) != set(STATES)
        or any(type(n) is not int or n < 0 for n in counts.values())
        or sum(counts.values()) != 40 or counts["attempt_started"] != 0
        or value.get("local_attempt_count") != 40 - counts["not_attempted"]):
        raise MetricBlocked("TERMINAL_RECEIPT_INVALID")
    if "terminal_diagnostics" in value:
        terminal = value["terminal_diagnostics"]
        if (not isinstance(terminal, list) or not 1 <= len(terminal) <= 40
            or any(not isinstance(item, dict) or set(item) != {
                "reason_detail", "completed_agent_message_count", "non_string_message_detected"
            } or type(item.get("completed_agent_message_count")) not in (int, type(None))
                or type(item.get("non_string_message_detected")) not in (bool, type(None))
                or item != cli._safe_terminal_metadata(item) for item in terminal)):
            raise MetricBlocked("TERMINAL_RECEIPT_INVALID")
    expected_evaluation = {"MEASURED": "EVALUATED", "INCOMPLETE": "INCOMPLETE",
                           "COMPLETED_NOT_EVALUABLE": "NOT_EVALUABLE"}[status]
    if (value.get("evaluation_status") != expected_evaluation
        or (status == "MEASURED" and not isinstance(value.get("evaluation"), dict))
        or (status != "MEASURED" and value.get("evaluation") is not None)):
        raise MetricBlocked("TERMINAL_RECEIPT_INVALID")
    return value


def inspect_run() -> dict:
    """Read-only projection; no automatic resume or modification of orphaned evidence."""
    receipt = RUN_ROOT / "metric.receipt.json"
    reason = "NO_TERMINAL_RECEIPT"
    if receipt.is_file():
        try:
            return _read_terminal(receipt)
        except (OSError, ValueError, TypeError, KeyError, MetricBlocked):
            reason = "TERMINAL_RECEIPT_INVALID"
    progress = RUN_ROOT / "progress.json"
    if progress.is_file():
        value = _read(progress)
        return _report("INCOMPLETE", reason, value["rows"], value["bindings"])
    return _report("INCOMPLETE", reason, _blank_rows(), {})


def run_metric() -> dict:
    if RUN_ROOT.exists() or RUN_ROOT.is_symlink():
        raise MetricBlocked("ALREADY_CONSUMED")
    prepared = prepare()
    RUN_ROOT.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        RUN_ROOT.mkdir(mode=0o700)
    except FileExistsError:
        raise MetricBlocked("ALREADY_CONSUMED") from None
    claim = {"schema_version": "codex-cli-metric-claim/v1", "run_id": RUN_ID,
             "policy": POLICY, "bindings": prepared.bindings, "raw_output_persisted": False}
    rows = _blank_rows()
    progress = {"schema_version": "codex-cli-metric-progress/v1", "claim_sha256": _digest(claim),
                "bindings": prepared.bindings, "rows": rows}
    try:
        cli._private_create(RUN_ROOT / "metric.claim.json", claim)
        _save_progress(RUN_ROOT, progress)
        started = time.monotonic()
        outputs = []
        stopped = False
        reason = "COMPLETE"
        validator = Draft202012Validator(json.loads(prepared.schema_bytes))
        for row, document in zip(rows, prepared.inference.corpus, strict=True):
            remaining = POLICY["max_run_seconds"] - (time.monotonic() - started)
            if remaining <= 0:
                stopped, reason = True, "RUN_DEADLINE"
                break
            row["state"] = "attempt_started"
            _save_progress(RUN_ROOT, progress)
            call_started = time.monotonic()
            remaining = POLICY["max_run_seconds"] - (call_started - started)
            if remaining <= 0:
                # The start marker was durable, but no model process was launched.
                row["state"] = "not_attempted"
                _save_progress(RUN_ROOT, progress)
                stopped, reason = True, "RUN_DEADLINE"
                break
            usage = {}
            try:
                result = cli.run_document(dict(document), schema_path=cli.SCHEMA_PATH,
                    prompt_text=prepared.prompt_bytes.decode("utf-8"), schema_bytes=prepared.schema_bytes,
                    timeout=min(POLICY["timeout_seconds"], remaining), usage_out=usage)
                validator.validate(result)
                validate_extraction(document, result)
                outputs.append(result)
                row["state"] = "valid_abstention" if result["abstention_reason"] is not None else "valid_extraction"
            except cli.CliContractError as error:
                code = str(error)
                row["error_code"] = code if code in _ERROR_CODES else "CLI_INTERNAL_ERROR"
                terminal = error.diagnostics.get("terminal_diagnostics")
                if isinstance(terminal, dict):
                    row["terminal_diagnostics"] = cli._safe_terminal_metadata(terminal)
                validation = error.diagnostics.get("validation")
                if isinstance(validation, dict) and validation.get("stage") in ("json_decode", "object_shape", "json_schema", "semantic"):
                    row["state"] = "invalid"
                    row["validation"] = cli._safe_validation_metadata(validation)
                else:
                    row["state"] = "operational_failure"
                    stopped, reason = True, "OPERATIONAL_FAILURE"
            except (ValidationError, ExtractionValidationError):
                row["state"], row["error_code"] = "invalid", "CLI_OUTPUT_SCHEMA_INVALID"
            except Exception:
                row["state"], row["error_code"] = "operational_failure", "CLI_INTERNAL_ERROR"
                stopped, reason = True, "OPERATIONAL_FAILURE"
            row["elapsed_seconds"] = round(max(0.0, time.monotonic() - call_started), 3)
            row["token_usage"] = {k: v for k, v in usage.items() if k in ("input_tokens", "output_tokens") and type(v) is int and v >= 0}
            _save_progress(RUN_ROOT, progress)
            if stopped:
                break
        if stopped:
            receipt = _report("INCOMPLETE", reason, rows, prepared.bindings)
        elif any(r["state"] == "invalid" for r in rows):
            # The CLI has discarded invalid raw rows; do not fabricate evaluator inputs.
            receipt = _report("COMPLETED_NOT_EVALUABLE", "COMPLETE", rows, prepared.bindings,
                              "NOT_EVALUABLE", "INVALID_OUTPUT_NOT_RETAINED")
        else:
            try:
                report = evaluate_calibration(prepared.inference, prepared.gold, outputs,
                                              _run_receipt(prepared.inference, outputs))
                evaluation = {"metrics": report.metrics, "source_metrics": report.source_metrics,
                              "coverage": report.coverage, "abstention_count": report.abstention_count,
                              "invalid_count": report.invalid_count, "receipt": report.receipt,
                              "baseline": prepared.baseline}
                receipt = _report("MEASURED", "COMPLETE", rows, prepared.bindings, "EVALUATED", None, evaluation)
            except Exception:
                receipt = _report("COMPLETED_NOT_EVALUABLE", "COMPLETE", rows, prepared.bindings,
                                  "NOT_EVALUABLE", "EVALUATOR_REJECTED")
        _publish_receipt(RUN_ROOT, receipt)
        return receipt
    except OSError:
        # The last durable start marker remains unknown; never overwrite it with invented success.
        durable = inspect_run()
        durable.update(status="STORAGE_FAILURE", reason="STORAGE_WRITE_FAILED")
        return durable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--execute", action="store_true", help="Consume the one-shot 40-record metric claim.")
    action.add_argument("--inspect", action="store_true", help="Read saved accounting without model calls or resume.")
    args = parser.parse_args(argv)
    try:
        result = run_metric() if args.execute else inspect_run()
    except MetricBlocked as error:
        result = {"run_id": RUN_ID, "status": "ALREADY_CONSUMED" if str(error) == "ALREADY_CONSUMED" else "PREREQUISITE_FAIL",
                  "reason": str(error) if str(error) in {"ALREADY_CONSUMED", "PREREQUISITE_INVALID", "MEMBERSHIP_INVALID", "INFERENCE_FIELDS_INVALID", "SOURCE_QUOTA_INVALID", "SOURCE_BINDING_INVALID", "GOLD_INVALID", "PREFLIGHT_HASH_INVALID", "PREFLIGHT_BINDING_INVALID", "CLI_VERSION_CHANGED", "BASELINE_BINDING_INVALID", "PROGRESS_INVALID"} else "PREREQUISITE_INVALID"}
    except KeyboardInterrupt:
        result = inspect_run()
    except Exception:
        result = {"run_id": RUN_ID, "status": "STORAGE_FAILURE", "reason": "STORAGE_READ_FAILED"}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
