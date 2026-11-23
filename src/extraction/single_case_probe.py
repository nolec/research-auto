"""Standalone, non-calibration #66574 probe. Preparation never calls a provider.

The explicit execute command needs separately approved hashes and preinitialized
custody. Neither preparation nor execution initializes or repairs a live budget.
Provider-internal behavior and current pricing are not attested by this module.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import io
import json
import multiprocessing
import os
from pathlib import Path
import signal
import stat
import sys
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from jsonschema import Draft202012Validator, ValidationError

from src.extraction.development_slice import ExtractionValidationError, validate_extraction
from src.extraction.inference_profile import InferenceProfile, load_inference_profile
from src.extraction.model_runner import ModelOutputError, OperationalModelError, ProviderContractError
from src.extraction.openai_responses import OpenAIResponsesTransport, build_response_request_body
from src.extraction.single_case_budget import BudgetBlocked, _directory, canonical_json, send_once

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts/source-spike/github-analysis/runs/ff2ac41d-73bb-4593-9e3e-9aa3a93369dd/collection-result.json"
SOURCE_SHA = "cb54022623a8740e0a997cc210b04eb7b93ed43c13056b5e82657a9d3dd6f49c"
DOC_ID = "github:5034214812"
PROFILE = ROOT / "configs/extraction/inference-profile-gpt-5.6-v1.json"
MODEL_FIELDS = ("document_id", "source", "title", "text", "published_at")
REQUEST_SECONDS = 120
WORKFLOW_SECONDS = 600
MAX_RESPONSE_BYTES = 131072
DEPENDENCIES = (
    "src/extraction/single_case_probe.py", "src/extraction/single_case_budget.py",
    "src/extraction/openai_responses.py", "src/extraction/inference_profile.py",
    "src/extraction/model_runner.py", "src/extraction/development_slice.py",
    "src/contracts/validation.py", "src/source_spike/analysis_bundle.py",
    "src/source_spike/review_packet.py", "configs/extraction/inference-profile-gpt-5.6-v1.json",
    "configs/extraction/prompts/problem-evidence-v1.txt", "schemas/model-extraction-output.schema.json",
    "schemas/inference-profile.schema.json",
)
POLICY = {"max_requests": 1, "retries": 0, "redirects": 0, "synthetic_provider_probes": 0,
          "card_model_calls": 0, "request_seconds": REQUEST_SECONDS,
          "workflow_seconds": WORKFLOW_SECONDS, "max_output_tokens": 1200}


class ProbeBlocked(RuntimeError):
    pass


class ResultStorageError(ProbeBlocked):
    """Storage failure, independent of the original model/contract assessment.

    Preserve the result and serialized bytes in memory, without appending to or
    replacing any file bytes. Partial writes and failed sync are not durability
    evidence. Process termination may lose this in-memory copy; never rerun the
    model to recover it.
    """
    def __init__(self, stage: str, result: dict, result_bytes: bytes | None):
        self.stage = stage
        self.result = result
        self.result_bytes = result_bytes
        super().__init__(f"result storage failed at {stage}; original result retained in exception, "
                         "file durability unverified; do not retry model")


def _hash(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _read(path: Path, *, private: bool = False) -> bytes:
    path = Path(path)
    try:
        with _directory(path.parent) as directory:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
                    raise ProbeBlocked("file type or size invalid")
                if private and (info.st_mode & 0o077 or info.st_nlink != 1):
                    raise ProbeBlocked("private regular file required")
                return stream.read(8 * 1024 * 1024 + 1)
    except OSError as error:
        raise ProbeBlocked("file unavailable; no recovery or reference following") from error


def _write(path: Path, value: object, *, raw: bool = False) -> None:
    data = value if raw else canonical_json(value)
    with _directory(path.parent) as directory:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)


def _wire(document: dict, profile: InferenceProfile) -> bytes:
    # Match the existing transport's wire serialization; source text is unchanged.
    return json.dumps(build_response_request_body(document, profile), ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _code_hashes() -> dict[str, str]:
    return {name: _hash(_read(ROOT / name)) for name in DEPENDENCIES}


@dataclass(frozen=True)
class FrozenBundle:
    manifest: dict
    document: dict
    request_bytes: bytes
    profile: InferenceProfile


def prepare_bundle(destination: Path, *, source_path: Path = SOURCE,
                   expected_source_sha256: str = SOURCE_SHA) -> str:
    """Interpret only fixed items[91] after hashing the same complete file bytes.

    Alternate source/hash arguments exist for synthetic tests; the prepare CLI pins
    the approved real path and SHA. Other records are not inspected or substituted.
    """
    raw = _read(source_path)
    if _hash(raw) != expected_source_sha256:
        raise ProbeBlocked("source hash mismatch")
    try:
        item = json.loads(raw)["items"][91]
        if item["document_id"] != DOC_ID or item["source_item_id"] != "5034214812" or item["source"] != "github":
            raise ProbeBlocked("fixed item identity mismatch")
        document = {key: item[key] for key in MODEL_FIELDS}
        if any(not isinstance(value, str) for value in document.values()):
            raise ProbeBlocked("source input field type invalid")
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProbeBlocked("fixed item unavailable; no substitute") from error
    profile = load_inference_profile(PROFILE)
    if profile.max_output_tokens != POLICY["max_output_tokens"]:
        raise ProbeBlocked("output-token policy changed")
    request = _wire(document, profile)
    document_bytes = canonical_json(document)
    estimate = len(request) + 1024
    manifest = {
        "schema_version": "single-case-extraction-probe/v1", "claim": "NOT_CALIBRATION_OR_PRODUCT_VALIDATION",
        "document_id": DOC_ID, "source_sha256": expected_source_sha256, "source_bytes": len(raw),
        "fixed_index": 91, "text_sha256": _hash(document["text"].encode()),
        "text_bytes": len(document["text"].encode()), "document_sha256": _hash(document_bytes),
        "request_sha256": _hash(request), "code_hashes": _code_hashes(), "policy": dict(POLICY),
        "model": profile.model, "reasoning_effort": profile.reasoning_effort,
        "code_hash_scope": "listed local dependencies only; site packages and interpreter not attested",
        "pricing": {"basis": "local config only; current tariff UNVERIFIED", "hard_cost_cap": False,
                    "input_usd_per_million": profile.input_usd_per_million,
                    "output_usd_per_million": profile.output_usd_per_million,
                    "input_token_estimate": estimate,
                    "estimation_method": "wire UTF8 bytes plus 1024; heuristic, not billing proof",
                    "estimated_usd": (estimate * profile.input_usd_per_million
                                      + profile.max_output_tokens * profile.output_usd_per_million) / 1_000_000},
        "model_execution": "NOT_RUN", "import": "NOT_RUN", "corpus": "NOT_RUN",
        "retention": "private frozen source input/request; future parsed model output only; no key or provider response/id",
    }
    destination = Path(destination)
    try:
        with _directory(destination.parent) as parent:
            os.mkdir(destination.name, 0o700, dir_fd=parent)
        _write(destination / "document.json", document_bytes, raw=True)
        _write(destination / "request.json", request, raw=True)
        _write(destination / "manifest.json", manifest)
    except OSError as error:
        raise ProbeBlocked("destination unavailable or already exists; no overwrite") from error
    return _hash(canonical_json(manifest))


def load_bundle(root: Path, approved_sha256: str) -> FrozenBundle:
    raw = _read(root / "manifest.json", private=True)
    if _hash(raw) != approved_sha256:
        raise ProbeBlocked("approved manifest hash mismatch")
    try:
        manifest = json.loads(raw)
        doc_raw = _read(root / "document.json", private=True)
        request = _read(root / "request.json", private=True)
        if (manifest["policy"] != POLICY or manifest["code_hashes"] != _code_hashes()
            or manifest["document_sha256"] != _hash(doc_raw) or manifest["request_sha256"] != _hash(request)):
            raise ProbeBlocked("frozen bundle or local code drift")
        document = json.loads(doc_raw)
        profile = load_inference_profile(PROFILE)
        if (set(document) != set(MODEL_FIELDS) or document["document_id"] != DOC_ID
            or request != _wire(document, profile) or manifest["model"] != profile.model):
            raise ProbeBlocked("request differs from approved source-only input")
        return FrozenBundle(manifest, document, request, profile)
    except (KeyError, TypeError, ValueError) as error:
        raise ProbeBlocked("frozen bundle invalid") from error


def binding_for(root: Path, approval_id: str, approved_sha256: str) -> dict:
    bundle = load_bundle(root, approved_sha256)
    return {"approval_id": approval_id, "document_id": DOC_ID,
            "source_sha256": bundle.manifest["source_sha256"], "model": bundle.profile.model,
            "prompt_sha256": bundle.profile.prompt_sha256, "schema_sha256": bundle.profile.output_schema_sha256,
            "code_sha256": _hash(canonical_json(bundle.manifest["code_hashes"])),
            "request_sha256": _hash(canonical_json(bundle.document)), "max_requests": 1}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProbeBlocked("redirect blocked; do not follow")


def _failure(kind: str, reason: str, output=None) -> dict:
    return {"status": kind, "reason": reason,
            "contract_status": "FAILED" if kind == "output_contract_failure" else "NOT_VALIDATED",
            "model_output": output, "content_quality": "NOT_ASSESSED", "human_card": "NOT_RUN"}


def call_transport(bundle: FrozenBundle, *, api_key: str, opener=None) -> dict:
    """Low-level adapter; live callers must enter through run_approved's budget gate."""
    actual_open = opener if opener is not None else build_opener(ProxyHandler({}), NoRedirect()).open
    def checked_open(request, *, timeout):
        if request.data != bundle.request_bytes:
            raise ProbeBlocked("wire request drift")
        with actual_open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderContractError("response exceeds byte limit")
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("status") != "completed":
                raise ProviderContractError("response incomplete or missing completion status")
        except (ValueError, UnicodeError) as error:
            raise ProviderContractError("response is not JSON") from error
        return io.BytesIO(raw)
    output = None
    try:
        transport = OpenAIResponsesTransport(api_key=api_key, opener=checked_open, timeout_seconds=REQUEST_SECONDS)
        result = transport(bundle.document, bundle.profile)  # exactly one call, no calibration runner
        output = dict(result.output)
        Draft202012Validator(bundle.profile.output_schema).validate(output)
        # The shared validator requires a source_url key but never uses it for spans.
        # This empty placeholder is validation-only; no URL is invented or sent.
        validate_extraction(dict(bundle.document, source_url=""), output)
    except (OperationalModelError, ProbeBlocked) as error:
        return _failure("operational_failure", type(error).__name__)
    except (ProviderContractError, ModelOutputError, ValidationError, ExtractionValidationError) as error:
        return _failure("output_contract_failure", type(error).__name__, output)
    return {"status": "contract_valid", "contract_status": "valid_abstention" if output["abstention_reason"] else "valid_extraction",
            "model_output": output, "resolved_model": result.resolved_model,
            "usage": {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens},
            "content_quality": "NOT_ASSESSED", "human_card": "NOT_RUN"}


