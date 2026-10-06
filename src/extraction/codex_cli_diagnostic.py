"""One-shot, extraction-only Codex CLI diagnostic with aggregate local custody."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator, ValidationError

from src.extraction.baseline_manifest import load_baseline_manifest
from src.extraction.calibration_evaluator import evaluate_calibration
from src.extraction.development_slice import (
    build_development_gold_sidecar,
    build_development_inference,
    validate_extraction,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/model-extraction-output.schema.json"
PROMPT_PATH = ROOT / "configs/extraction/prompts/problem-evidence-v1.txt"
BASELINE_PATH = ROOT / "configs/extraction/development-baseline-v1.json"
CUSTODY_ROOT = ROOT / "artifacts/extraction/calibration/audit-local/codex-cli-gpt-6-sol-v1"
MODEL = "gpt-6-sol"
MAX_DOCUMENT_SECONDS = 120
MAX_RUN_SECONDS = 1800


class CliContractError(RuntimeError):
    """A stable, non-sensitive classification for a failed CLI contract."""

    def __init__(
        self, reason: str, *, returncode: int | None = None,
        failure_stage: str = "contract_validation", error_class: str = "UNKNOWN",
    ) -> None:
        super().__init__(reason)
        stages = {
            "contract_validation", "subprocess_launch", "subprocess_timeout",
            "subprocess_exit", "isolation_check", "preflight", "evaluation",
        }
        classes = {
            "UNKNOWN", "TIMEOUT", "EXECUTABLE_NOT_FOUND", "PERMISSION_ERROR",
            "OPERATIONAL_ERROR", "ARGUMENT_ERROR", "AUTHENTICATION_ERROR",
            "MODEL_UNAVAILABLE", "NETWORK_ERROR", "INTERNAL_ERROR",
        }
        self.diagnostics = {
            "returncode": returncode if type(returncode) is int else None,
            "failure_stage": failure_stage if failure_stage in stages else "contract_validation",
            "error_class": error_class if error_class in classes else "UNKNOWN",
        }


def _classify_cli_stderr(stderr: str) -> str:
    """Classify explicit error lines; warnings alone do not establish a failure cause."""
    lines = [line.strip().lower() for line in stderr.splitlines()]
    errors = "\n".join(line for line in lines if line.startswith(("error:", "error ", "fatal:")))
    patterns = (
        ("ARGUMENT_ERROR", ("unexpected argument", "unrecognized option", "invalid value")),
        ("AUTHENTICATION_ERROR", ("authentication failed", "unauthorized", "not logged in")),
        ("MODEL_UNAVAILABLE", ("model is not supported", "model not found", "unsupported model")),
        ("NETWORK_ERROR", ("connection refused", "error sending request", "failed to send request")),
        ("PERMISSION_ERROR", ("permission denied", "operation not permitted")),
    )
    for classification, markers in patterns:
        if any(marker in errors for marker in markers):
            return classification
    return "UNKNOWN"


def _failure_diagnostics(error: Exception, stage: str) -> dict[str, object]:
    if isinstance(error, CliContractError):
        return dict(error.diagnostics)
    return {"returncode": None, "failure_stage": stage, "error_class": "INTERNAL_ERROR"}


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _capture_usage(stdout: str | bytes | None, usage_out: dict[str, int] | None) -> None:
    if usage_out is None or stdout is None:
        return
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        for field in ("input_tokens", "output_tokens"):
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                usage_out[field] = value


def _private_create(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        raise


class CliCustody:
    def __init__(self, claim_path: Path, receipt_path: Path) -> None:
        self.claim_path = claim_path
        self.receipt_path = receipt_path

    def claim(self, value: Mapping[str, object]) -> None:
        try:
            _private_create(self.claim_path, value)
        except FileExistsError as error:
            raise CliContractError("ALREADY_CONSUMED") from error

    def publish(self, value: Mapping[str, object]) -> None:
        try:
            _private_create(self.receipt_path, value)
        except FileExistsError as error:
            raise CliContractError("TERMINAL_RECEIPT_EXISTS") from error


def parse_cli_events(
    stdout: str, document: Mapping[str, object], *,
    schema: Mapping[str, object] | None = None,
    usage_out: dict[str, int] | None = None,
) -> dict[str, object]:
    terminal_count = 0
    messages: list[str] = []
    saw_error = False
    _capture_usage(stdout, usage_out)
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (TypeError, ValueError) as error:
            raise CliContractError("CLI_TERMINAL_EVENT_INVALID") from error
        if not isinstance(event, dict):
            raise CliContractError("CLI_TERMINAL_EVENT_INVALID")
        kind = event.get("type")
        if kind in {"error", "turn.failed"}:
            saw_error = True
        if kind == "turn.completed":
            terminal_count += 1
        if kind in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, dict):
                raise CliContractError("CLI_TERMINAL_EVENT_INVALID")
            item_type = item.get("type")
            if item_type in {"command_execution", "file_change", "mcp_tool_call", "web_search", "tool_call"}:
                raise CliContractError("CLI_TOOL_EVENT")
            if item_type not in {"agent_message", "reasoning"}:
                raise CliContractError("CLI_TOOL_EVENT")
            if kind == "item.completed" and item_type == "agent_message":
                message = item.get("text")
                if not isinstance(message, str):
                    raise CliContractError("CLI_OUTPUT_MISSING")
                messages.append(message)
        elif kind not in {"thread.started", "turn.started", "turn.completed", "error", "turn.failed"}:
            raise CliContractError("CLI_TERMINAL_EVENT_INVALID")
    if saw_error:
        raise CliContractError("CLI_ERROR_EVENT")
    if terminal_count != 1:
        raise CliContractError("CLI_TERMINAL_EVENT_INVALID")
    if len(messages) != 1:
        raise CliContractError("CLI_OUTPUT_MISSING")
    try:
        output = json.loads(messages[0])
    except (TypeError, ValueError) as error:
        raise CliContractError("CLI_OUTPUT_SCHEMA_INVALID") from error
    if not isinstance(output, dict):
        raise CliContractError("CLI_OUTPUT_SCHEMA_INVALID")
    if schema is not None:
        try:
            Draft202012Validator(schema).validate(output)
        except ValidationError as error:
            raise CliContractError("CLI_OUTPUT_SCHEMA_INVALID") from error
    if output.get("document_id") != document.get("document_id"):
        raise CliContractError("CLI_DOCUMENT_ID_MISMATCH")
    try:
        validate_extraction(document, output)
    except (TypeError, ValueError, ValidationError) as error:
        raise CliContractError("CLI_OUTPUT_SCHEMA_INVALID") from error
    return output


def run_document(
    document: Mapping[str, object], *, schema_path: Path, prompt_text: str, timeout: float,
    schema_bytes: bytes | None = None, usage_out: dict[str, int] | None = None,
) -> dict[str, object]:
    if schema_bytes is None and not schema_path.is_file():
        raise CliContractError("CLI_SCHEMA_MISSING")
    try:
        frozen_schema = schema_bytes if schema_bytes is not None else schema_path.read_bytes()
        schema = json.loads(frozen_schema.decode("utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, TypeError) as error:
        raise CliContractError("CLI_SCHEMA_INVALID") from error
    source = {field: document[field] for field in (
        "document_id", "source", "title", "text", "published_at"
    )}
    request = prompt_text + "\n\nSource document JSON:\n" + json.dumps(
        source, ensure_ascii=False, separators=(",", ":")
    )
    with tempfile.TemporaryDirectory(prefix="codex-cli-diagnostic-") as directory:
        frozen_schema_path = Path(directory) / "schema.json"
        frozen_schema_path.write_bytes(frozen_schema)
        work_dir = Path(directory) / "work"
        work_dir.mkdir()
        command = [
            "codex", "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--strict-config", "--json", "--output-schema", str(frozen_schema_path),
            "--model", MODEL, "--sandbox", "read-only", "--cd", str(work_dir),
            "--skip-git-repo-check", "-",
        ]
        try:
            completed = subprocess.run(
                command, input=request, capture_output=True, text=True,
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as error:
            _capture_usage(error.stdout, usage_out)
            raise CliContractError(
                "CLI_TIMEOUT", failure_stage="subprocess_timeout", error_class="TIMEOUT",
            ) from error
        except OSError as error:
            classification = (
                "EXECUTABLE_NOT_FOUND" if isinstance(error, FileNotFoundError)
                else "PERMISSION_ERROR" if isinstance(error, PermissionError)
                else "OPERATIONAL_ERROR"
            )
            raise CliContractError(
                "CLI_OPERATIONAL_ERROR", failure_stage="subprocess_launch", error_class=classification,
            ) from error
        _capture_usage(completed.stdout, usage_out)
        if any(work_dir.iterdir()):
            raise CliContractError("CLI_ISOLATION_VIOLATION", failure_stage="isolation_check")
        if completed.returncode != 0:
            raise CliContractError(
                "CLI_NONZERO_EXIT", returncode=completed.returncode,
                failure_stage="subprocess_exit", error_class=_classify_cli_stderr(completed.stderr),
            )
        return parse_cli_events(completed.stdout, document, schema=schema, usage_out=usage_out)


def _claim_base(
    *, kind: str, cli_version: str, manifest_hash: str, corpus_hash: str,
    gold_hash: str, prompt_bytes: bytes, schema_bytes: bytes,
) -> dict[str, object]:
    return {
        "schema_version": "codex-cli-extraction-claim/v1",
        "kind": kind,
        "provider": "codex_cli",
        "requested_model": MODEL,
        "model_binding": "explicit_argument_server_accepted",
        "resolved_model": "UNAVAILABLE",
        "cli_version": cli_version,
        "baseline_manifest_sha256": manifest_hash,
        "inference_corpus_sha256": corpus_hash,
        "gold_sidecar_sha256": gold_hash,
        "prompt_sha256": sha256(prompt_bytes).hexdigest(),
        "output_schema_sha256": sha256(schema_bytes).hexdigest(),
        "command_contract_sha256": _digest({
            "model": MODEL, "sandbox": "read-only", "ephemeral": True,
            "ignore_user_config": True, "ignore_rules": True, "retry": 0,
            "timeout_seconds": MAX_DOCUMENT_SECONDS,
        }),
        "raw_output_persisted": False,
        "source_text_persisted": False,
    }


def run_diagnostic() -> dict[str, object]:
    """Run one synthetic preflight, then one 40-document metric run."""
    manifest = load_baseline_manifest(BASELINE_PATH, repo_root=ROOT)
    inference = build_development_inference(manifest.sources)
    gold = build_development_gold_sidecar(manifest.sources)
    if len(inference.corpus) != 40 or len(gold.labels) != 40:
        raise CliContractError("CANONICAL_MEMBERSHIP_INVALID")
    try:
        version = subprocess.run(
            ["codex", "--version"], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise CliContractError("CLI_PREREQUISITE_FAIL") from error
    prompt_bytes = PROMPT_PATH.read_bytes()
    schema_bytes = SCHEMA_PATH.read_bytes()
    prompt_text = prompt_bytes.decode("utf-8")
    manifest_hash = str(manifest.receipt["manifest_sha256"])
    corpus_hash = str(inference.receipt["inference_corpus_sha256"])
    gold_hash = str(gold.receipt["gold_sidecar_sha256"])
    preflight = CliCustody(
        CUSTODY_ROOT / "preflight.claim.json", CUSTODY_ROOT / "preflight.receipt.json"
    )
    preflight_claim = _claim_base(
        kind="preflight", cli_version=version, manifest_hash=manifest_hash,
        corpus_hash=corpus_hash, gold_hash=gold_hash,
        prompt_bytes=prompt_bytes, schema_bytes=schema_bytes,
    )
    preflight.claim(preflight_claim)
    synthetic = {
        "document_id": "preflight:codex-cli-gpt-6-sol-v1",
        "source": "github",
        "title": "Synthetic export failure",
        "text": "The scheduled export fails before producing a file.",
        "published_at": "2026-01-01T00:00:00Z",
        "source_url": "https://research-auto.local/preflight",
    }
    preflight_usage: dict[str, int] = {}
    try:
        check = run_document(
            synthetic, schema_path=SCHEMA_PATH, prompt_text=prompt_text,
            timeout=MAX_DOCUMENT_SECONDS, schema_bytes=schema_bytes,
            usage_out=preflight_usage,
        )
        if check.get("problem_signal") is not True or check.get("usable_evidence") is not True:
            raise CliContractError("CLI_SEMANTIC_SANITY_FAIL")
    except Exception as error:
        receipt = {
            **preflight_claim, "status": "PREFLIGHT_BLOCKED",
            "reason": str(error) if isinstance(error, CliContractError) else "CLI_INTERNAL_ERROR",
            "process_diagnostics": _failure_diagnostics(error, "preflight"),
            "claim_sha256": _digest(preflight_claim), "process_count": 1,
            "usage_status": "OBSERVED" if preflight_usage else "UNAVAILABLE",
            "token_usage": preflight_usage,
            "cost_status": "UNAVAILABLE",
        }
        preflight.publish(receipt)
        return receipt
    preflight_receipt = {
        **preflight_claim, "status": "PREFLIGHT_PASS", "reason": "contract_valid",
        "claim_sha256": _digest(preflight_claim), "process_count": 1,
        "usage_status": "OBSERVED" if preflight_usage else "UNAVAILABLE",
        "token_usage": preflight_usage,
        "cost_status": "UNAVAILABLE",
    }
    preflight.publish(preflight_receipt)
    metric = CliCustody(CUSTODY_ROOT / "metric.claim.json", CUSTODY_ROOT / "metric.receipt.json")
    metric_claim = _claim_base(
        kind="metric", cli_version=version, manifest_hash=manifest_hash,
        corpus_hash=corpus_hash, gold_hash=gold_hash,
        prompt_bytes=prompt_bytes, schema_bytes=schema_bytes,
    )
    metric_claim["preflight_receipt_sha256"] = _digest(preflight_receipt)
    metric.claim(metric_claim)
    started = time.monotonic()
    outputs: list[dict[str, object]] = []
    usage_totals: dict[str, int] = {}
    reason = "complete"
    try:
        for document in inference.corpus:
            remaining = MAX_RUN_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise CliContractError("CLI_RUN_TIMEOUT")
            document_usage: dict[str, int] = {}
            try:
                output = run_document(
                    document, schema_path=SCHEMA_PATH, prompt_text=prompt_text,
                    timeout=min(MAX_DOCUMENT_SECONDS, remaining), schema_bytes=schema_bytes,
                    usage_out=document_usage,
                )
            finally:
                for field, count in document_usage.items():
                    usage_totals[field] = usage_totals.get(field, 0) + count
            outputs.append(output)
        output_tuple = tuple(outputs)
        run_receipt = {
            "variant_id": "codex_cli_gpt_6_sol_v1",
            "status": "success",
            "inference_corpus_sha256": corpus_hash,
            "input_count": len(inference.corpus),
            "output_count": len(output_tuple),
            "output_sha256": _digest(output_tuple),
        }
        report = evaluate_calibration(inference, gold, output_tuple, run_receipt)
        receipt = {
            **metric_claim,
            "status": "MEASURED",
            "reason": reason,
            "claim_sha256": _digest(metric_claim),
            "input_count": 40,
            "terminal_output_count": len(output_tuple),
            "metrics": report.metrics,
            "source_metrics": report.source_metrics,
            "coverage": report.coverage,
            "abstention_count": report.abstention_count,
            "invalid_count": report.invalid_count,
            "usage_status": "OBSERVED" if usage_totals else "UNAVAILABLE",
            "token_usage": usage_totals,
            "cost_status": "UNAVAILABLE",
            "opportunity_card_status": "NOT_EVALUATED",
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as error:
        receipt = {
            **metric_claim,
            "status": "TERMINAL_FAILURE",
            "reason": str(error) if isinstance(error, CliContractError) else "EVALUATION_INTERNAL_ERROR",
            "process_diagnostics": _failure_diagnostics(error, "evaluation"),
            "claim_sha256": _digest(metric_claim),
            "input_count": 40,
            "terminal_output_count": len(outputs),
            "usage_status": "OBSERVED" if usage_totals else "UNAVAILABLE",
            "token_usage": usage_totals,
            "cost_status": "UNAVAILABLE",
            "opportunity_card_status": "NOT_EVALUATED",
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    metric.publish(receipt)
    return receipt


def main() -> int:
    try:
        result = run_diagnostic()
    except Exception as error:
        result = {
            "status": "DIAGNOSTIC_BLOCKED",
            "reason": str(error) if isinstance(error, CliContractError) else "CLI_INTERNAL_ERROR",
            "process_diagnostics": _failure_diagnostics(error, "preflight"),
        }
    summary = {
        "status": result["status"], "reason": result["reason"],
        "terminal_output_count": result.get("terminal_output_count", 0),
    }
    if "process_diagnostics" in result:
        summary["process_diagnostics"] = result["process_diagnostics"]
    print(json.dumps(summary, sort_keys=True))
    return 0 if result["status"] == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
