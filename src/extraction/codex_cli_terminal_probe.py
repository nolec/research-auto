"""One-shot first-document diagnosis; no metric run, retry, or product-quality claim."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from src.extraction import codex_cli_diagnostic as cli
from src.extraction import codex_cli_metric as metric
from src.extraction.development_slice import validate_extraction

RUN_ID = "codex-cli-gpt-6-sol-terminal-probe-v2"
PROBE_ROOT = metric.RUN_ROOT.parent / RUN_ID
V1_PROBE_ROOT = metric.RUN_ROOT.parent / "codex-cli-gpt-6-sol-terminal-probe-v1"
METRIC_ROOT = metric.RUN_ROOT
HISTORY_ROOTS = (cli.CUSTODY_ROOT, cli.V2_CUSTODY_ROOT, cli.V3_CUSTODY_ROOT,
                 cli.V4_CUSTODY_ROOT, cli.V5_CUSTODY_ROOT, V1_PROBE_ROOT, METRIC_ROOT)
SOURCE_HASHES = {
    "metric.claim.json": "f5a682c607bfcae806e3ac93d36cffa9e3d9b58cf34b91be8758e0fe8e422356",
    "metric.receipt.json": "eafda67d79cb3e8a66962eab202d5bae4bf3f3fba73a766d991add875dcaba79",
    "progress.json": "a5ea0ab5d4095a228bc1a48de100bd60f1d838a99f2977a1053e779834f7133d",
}
POLICY = {"max_local_model_processes": 1, "wrapper_retries": 0,
          "model_subprocess_timeout_seconds": 120, "total_workflow_timeout": "UNBOUNDED",
          "provider_request_count": "UNAVAILABLE", "provider_retry_control": "UNAVAILABLE",
          "cli_cost_ceiling": "UNENFORCED"}
MODEL_FIELDS = ("document_id", "source", "title", "text", "published_at")
OUTCOMES = {"NOT_REPRODUCED": 0, "REPRODUCED": 1, "OTHER_FAILURE": 2, "INCOMPLETE": 3, "BLOCKED": 4}
REASONS = metric._ERROR_CODES | {
    "CLI_OPERATIONAL_ERROR", "CLI_SCHEMA_MISSING", "CLI_SCHEMA_INVALID", "CONTRACT_VALID",
    "NO_TERMINAL_RECEIPT", "TERMINAL_RECEIPT_INVALID", "STORAGE_WRITE_FAILED",
    "PREREQUISITE_INVALID", "ALREADY_CONSUMED", "CLAIM_WRITE_FAILED",
}


@dataclass(frozen=True)
class Prepared:
    document: dict
    prompt_bytes: bytes
    schema_bytes: bytes
    bindings: dict
    history: dict


def inventory() -> dict:
    """Snapshot only historical regular files; never traverse links or write evidence."""
    result = {}
    for root in HISTORY_ROOTS:
        if root.is_symlink() or not root.is_dir():
            raise ValueError("history unavailable")
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("history link")
            if path.is_file():
                result[f"{root.name}/{path.relative_to(root)}"] = {
                    "sha256": sha256(path.read_bytes()).hexdigest(), "mode": path.stat().st_mode & 0o777,
                }
            elif not path.is_dir():
                raise ValueError("history special file")
    return result


def prepare() -> Prepared:
    history = inventory()
    originals = {}
    for name, expected in SOURCE_HASHES.items():
        raw = (METRIC_ROOT / name).read_bytes()
        if sha256(raw).hexdigest() != expected:
            raise ValueError("source hash mismatch")
        originals[name] = json.loads(raw)
    source_claim = originals["metric.claim.json"]
    source_receipt = originals["metric.receipt.json"]
    progress = originals["progress.json"]
    if (source_receipt["status"] != "INCOMPLETE" or source_receipt["local_attempt_count"] != 1
        or progress["claim_sha256"] != cli._digest(source_claim)
        or progress["rows"][0]["ordinal"] != 1
        or progress["rows"][0]["error_code"] != "CLI_OUTPUT_MISSING"):
        raise ValueError("source binding mismatch")
    # This prerequisite routine has no inference calls and does not consume metric custody.
    frozen = metric.prepare()
    docs = frozen.inference.corpus
    ids = [doc["document_id"] for doc in docs]
    expected = {
        "inference_corpus_sha256": cli._digest(docs), "ordered_ids_sha256": cli._digest(ids),
        "prompt_sha256": sha256(frozen.prompt_bytes).hexdigest(),
        "output_schema_sha256": sha256(frozen.schema_bytes).hexdigest(),
    }
    if len(docs) != 40 or any(
        frozen.bindings.get(k) != value or source_claim["bindings"].get(k) != value
        or source_receipt["bindings"].get(k) != value for k, value in expected.items()
    ):
        raise ValueError("frozen input drift")
    document = json.loads(json.dumps(docs[0]))
    if set(document) != set(MODEL_FIELDS) | {"source_url"}:
        raise ValueError("inference fields invalid")
    payload = {k: document[k] for k in MODEL_FIELDS}
    bindings = {**expected, "source_metric_claim_sha256": SOURCE_HASHES["metric.claim.json"],
                "source_metric_receipt_sha256": SOURCE_HASHES["metric.receipt.json"],
                "source_metric_progress_sha256": SOURCE_HASHES["progress.json"],
                "selected_document_sha256": cli._digest(document), "model_input_sha256": cli._digest(payload),
                "input_serialization": "UTF-8 canonical JSON; sorted keys; compact separators; ensure_ascii=false",
                "selected_ordinal": 1, "requested_model": cli.MODEL,
                "cli_version": "codex-cli 0.163.0-alpha.10.2",
                # metric.prepare checks the CLI version; host permissions are not probed.
                "execution_environment": {
                    "cli_version": "codex-cli 0.163.0-alpha.10.2",
                    "requested_sandbox": "read-only",
                    "host_sandbox": "UNKNOWN", "effective_permissions": "UNKNOWN",
                    "v1_environment_comparison": "UNKNOWN",
                    "error_class_semantics": "PATTERN_CLASSIFICATION_NOT_ROOT_CAUSE",
                },
                "implementation_bundle_sha256": cli._digest({
                    "metric_bundle_sha256": frozen.bindings["implementation_bundle_sha256"],
                    "probe_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                }), "policy_sha256": cli._digest(POLICY)}
    if inventory() != history:
        raise ValueError("history drift before claim")
    return Prepared(document, frozen.prompt_bytes, frozen.schema_bytes, bindings, history)


def _sync_directory() -> None:
    fd = os.open(PROBE_ROOT, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".receipt-", dir=PROBE_ROOT)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, PROBE_ROOT / "probe.receipt.json")
        _sync_directory()
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _result(status, reason, *, bindings=None, claim_hash=None, count=None, attempts=None, integrity="UNVERIFIED", usage=None):
    return {"schema_version": "codex-cli-terminal-probe-receipt/v1", "run_id": RUN_ID,
            "status": status, "reason": reason, "integrity": integrity,
            "bindings": bindings or {}, "claim_sha256": claim_hash,
            "local_model_process_count": 0 if status == "BLOCKED" else count,
            "local_model_call_attempt_count": 0 if status == "BLOCKED" else attempts,
            "historical_metric_v1_subtype": "UNKNOWN",
            "quality_metrics": "NOT_EVALUATED", "token_usage": usage or {},
            "provider_request_count": "UNAVAILABLE", "resolved_model": "UNAVAILABLE", "cost_status": "UNAVAILABLE"}


def _exit(value):
    if value["status"] != "BLOCKED" and value["integrity"] != "VERIFIED":
        return 5
    return OUTCOMES[value["status"]]


def _observed_process_count(error: cli.CliContractError) -> int | None:
    stage = error.diagnostics.get("failure_stage")
    if stage == "subprocess_launch" or str(error) in {"CLI_SCHEMA_MISSING", "CLI_SCHEMA_INVALID"}:
        return 0
    if stage in {"subprocess_timeout", "subprocess_exit", "isolation_check"}:
        return 1
    # These classifications are emitted only after a subprocess result is available.
    if str(error) in {
        "CLI_TIMEOUT", "CLI_NONZERO_EXIT", "CLI_OUTPUT_MISSING", "CLI_TERMINAL_EVENT_INVALID",
        "CLI_TOOL_EVENT", "CLI_ERROR_EVENT", "CLI_OUTPUT_SCHEMA_INVALID",
        "CLI_DOCUMENT_ID_MISMATCH", "CLI_ISOLATION_VIOLATION",
    }:
        return 1
    return None


def _safe_process_diagnostics(value: dict) -> dict:
    """Reuse the CLI allowlists without retaining messages or raw process output."""
    stage = value.get("failure_stage")
    classification = value.get("error_class")
    return cli.CliContractError(
        "CLI_OPERATIONAL_ERROR", returncode=value.get("returncode"),
        failure_stage=stage if type(stage) is str else "contract_validation",
        error_class=classification if type(classification) is str else "UNKNOWN",
    ).diagnostics


def inspect_probe() -> dict:
    """No writes, launch inference, historical verification, or inferred launch count."""
    path = PROBE_ROOT / "probe.receipt.json"
    if path.is_file() and not path.is_symlink():
        try:
            value = json.loads(path.read_bytes())
            base_keys = set(_result("INCOMPLETE", "NO_TERMINAL_RECEIPT"))
            if (not isinstance(value, dict) or set(value) - {"terminal_diagnostics", "process_diagnostics"} != base_keys
                or value["schema_version"] != "codex-cli-terminal-probe-receipt/v1"
                or value["run_id"] != RUN_ID or value["status"] not in OUTCOMES
                or value["status"] == "BLOCKED" or value["reason"] not in REASONS
                or value["integrity"] not in {"VERIFIED", "FAILED", "UNVERIFIED"}
                or value["historical_metric_v1_subtype"] != "UNKNOWN" or value["quality_metrics"] != "NOT_EVALUATED"):
                raise ValueError("invalid receipt")
            claim = json.loads((PROBE_ROOT / "probe.claim.json").read_bytes())
            if value["claim_sha256"] != cli._digest(claim) or value["bindings"] != claim["bindings"]:
                raise ValueError("claim mismatch")
            terminal = value.get("terminal_diagnostics")
            if terminal is not None and (not isinstance(terminal, dict) or terminal != cli._safe_terminal_metadata(terminal)):
                raise ValueError("unsafe diagnostics")
            if "process_diagnostics" in value:
                process = value["process_diagnostics"]
                if (not isinstance(process, dict)
                    or (process.get("returncode") is not None and type(process.get("returncode")) is not int)
                    or process != _safe_process_diagnostics(process)):
                    raise ValueError("unsafe process diagnostics")
            return value
        except (OSError, ValueError, TypeError, KeyError):
            return _result("INCOMPLETE", "TERMINAL_RECEIPT_INVALID")
    return _result("INCOMPLETE", "NO_TERMINAL_RECEIPT")


def run_probe() -> dict:
    if PROBE_ROOT.exists() or PROBE_ROOT.is_symlink():
        return _result("BLOCKED", "ALREADY_CONSUMED")
    try:
        frozen = prepare()
    except Exception:
        return _result("BLOCKED", "PREREQUISITE_INVALID")
    try:
        PROBE_ROOT.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        PROBE_ROOT.mkdir(mode=0o700)
    except FileExistsError:
        return _result("BLOCKED", "ALREADY_CONSUMED")
    except OSError:
        return _result("BLOCKED", "CLAIM_WRITE_FAILED")
    claim = {"schema_version": "codex-cli-terminal-probe-claim/v1", "run_id": RUN_ID,
             "bindings": frozen.bindings, "policy": POLICY, "history": frozen.history,
             "raw_output_persisted": False}
    claim_hash = cli._digest(claim)
    usage = {}
    try:
        cli._private_create(PROBE_ROOT / "probe.claim.json", claim)
        _sync_directory()
    except OSError:
        # A partially written claim or an empty exclusive directory is still consumed.
        return _result("INCOMPLETE", "CLAIM_WRITE_FAILED")
    value = _result("OTHER_FAILURE", "CLI_INTERNAL_ERROR", bindings=frozen.bindings,
                    claim_hash=claim_hash, attempts=0)
    try:
        prompt_text = frozen.prompt_bytes.decode("utf-8")
        value["local_model_call_attempt_count"] = 1
        result = cli.run_document(frozen.document, schema_path=cli.SCHEMA_PATH,
                                  prompt_text=prompt_text, schema_bytes=frozen.schema_bytes,
                                  timeout=POLICY["model_subprocess_timeout_seconds"], usage_out=usage)
        value["local_model_process_count"] = 1
        Draft202012Validator(json.loads(frozen.schema_bytes)).validate(result)
        validate_extraction(frozen.document, result)
        value.update(status="NOT_REPRODUCED", reason="CONTRACT_VALID")
    except cli.CliContractError as error:
        value["process_diagnostics"] = _safe_process_diagnostics(error.diagnostics)
        value["local_model_process_count"] = _observed_process_count(error)
        reason = str(error) if str(error) in REASONS else "CLI_INTERNAL_ERROR"
        value.update(status="REPRODUCED" if reason == "CLI_OUTPUT_MISSING" else "OTHER_FAILURE", reason=reason)
        terminal = error.diagnostics.get("terminal_diagnostics")
        if reason == "CLI_OUTPUT_MISSING" and isinstance(terminal, dict):
            value["terminal_diagnostics"] = cli._safe_terminal_metadata(terminal)
    except Exception:
        # Exception messages and raw invalid output never cross the custody boundary.
        value.update(status="OTHER_FAILURE", reason="CLI_INTERNAL_ERROR")
    value["token_usage"] = {k: v for k, v in usage.items()
                            if k in {"input_tokens", "output_tokens"} and type(v) is int and v >= 0}
    try:
        value["integrity"] = "VERIFIED" if inventory() == frozen.history else "FAILED"
    except Exception:
        value["integrity"] = "UNVERIFIED"
    try:
        publish(value)
    except OSError:
        # Do not retry publication or infer that a terminal receipt became durable.
        return _result("INCOMPLETE", "STORAGE_WRITE_FAILED", bindings=frozen.bindings,
                       claim_hash=claim_hash)
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--execute", action="store_true", help="Requires separate human execution approval.")
    group.add_argument("--inspect", action="store_true", help="Read saved evidence; never resume.")
    args = parser.parse_args(argv)
    try:
        value = run_probe() if args.execute else inspect_probe()
    except KeyboardInterrupt:
        value = inspect_probe()
    except Exception:
        value = _result("INCOMPLETE", "STORAGE_WRITE_FAILED")
    print(json.dumps(value, sort_keys=True, allow_nan=False))
    return _exit(value)


if __name__ == "__main__":
    raise SystemExit(main())