def supervise(call, *, timeout: float = REQUEST_SECONDS) -> dict:
    """POSIX child alarm plus parent watchdog; no worker restart or retry."""
    context = multiprocessing.get_context("fork")
    receive, send = context.Pipe(duplex=False)
    def worker():
        receive.close()
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            try: result = call()
            except BaseException as error: result = _failure("operational_failure", type(error).__name__)
            send.send(result)
        finally:
            send.close()
    process = context.Process(target=worker)
    try:
        process.start()
        send.close()
        if not receive.poll(timeout):
            return _failure("operational_failure", "worker_deadline")
        try:
            result = receive.recv()
        except EOFError:
            return _failure("operational_failure", "worker_terminated")
        return result if isinstance(result, dict) else _failure("operational_failure", "worker_result_invalid")
    finally:
        receive.close()
        send.close()
        if process.pid is not None:
            if process.is_alive(): process.kill()
            process.join(timeout=2)


def _workflow_expired(*args):
    raise TimeoutError("workflow deadline")


@contextmanager
def _workflow_deadline():
    previous = signal.getsignal(signal.SIGALRM)
    if signal.getitimer(signal.ITIMER_REAL)[0]:
        if previous is not _workflow_expired:
            raise ProbeBlocked("existing process alarm; refuse to replace it")
        yield  # Nested stages share the original deadline; never restart its clock.
        return
    signal.signal(signal.SIGALRM, _workflow_expired)
    signal.setitimer(signal.ITIMER_REAL, WORKFLOW_SECONDS)
    try: yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def run_approved(root: Path, budget_root: Path, completion_token: str, approval_id: str,
                 approved_sha256: str, *, api_key: str | None = None, opener=None) -> dict:
    """Execute only after a separate human approval of this exact manifest.

    Providing the hash is an acknowledgment, not authentication of human consent.
    Existing custody and caller-held completion evidence are mandatory; never init.
    """
    with _workflow_deadline():
        bundle = load_bundle(root, approved_sha256)
        binding = binding_for(root, approval_id, approved_sha256)
        key = api_key if api_key is not None else os.environ.get(bundle.profile.secret_environment_variable)
        if not key: raise ProbeBlocked("approved execution requires configured credential")
        return supervise(lambda: send_once(budget_root, binding, bundle.document,
                         lambda document: call_transport(bundle, api_key=key, opener=opener),
                         completion_token=completion_token))


@contextmanager
def _reserved_output(path: Path):
    """Reserve a new private result before any attempt; never overwrite/reuse it."""
    with _directory(path.parent) as directory:
        try:
            fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
        except OSError as error:
            raise ProbeBlocked("output unavailable/reserved; do not retry model") from error
        # No error record is ever written here: it could corrupt an existing
        # complete or partial result and conceal the original storage failure.
        with os.fdopen(fd, "wb") as stream:
            yield stream


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--destination", type=Path, required=True)
    execute = sub.add_parser("execute")
    for name in ("bundle", "budget", "completion-file", "output-file"):
        execute.add_argument("--" + name, type=Path, required=True)
    execute.add_argument("--approval-sha256", required=True)
    execute.add_argument("--approval-id", required=True)
    execute.add_argument("--accept-config-pricing", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        print(json.dumps({"manifest_sha256": prepare_bundle(args.destination), "model": "NOT_RUN"}))
    else:
        _execute(args)
    return 0


def _execute(args) -> None:
    with _workflow_deadline():
        if not args.accept_config_pricing:
            raise ProbeBlocked("current prices unverified; explicit pricing assumption acknowledgment required")
        # Source/token/output reads and writes belong to a later, separately approved run.
        load_bundle(args.bundle, args.approval_sha256)
        token = json.loads(_read(args.completion_file, private=True))["completion_token"]
        result = None
        result_bytes = None
        storage_stage = None
        try:
            with _reserved_output(args.output_file) as stream:
                result = run_approved(args.bundle,args.budget,token,args.approval_id,args.approval_sha256)
                storage_stage = "serialization"
                result_bytes = canonical_json(result)
                storage_stage = "write"
                if stream.write(result_bytes) != len(result_bytes):
                    raise OSError("incomplete result write")
                storage_stage = "flush"
                stream.flush()
                storage_stage = "fsync"
                os.fsync(stream.fileno())
                storage_stage = "close"
        except Exception as error:
            if storage_stage is not None:
                raise ResultStorageError(storage_stage, result, result_bytes) from error
            raise
        print(json.dumps({"result_path":str(args.output_file),"status":result["status"]}))


if __name__ == "__main__":
    raise SystemExit(main())
