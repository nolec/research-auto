from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
import src.extraction.codex_cli_diagnostic as diagnostic

from src.extraction.codex_cli_diagnostic import (
    CliContractError,
    CliCustody,
    SCHEMA_PATH,
    parse_cli_events,
    run_document,
)


DOCUMENT = {
    "document_id": "github:synthetic",
    "source": "github",
    "title": "Export failure",
    "text": "The scheduled export fails before producing a file.",
    "published_at": "2026-01-01T00:00:00Z",
    "source_url": "https://example.test/synthetic",
}


def test_prompt_and_schema_explain_both_semantic_branches() -> None:
    prompt = diagnostic.PROMPT_PATH.read_text()
    schema = json.loads(SCHEMA_PATH.read_text())
    assert "abstention_reason" in prompt
    assert "non-empty" in prompt
    assert "actor, problem, context, consequence, evidence_quote" in prompt
    assert "Do not invent" in prompt
    assert "every inferred field null" in prompt
    assert "Semantic validation" in schema.get("description", "")


def test_extraction_contract_stays_within_unchanged_preflight_budget() -> None:
    from src.extraction import model_preflight
    from src.extraction.inference_profile import load_inference_profile

    profile = load_inference_profile(
        diagnostic.ROOT / "configs/extraction/inference-profile-gpt-5.6-v1.json"
    )
    assert model_preflight._MAX_COST_USD == 0.10
    assert model_preflight._MAX_ATTEMPTS == 3
    assert profile.max_output_tokens == 1200
    assert model_preflight._upper_bound(profile) <= model_preflight._MAX_COST_USD


def test_inference_profile_binds_updated_extraction_contract() -> None:
    from src.extraction.inference_profile import load_inference_profile

    profile = load_inference_profile(
        diagnostic.ROOT / "configs/extraction/inference-profile-gpt-5.6-v1.json"
    )
    assert profile.prompt_sha256 == sha256(diagnostic.PROMPT_PATH.read_bytes()).hexdigest()
    assert profile.output_schema == json.loads(SCHEMA_PATH.read_text())
    assert "Do not invent" in profile.prompt_text


@pytest.mark.parametrize("actor", [None, "", "   "])
def test_non_abstention_actor_is_rejected_without_weakening_semantics(actor: object) -> None:
    output = {**_output(), "actor": actor}
    with pytest.raises(CliContractError) as caught:
        parse_cli_events(_events(output), DOCUMENT, schema=json.loads(SCHEMA_PATH.read_text()))
    assert caught.value.diagnostics["validation"] == {
        "stage": "semantic", "field": "actor", "rule": "NON_EMPTY_STRING",
    }


def test_unsupported_actor_can_abstain_without_inventing_a_user() -> None:
    output = {field: None for field in _output()}
    output.update(document_id=DOCUMENT["document_id"], abstention_reason="Actor is not supported by the source.")
    assert parse_cli_events(_events(output), DOCUMENT, schema=json.loads(SCHEMA_PATH.read_text())) == output
    output["actor"] = "invented user"
    with pytest.raises(CliContractError) as caught:
        parse_cli_events(_events(output), DOCUMENT, schema=json.loads(SCHEMA_PATH.read_text()))
    assert caught.value.diagnostics["validation"]["rule"] == "ABSTENTION_VALUES"


def _output() -> dict[str, object]:
    return {
        "document_id": DOCUMENT["document_id"],
        "observation_type": "user_problem",
        "actor": "user",
        "problem": "The scheduled export fails before producing a file.",
        "context": "Scheduled export",
        "consequence": "No export file is produced.",
        "evidence_quote": DOCUMENT["text"],
        "evidence_start": 0,
        "evidence_end": len(DOCUMENT["text"]),
        "problem_signal": True,
        "money_signal": False,
        "money_signal_type": None,
        "usable_evidence": True,
        "confidence": 0.8,
        "abstention_reason": None,
    }


def _events(output: dict[str, object] | None = None) -> str:
    return "\n".join(json.dumps(event) for event in (
        {"type": "thread.started", "thread_id": "secret-thread"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(output or _output())}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}},
    ))


def test_parser_accepts_one_terminal_message_and_rejects_tools() -> None:
    assert parse_cli_events(_events(), DOCUMENT)["document_id"] == DOCUMENT["document_id"]
    with pytest.raises(CliContractError, match="CLI_TOOL_EVENT"):
        parse_cli_events(_events() + '\n{"type":"item.started","item":{"type":"command_execution"}}', DOCUMENT)
    with pytest.raises(CliContractError, match="CLI_TERMINAL_EVENT_INVALID"):
        parse_cli_events(_events() + '\n{"type":"turn.completed"}', DOCUMENT)


def test_parser_exposes_observed_token_usage_without_raw_events() -> None:
    usage: dict[str, int] = {}
    parse_cli_events(_events(), DOCUMENT, usage_out=usage)
    assert usage == {"input_tokens": 10, "output_tokens": 20}


def test_parser_rejects_membership_and_raw_text_is_not_in_error() -> None:
    wrong = _output()
    wrong["document_id"] = "github:other"
    with pytest.raises(CliContractError, match="CLI_DOCUMENT_ID_MISMATCH") as error:
        parse_cli_events(_events(wrong), DOCUMENT)
    assert DOCUMENT["text"] not in str(error.value)


def test_custody_blocks_second_claim_without_overwriting(tmp_path: Path) -> None:
    custody = CliCustody(tmp_path / "claim.json", tmp_path / "receipt.json")
    claim = {"schema_version": "codex-cli-claim/v1", "model": "gpt-6-sol"}
    custody.claim(claim)
    with pytest.raises(CliContractError, match="ALREADY_CONSUMED"):
        custody.claim(claim)
    assert json.loads((tmp_path / "claim.json").read_text()) == claim


def test_run_document_never_returns_stderr_or_raw_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = _events()
        stderr = "SECRET ERROR AND SOURCE TEXT"

    def fake_run(command: list[str], **kwargs: object) -> Completed:
        observed["command"] = command
        observed["input"] = kwargs.get("input")
        return Completed()

    monkeypatch.setattr("src.extraction.codex_cli_diagnostic.subprocess.run", fake_run)
    result = run_document(DOCUMENT, schema_path=SCHEMA_PATH, prompt_text="extract", timeout=10)
    assert result["document_id"] == DOCUMENT["document_id"]
    assert "SECRET ERROR" not in json.dumps(result)
    assert DOCUMENT["text"] not in " ".join(observed["command"])
    assert DOCUMENT["text"] in observed["input"]


def test_run_document_rejects_missing_output_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_call(*_args: object, **_kwargs: object) -> None:
        pytest.fail("provider must not run without a schema")

    monkeypatch.setattr("src.extraction.codex_cli_diagnostic.subprocess.run", unexpected_call)
    with pytest.raises(CliContractError, match="CLI_SCHEMA_MISSING"):
        run_document(DOCUMENT, schema_path=tmp_path / "missing.json", prompt_text="extract", timeout=10)


def _stub_diagnostic_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    prompt = tmp_path / "prompt.txt"
    schema = tmp_path / "schema.json"
    prompt.write_text("original prompt", encoding="utf-8")
    schema.write_bytes(SCHEMA_PATH.read_bytes())
    monkeypatch.setattr(diagnostic, "PROMPT_PATH", prompt)
    monkeypatch.setattr(diagnostic, "SCHEMA_PATH", schema)
    monkeypatch.setattr(diagnostic, "CUSTODY_ROOT", tmp_path / "custody")
    monkeypatch.setattr(diagnostic, "load_baseline_manifest", lambda *_args, **_kwargs: SimpleNamespace(
        sources=[], receipt={"manifest_sha256": "manifest"},
    ))
    monkeypatch.setattr(diagnostic, "build_development_inference", lambda *_args: SimpleNamespace(
        corpus=[DOCUMENT] * 40, receipt={"inference_corpus_sha256": "corpus"},
    ))
    monkeypatch.setattr(diagnostic, "build_development_gold_sidecar", lambda *_args: SimpleNamespace(
        labels=[{}] * 40, receipt={"gold_sidecar_sha256": "gold"},
    ))
    monkeypatch.setattr(diagnostic.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout="codex 1.0"))
    return prompt, schema


def test_preflight_claim_binds_the_actual_prompt_and_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, schema = _stub_diagnostic_inputs(tmp_path, monkeypatch)
    original_schema = schema.read_bytes()
    original_claim = diagnostic.CliCustody.claim
    observed: dict[str, object] = {}

    def mutate_after_claim(self: CliCustody, value: dict[str, object]) -> None:
        original_claim(self, value)
        prompt.write_text("changed prompt", encoding="utf-8")
        schema.write_text("{}", encoding="utf-8")

    def fake_document(_document: dict[str, object], **kwargs: object) -> None:
        observed.update(kwargs)
        raise CliContractError("CLI_SEMANTIC_SANITY_FAIL")

    monkeypatch.setattr(diagnostic.CliCustody, "claim", mutate_after_claim)
    monkeypatch.setattr(diagnostic, "run_document", fake_document)
    diagnostic.run_diagnostic()
    claim = json.loads((tmp_path / "custody/preflight.claim.json").read_text())
    assert observed["prompt_text"] == "original prompt"
    assert observed["schema_bytes"] == original_schema
    assert claim["prompt_sha256"] == sha256(b"original prompt").hexdigest()
    assert claim["output_schema_sha256"] == sha256(original_schema).hexdigest()


def test_unexpected_preflight_exception_writes_terminal_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_diagnostic_inputs(tmp_path, monkeypatch)

    def fail_document(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("private source text must not leak")

    monkeypatch.setattr(diagnostic, "run_document", fail_document)
    receipt = diagnostic.run_diagnostic()
    assert receipt["status"] == "PREFLIGHT_BLOCKED"
    assert receipt["reason"] == "CLI_INTERNAL_ERROR"
    assert "private source text" not in json.dumps(receipt)
    assert json.loads((tmp_path / "custody/preflight.receipt.json").read_text()) == receipt


@pytest.mark.parametrize("stderr,expected", [
    ("error: unexpected argument '--bad'", "ARGUMENT_ERROR"),
    ("Error: authentication failed", "AUTHENTICATION_ERROR"),
    ("Error: model is not supported", "MODEL_UNAVAILABLE"),
    ("Error: connection refused", "NETWORK_ERROR"),
    ("Error: permission denied", "PERMISSION_ERROR"),
    ("WARNING: Operation not permitted\nerror: unexpected argument", "ARGUMENT_ERROR"),
    ("WARNING: Operation not permitted\nPRIVATE SOURCE AND TOKEN", "UNKNOWN"),
])
def test_nonzero_error_has_sanitized_diagnostics(
    monkeypatch: pytest.MonkeyPatch, stderr: str, expected: str,
) -> None:
    monkeypatch.setattr(diagnostic.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=2, stdout=_events(), stderr=stderr,
    ))
    with pytest.raises(CliContractError) as caught:
        run_document(DOCUMENT, schema_path=SCHEMA_PATH, prompt_text="extract", timeout=10)
    assert caught.value.diagnostics == {
        "returncode": 2, "failure_stage": "subprocess_exit", "error_class": expected,
    }
    assert stderr not in json.dumps(caught.value.diagnostics)


@pytest.mark.parametrize("error,stage,classification", [
    (subprocess.TimeoutExpired("codex", 10), "subprocess_timeout", "TIMEOUT"),
    (FileNotFoundError("PRIVATE executable path"), "subprocess_launch", "EXECUTABLE_NOT_FOUND"),
    (PermissionError("PRIVATE permission path"), "subprocess_launch", "PERMISSION_ERROR"),
])
def test_launch_and_timeout_errors_have_safe_diagnostics(
    monkeypatch: pytest.MonkeyPatch, error: Exception, stage: str, classification: str,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise error
    monkeypatch.setattr(diagnostic.subprocess, "run", fail)
    with pytest.raises(CliContractError) as caught:
        run_document(DOCUMENT, schema_path=SCHEMA_PATH, prompt_text="extract", timeout=10)
    assert caught.value.diagnostics == {
        "returncode": None, "failure_stage": stage, "error_class": classification,
    }


def test_preflight_failure_diagnostics_and_consumed_claim_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_diagnostic_inputs(tmp_path, monkeypatch)
    calls: list[object] = []
    def fail(*args: object, **_kwargs: object) -> None:
        calls.append(args)
        raise CliContractError("CLI_NONZERO_EXIT", returncode=2,
                               failure_stage="subprocess_exit", error_class="ARGUMENT_ERROR")
    monkeypatch.setattr(diagnostic, "run_document", fail)
    receipt = diagnostic.run_diagnostic()
    assert receipt["process_diagnostics"]["returncode"] == 2
    receipt_path = tmp_path / "custody/preflight.receipt.json"
    frozen = receipt_path.read_bytes()
    with pytest.raises(CliContractError, match="ALREADY_CONSUMED"):
        diagnostic.run_diagnostic()
    assert len(calls) == 1
    assert receipt_path.read_bytes() == frozen


def test_metric_failure_diagnostics_reach_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_diagnostic_inputs(tmp_path, monkeypatch)
    def run(document: dict[str, object], **_kwargs: object) -> dict[str, object]:
        if str(document["document_id"]).startswith("preflight:"):
            return {"problem_signal": True, "usable_evidence": True}
        raise CliContractError("CLI_NONZERO_EXIT", returncode=7,
                               failure_stage="subprocess_exit", error_class="UNKNOWN")
    monkeypatch.setattr(diagnostic, "run_document", run)
    assert diagnostic.run_diagnostic()["process_diagnostics"] == {
        "returncode": 7, "failure_stage": "subprocess_exit", "error_class": "UNKNOWN",
    }


def test_cli_summary_exposes_only_safe_failure_diagnostics(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    details = {"returncode": 2, "failure_stage": "subprocess_exit", "error_class": "ARGUMENT_ERROR"}
    monkeypatch.setattr(diagnostic, "run_diagnostic", lambda: {
        "status": "PREFLIGHT_BLOCKED", "reason": "CLI_NONZERO_EXIT",
        "process_diagnostics": details, "private_raw_output": "SECRET",
    })
    assert diagnostic.main([]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "PREFLIGHT_BLOCKED", "reason": "CLI_NONZERO_EXIT",
        "terminal_output_count": 0, "process_diagnostics": details,
    }


def test_nonzero_cli_exit_preserves_observed_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    class Completed:
        returncode = 1
        stdout = _events()
        stderr = "private source text"

    monkeypatch.setattr(diagnostic.subprocess, "run", lambda *_args, **_kwargs: Completed())
    usage: dict[str, int] = {}
    with pytest.raises(CliContractError, match="CLI_NONZERO_EXIT"):
        run_document(DOCUMENT, schema_path=SCHEMA_PATH, prompt_text="extract", timeout=10, usage_out=usage)
    assert usage == {"input_tokens": 10, "output_tokens": 20}


def test_metric_failure_receipt_includes_failed_call_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_diagnostic_inputs(tmp_path, monkeypatch)

    def fake_document(document: dict[str, object], **kwargs: object) -> dict[str, object]:
        if str(document["document_id"]).startswith("preflight:"):
            return {"problem_signal": True, "usable_evidence": True}
        kwargs["usage_out"].update({"input_tokens": 10, "output_tokens": 20})
        raise CliContractError("CLI_NONZERO_EXIT")

    monkeypatch.setattr(diagnostic, "run_document", fake_document)
    receipt = diagnostic.run_diagnostic()
    assert receipt["status"] == "TERMINAL_FAILURE"
    assert receipt["reason"] == "CLI_NONZERO_EXIT"
    assert receipt["usage_status"] == "OBSERVED"
    assert receipt["token_usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert "private source text" not in json.dumps(receipt)


@pytest.mark.parametrize("failure", ["CLI_NONZERO_EXIT", "CLI_TIMEOUT", "CLI_OUTPUT_SCHEMA_INVALID"])
def test_preflight_failure_receipt_preserves_observed_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    _stub_diagnostic_inputs(tmp_path, monkeypatch)

    def fail_preflight(*_args: object, **kwargs: object) -> None:
        usage = kwargs.get("usage_out")
        if isinstance(usage, dict):
            usage.update({"input_tokens": 10, "output_tokens": 20})
        raise CliContractError(failure)

    monkeypatch.setattr(diagnostic, "run_document", fail_preflight)
    receipt = diagnostic.run_diagnostic()
    assert receipt["status"] == "PREFLIGHT_BLOCKED"
    assert receipt["reason"] == failure
    assert receipt["usage_status"] == "OBSERVED"
    assert receipt["token_usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert receipt["cost_status"] == "UNAVAILABLE"
    assert json.loads((tmp_path / "custody/preflight.receipt.json").read_text()) == receipt


def _v2_cli_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "pass") -> list[list[str]]:
    _stub_diagnostic_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(diagnostic, "V2_CUSTODY_ROOT", tmp_path / "v2", raising=False)
    monkeypatch.setattr(sys, "argv", ["codex_cli_diagnostic", "--preflight-only"])
    legacy = tmp_path / "custody"
    legacy.mkdir()
    for name in ("preflight.claim.json", "preflight.receipt.json", "metric.claim.json", "metric.receipt.json"):
        (legacy / name).write_bytes(b"existing v1 custody")
    calls: list[list[str]] = []

    def fake_process(command: list[str], **kwargs: object) -> SimpleNamespace:
        if command == ["codex", "--version"]:
            return SimpleNamespace(stdout="codex 1.0")
        calls.append(command)
        assert kwargs["timeout"] == 120
        document = json.loads(str(kwargs["input"]).split("Source document JSON:\n", 1)[1])
        output = _output()
        output["document_id"] = document["document_id"]
        if mode == "wrong_id":
            output["document_id"] = "other-document"
        if mode == "invalid_span":
            output["evidence_end"] = 1
        if mode == "semantic_null":
            output["context"] = None
        if mode == "private_extra":
            output[PRIVATE_VALUE] = PRIVATE_VALUE
        return SimpleNamespace(
            returncode=2 if mode == "nonzero" else 0,
            stdout=_events(output), stderr="error: unexpected argument" if mode == "nonzero" else "",
        )

    def unexpected_metric(*_args: object, **_kwargs: object) -> None:
        pytest.fail("preflight-only must not evaluate a metric run")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_process)
    monkeypatch.setattr(diagnostic, "evaluate_calibration", unexpected_metric)
    return calls


@pytest.mark.parametrize("mode,status,reason,exit_code", [
    ("pass", "PREFLIGHT_PASS", "contract_valid", 0),
    ("nonzero", "PREFLIGHT_BLOCKED", "CLI_NONZERO_EXIT", 1),
    ("wrong_id", "PREFLIGHT_BLOCKED", "CLI_DOCUMENT_ID_MISMATCH", 1),
    ("invalid_span", "PREFLIGHT_BLOCKED", "CLI_OUTPUT_SCHEMA_INVALID", 1),
])
def test_v2_preflight_cli_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    mode: str, status: str, reason: str, exit_code: int,
) -> None:
    calls = _v2_cli_environment(tmp_path, monkeypatch, mode)
    assert diagnostic.main() == exit_code
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == status
    assert summary["reason"] == reason
    assert summary["execution_mode"] == "preflight_only"
    assert len(calls) == 1
    assert not list((tmp_path / "v2").glob("metric.*"))
    assert all(p.read_bytes() == b"existing v1 custody" for p in (tmp_path / "custody").iterdir())
    receipt_path = tmp_path / "v2/preflight.receipt.json"
    frozen = receipt_path.read_bytes()
    assert diagnostic.main() == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "ALREADY_CONSUMED"
    assert len(calls) == 1
    assert receipt_path.read_bytes() == frozen


def test_v2_claim_binds_actual_inputs_code_and_process_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v2_cli_environment(tmp_path, monkeypatch)
    assert diagnostic.main() == 0
    claim = json.loads((tmp_path / "v2/preflight.claim.json").read_text())
    receipt = json.loads((tmp_path / "v2/preflight.receipt.json").read_text())
    assert claim["schema_version"] == "codex-cli-extraction-claim/v2"
    assert claim["diagnostic_version"] == "codex-cli-gpt-6-sol-preflight-v2"
    assert claim["implementation_sha256"] == sha256(Path(diagnostic.__file__).read_bytes()).hexdigest()
    assert claim["prompt_sha256"] == sha256(b"original prompt").hexdigest()
    assert claim["output_schema_sha256"] == sha256((tmp_path / "schema.json").read_bytes()).hexdigest()
    assert claim["cli_version"] == "codex 1.0"
    assert claim["requested_model"] == "gpt-6-sol"
    assert claim["model_binding"] == "explicit_cli_argument"
    assert receipt["resolved_model"] == "UNAVAILABLE"
    assert receipt["server_acceptance"] == "UNVERIFIED"
    assert receipt["provider_request_count"] == "UNAVAILABLE"
    assert claim["execution_contract"] == {
        "execution_mode": "preflight_only", "max_model_processes": 1,
        "wrapper_retries": 0, "timeout_seconds": 120,
        "provider_retry_control": "UNAVAILABLE", "cost_limit_status": "UNENFORCED",
    }
    assert claim["command_contract_sha256"] == diagnostic._digest(claim["execution_contract"])
    assert receipt["claim_sha256"] == diagnostic._digest(claim)
    assert receipt["token_usage"] == {"input_tokens": 10, "output_tokens": 20}


def test_v2_preflight_semantic_abstention_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v2_cli_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(diagnostic, "run_document", lambda *_args, **_kwargs: {
        "problem_signal": False, "usable_evidence": False,
    })
    assert diagnostic.main() == 1
    receipt = json.loads((tmp_path / "v2/preflight.receipt.json").read_text())
    assert receipt["reason"] == "CLI_SEMANTIC_SANITY_FAIL"
    assert not list((tmp_path / "v2").glob("metric.*"))


def test_cli_rejects_unknown_mode_without_model_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _v2_cli_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["codex_cli_diagnostic", "--unknown-mode"])
    with pytest.raises(SystemExit) as caught:
        diagnostic.main()
    assert caught.value.code == 2
    assert calls == []


PRIVATE_VALUE = "PRIVATE-source-value-and-unregistered-key@example.test"


def _validation_events(case: str, document: dict[str, object]) -> str:
    output = _output()
    output["document_id"] = document["document_id"]
    output["actor"] = PRIVATE_VALUE
    if case == "schema_type":
        output["confidence"] = PRIVATE_VALUE
    elif case == "schema_extra":
        output[PRIVATE_VALUE] = PRIVATE_VALUE
    elif case == "schema_required":
        del output["context"]
    elif case == "semantic_null":
        output["context"] = None
    elif case == "semantic_span":
        output["evidence_end"] = 1
    message = PRIVATE_VALUE if case == "json_decode" else json.dumps(
        [PRIVATE_VALUE] if case == "object_shape" else output,
    )
    return "\n".join(json.dumps(event) for event in (
        {"type": "item.completed", "item": {"type": "agent_message", "text": message}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}},
    ))


@pytest.mark.parametrize("case,stage,field,rule", [
    ("json_decode", "json_decode", None, "JSON_DECODE"),
    ("object_shape", "object_shape", None, "OBJECT_REQUIRED"),
    ("schema_type", "json_schema", "confidence", "TYPE"),
    ("schema_extra", "json_schema", None, "ADDITIONAL_PROPERTIES"),
    ("schema_required", "json_schema", None, "REQUIRED"),
    ("semantic_null", "semantic", "context", "NON_EMPTY_STRING"),
    ("semantic_span", "semantic", "evidence_quote", "SPAN_MISMATCH"),
])
def test_validation_failures_have_allowlisted_metadata(
    case: str, stage: str, field: str | None, rule: str,
) -> None:
    with pytest.raises(CliContractError, match="CLI_OUTPUT_SCHEMA_INVALID") as caught:
        parse_cli_events(_validation_events(case, DOCUMENT), DOCUMENT,
                         schema=json.loads(SCHEMA_PATH.read_text()))
    assert caught.value.diagnostics["validation"] == {"stage": stage, "field": field, "rule": rule}
    assert PRIVATE_VALUE not in json.dumps(caught.value.diagnostics)


def test_validation_metadata_drops_unregistered_values() -> None:
    error = CliContractError("CLI_OUTPUT_SCHEMA_INVALID", validation={
        "stage": PRIVATE_VALUE, "field": PRIVATE_VALUE, "rule": PRIVATE_VALUE,
        "message": PRIVATE_VALUE, "instance": {"private": PRIVATE_VALUE},
    })
    assert error.diagnostics["validation"] == {"stage": "unknown", "field": None, "rule": "UNKNOWN"}
    assert PRIVATE_VALUE not in json.dumps(error.diagnostics)


@pytest.mark.parametrize("metric", [False, True])
@pytest.mark.parametrize("case,rule", [
    ("json_decode", "JSON_DECODE"), ("schema_extra", "ADDITIONAL_PROPERTIES"),
    ("semantic_null", "NON_EMPTY_STRING"),
])
def test_validation_details_reach_receipt_and_cli_without_raw_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    metric: bool, case: str, rule: str,
) -> None:
    _stub_diagnostic_inputs(tmp_path, monkeypatch)
    def controlled_output(document: dict[str, object], **kwargs: object) -> dict[str, object]:
        if metric and str(document["document_id"]).startswith("preflight:"):
            return {"problem_signal": True, "usable_evidence": True}
        return parse_cli_events(_validation_events(case, document), document,
                                schema=json.loads(SCHEMA_PATH.read_text()), usage_out=kwargs["usage_out"])
    monkeypatch.setattr(diagnostic, "run_document", controlled_output)
    assert diagnostic.main([]) == 1
    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    name = "metric" if metric else "preflight"
    receipt_text = (tmp_path / f"custody/{name}.receipt.json").read_text()
    receipt = json.loads(receipt_text)
    assert summary["process_diagnostics"] == receipt["process_diagnostics"]
    assert receipt["process_diagnostics"]["validation"]["rule"] == rule
    assert receipt["token_usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert PRIVATE_VALUE not in receipt_text + stdout


@pytest.mark.parametrize("changes,rule,field,message", [
    ({"document_id": "other"}, "DOCUMENT_ID", "document_id", "extraction document_id does not match input document_id"),
    ({"abstention_reason": ""}, "ABSTENTION_REASON", "abstention_reason", "abstention reason must be a non-empty string"),
    ({"abstention_reason": "unsupported"}, "ABSTENTION_VALUES", None, "abstention must not contain inferred values"),
    ({"observation_type": None}, "OBSERVATION_TYPE", "observation_type", "invalid observation_type"),
    ({"context": None}, "NON_EMPTY_STRING", "context", "context must be a non-empty string"),
    ({"problem_signal": None}, "BOOLEAN", "problem_signal", "problem_signal must be boolean"),
    ({"money_signal_type": "loss"}, "MONEY_TYPE_NULL", "money_signal_type", "money signal type must be null when money signal is false"),
    ({"money_signal": True}, "MONEY_TYPE_REQUIRED", "money_signal_type", "money signal type is required when money signal is true"),
    ({"confidence": True}, "NUMERIC", "confidence", "confidence must be numeric"),
    ({"confidence": 1.1}, "CONFIDENCE_RANGE", "confidence", "confidence must be between zero and one"),
    ({"evidence_start": True}, "INTEGER_OFFSETS", None, "evidence span must use integer offsets"),
    ({"evidence_end": 999}, "SPAN_BOUNDS", None, "evidence span is outside the input text"),
    ({"evidence_end": 1}, "SPAN_MISMATCH", "evidence_quote", "evidence span does not match evidence_quote"),
])
def test_semantic_validation_preserves_valueerror_and_messages(
    changes: dict[str, object], rule: str, field: str | None, message: str,
) -> None:
    with pytest.raises(ValueError) as caught:
        diagnostic.validate_extraction(DOCUMENT, {**_output(), **changes})
    assert str(caught.value) == message
    assert isinstance(caught.value, diagnostic.ExtractionValidationError)
    assert caught.value.rule == rule
    assert caught.value.field == field


@pytest.mark.parametrize("bad_document", [False, True])
def test_semantic_field_set_errors_preserve_messages(bad_document: bool) -> None:
    document, output = dict(DOCUMENT), _output()
    if bad_document:
        del document["source_url"]
    else:
        del output["context"]
    with pytest.raises(ValueError) as caught:
        diagnostic.validate_extraction(document, output)
    assert str(caught.value) == (
        "inference document fields do not match the gold-free contract" if bad_document
        else "extraction fields do not match the minimal contract"
    )
    assert caught.value.rule == ("INFERENCE_FIELDS" if bad_document else "OUTPUT_FIELDS")
    assert caught.value.field is None


def _v3_cli_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "pass") -> list[list[str]]:
    calls = _v2_cli_environment(tmp_path, monkeypatch, mode)
    monkeypatch.setattr(diagnostic, "V3_CUSTODY_ROOT", tmp_path / "v3", raising=False)
    monkeypatch.setattr(sys, "argv", ["codex_cli_diagnostic", "--preflight-only", "--preflight-version", "v3"])
    (tmp_path / "v2").mkdir()
    for name in ("preflight.claim.json", "preflight.receipt.json", "metric.claim.json", "metric.receipt.json"):
        (tmp_path / "v2" / name).write_bytes(b"existing v2 custody")
    return calls


@pytest.mark.parametrize("mode,status,rule", [
    ("pass", "PREFLIGHT_PASS", None),
    ("nonzero", "PREFLIGHT_BLOCKED", None),
    ("semantic_null", "PREFLIGHT_BLOCKED", "NON_EMPTY_STRING"),
    ("private_extra", "PREFLIGHT_BLOCKED", "ADDITIONAL_PROPERTIES"),
    ("invalid_span", "PREFLIGHT_BLOCKED", "SPAN_MISMATCH"),
])
def test_explicit_v3_cli_preserves_old_custody_and_safe_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    mode: str, status: str, rule: str | None,
) -> None:
    calls = _v3_cli_environment(tmp_path, monkeypatch, mode)
    assert diagnostic.main() == (0 if status == "PREFLIGHT_PASS" else 1)
    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    assert summary["status"] == status
    assert summary["execution_mode"] == "preflight_only"
    assert summary["preflight_version"] == "v3"
    receipt_path = tmp_path / "v3/preflight.receipt.json"
    receipt_text = receipt_path.read_text()
    receipt = json.loads(receipt_text)
    assert receipt["diagnostic_version"] == "codex-cli-gpt-6-sol-preflight-v3"
    if rule:
        assert receipt["process_diagnostics"]["validation"]["rule"] == rule
        assert summary["process_diagnostics"] == receipt["process_diagnostics"]
    assert PRIVATE_VALUE not in stdout + receipt_text
    assert len(calls) == 1
    assert not list((tmp_path / "v3").glob("metric.*"))
    for folder, sentinel in (("custody", b"existing v1 custody"), ("v2", b"existing v2 custody")):
        assert all(file.read_bytes() == sentinel for file in (tmp_path / folder).iterdir())
    frozen = receipt_path.read_bytes()
    assert diagnostic.main() == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "ALREADY_CONSUMED"
    assert len(calls) == 1
    assert receipt_path.read_bytes() == frozen


def test_v3_claim_binds_version_without_changing_probe_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v3_cli_environment(tmp_path, monkeypatch)
    assert diagnostic.main() == 0
    claim = json.loads((tmp_path / "v3/preflight.claim.json").read_text())
    assert claim["diagnostic_version"] == "codex-cli-gpt-6-sol-preflight-v3"
    assert claim["implementation_sha256"] == sha256(Path(diagnostic.__file__).read_bytes()).hexdigest()
    assert claim["model_binding"] == "explicit_cli_argument"
    assert claim["resolved_model"] == "UNAVAILABLE"
    assert claim["execution_contract"]["preflight_version"] == "v3"
    assert claim["execution_contract"]["max_model_processes"] == 1
    assert claim["execution_contract"]["wrapper_retries"] == 0
    assert claim["command_contract_sha256"] == diagnostic._digest(claim["execution_contract"])
    assert claim["synthetic_document_sha256"] == diagnostic._digest({
        "document_id": "preflight:codex-cli-gpt-6-sol-preflight-v2",
        "source": "github", "title": "Synthetic export failure", "text": DOCUMENT["text"],
        "published_at": DOCUMENT["published_at"], "source_url": "https://research-auto.local/preflight",
    })


def test_default_preflight_stays_v2_and_does_not_create_v3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v2_cli_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(diagnostic, "V3_CUSTODY_ROOT", tmp_path / "v3", raising=False)
    assert diagnostic.main() == 0
    claim = json.loads((tmp_path / "v2/preflight.claim.json").read_text())
    assert claim["diagnostic_version"] == "codex-cli-gpt-6-sol-preflight-v2"
    assert not (tmp_path / "v3").exists()


@pytest.mark.parametrize("args", [
    ["--preflight-version", "v3"], ["--preflight-version", "v2"],
    ["--preflight-only", "--preflight-version", "v6"],
])
def test_invalid_version_cli_args_never_launch_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str],
) -> None:
    calls = _v3_cli_environment(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as caught:
        diagnostic.main(args)
    assert caught.value.code == 2
    assert calls == []
    assert not (tmp_path / "v3").exists()


@pytest.mark.parametrize("preflight_only,version", [(False, "v3"), (False, "v2"), (True, "v6")])
def test_invalid_version_api_rejected_before_preparation(
    monkeypatch: pytest.MonkeyPatch, preflight_only: bool, version: str,
) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("invalid mode must be rejected before reading data or calling the CLI")
    monkeypatch.setattr(diagnostic, "load_baseline_manifest", unexpected)
    with pytest.raises(CliContractError, match="CLI_PREFLIGHT_VERSION_INVALID"):
        diagnostic.run_diagnostic(preflight_only=preflight_only, preflight_version=version)


def _v4_cli_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> list[list[str]]:
    calls = _v3_cli_environment(tmp_path, monkeypatch, "nonzero" if mode == "nonzero" else "pass")
    monkeypatch.setattr(diagnostic, "V4_CUSTODY_ROOT", tmp_path / "v4", raising=False)
    monkeypatch.setattr(sys, "argv", ["codex_cli_diagnostic", "--preflight-only", "--preflight-version", "v4"])
    (tmp_path / "v3").mkdir()
    for name in ("preflight.claim.json", "preflight.receipt.json", "metric.claim.json", "metric.receipt.json"):
        (tmp_path / "v3" / name).write_bytes(b"existing v3 custody")
    fake_run = diagnostic.subprocess.run

    def process(command: list[str], **kwargs: object) -> SimpleNamespace:
        if command == ["codex", "--version"]:
            if mode == "prerequisite":
                raise FileNotFoundError("private executable path")
            return fake_run(command, **kwargs)
        completed = fake_run(command, **kwargs)
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 120)
        if mode == "internal":
            raise RuntimeError(PRIVATE_VALUE)
        events = [json.loads(line) for line in completed.stdout.splitlines()]
        output = json.loads(events[2]["item"]["text"])
        if mode == "abstain":
            output = {field: None for field in output}
            output.update(document_id=json.loads(events[2]["item"]["text"])["document_id"], abstention_reason=PRIVATE_VALUE)
        elif mode == "negative":
            output["problem_signal"] = False
        elif mode == "schema":
            output["actor"] = 42
        elif mode == "semantic":
            output["actor"] = None
        elif mode == "membership":
            output["document_id"] = "wrong-document"
        if mode == "event":
            completed.stdout = "{}"
        else:
            events[2]["item"]["text"] = "{" if mode == "json" else json.dumps([] if mode == "object" else output)
            completed.stdout = "\n".join(json.dumps(event) for event in events)
        return completed

    monkeypatch.setattr(diagnostic.subprocess, "run", process)
    return calls


@pytest.mark.parametrize("mode,status,reason,observed", [
    ("pass", "PREFLIGHT_PASS", "contract_valid", (True, False, True)),
    ("abstain", "PREFLIGHT_BLOCKED", "CLI_SEMANTIC_SANITY_FAIL", (True, True, False)),
    ("negative", "PREFLIGHT_BLOCKED", "CLI_SEMANTIC_SANITY_FAIL", (True, False, False)),
    ("json", "PREFLIGHT_BLOCKED", "CLI_OUTPUT_SCHEMA_INVALID", (False, None, None)),
    ("object", "PREFLIGHT_BLOCKED", "CLI_OUTPUT_SCHEMA_INVALID", (False, None, None)),
    ("schema", "PREFLIGHT_BLOCKED", "CLI_OUTPUT_SCHEMA_INVALID", (False, None, None)),
    ("semantic", "PREFLIGHT_BLOCKED", "CLI_OUTPUT_SCHEMA_INVALID", (False, None, None)),
    ("membership", "PREFLIGHT_BLOCKED", "CLI_DOCUMENT_ID_MISMATCH", (False, None, None)),
    ("event", "PREFLIGHT_BLOCKED", "CLI_TERMINAL_EVENT_INVALID", (None, None, None)),
    ("nonzero", "PREFLIGHT_BLOCKED", "CLI_NONZERO_EXIT", (None, None, None)),
    ("timeout", "PREFLIGHT_BLOCKED", "CLI_TIMEOUT", (None, None, None)),
    ("internal", "PREFLIGHT_BLOCKED", "CLI_INTERNAL_ERROR", (None, None, None)),
])
def test_v4_cli_observations_match_receipt_and_preserve_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    mode: str, status: str, reason: str, observed: tuple[bool | None, ...],
) -> None:
    calls = _v4_cli_environment(tmp_path, monkeypatch, mode)
    historical = {str(p): p.read_bytes() for folder in ("custody", "v2", "v3") for p in (tmp_path / folder).iterdir()}
    assert diagnostic.main() == (0 if status == "PREFLIGHT_PASS" else 1)
    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    receipt_path = tmp_path / "v4/preflight.receipt.json"
    receipt_text = receipt_path.read_text()
    receipt = json.loads(receipt_text)
    assert summary["status"] == receipt["status"] == status
    assert summary["reason"] == receipt["reason"] == reason
    assert summary["preflight_version"] == "v4"
    for key, expected in zip(("output_contract_valid", "abstained", "positive_sanity_valid"), observed):
        assert summary[key] is expected
        assert receipt[key] is expected
    claim = json.loads((tmp_path / "v4/preflight.claim.json").read_text())
    assert claim["diagnostic_version"] == receipt["diagnostic_version"] == "codex-cli-gpt-6-sol-preflight-v4"
    assert claim["execution_contract"]["preflight_version"] == "v4"
    assert claim["execution_contract"]["max_model_processes"] == 1
    assert claim["execution_contract"]["wrapper_retries"] == 0
    assert claim["implementation_sha256"] == sha256(Path(diagnostic.__file__).read_bytes()).hexdigest()
    assert receipt["process_count"] == len(calls) == 1
    assert PRIVATE_VALUE not in stdout + receipt_text
    assert not list((tmp_path / "v4").glob("metric.*"))
    assert {path: Path(path).read_bytes() for path in historical} == historical
    frozen = receipt_path.read_bytes()
    assert diagnostic.main() == 1
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["reason"] == "ALREADY_CONSUMED"
    assert all(repeated[k] is None for k in ("output_contract_valid", "abstained", "positive_sanity_valid"))
    assert receipt_path.read_bytes() == frozen
    assert len(calls) == 1


def test_v4_prerequisite_failure_is_unobserved_and_does_not_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _v4_cli_environment(tmp_path, monkeypatch, "prerequisite")
    assert diagnostic.main() == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["reason"] == "CLI_PREREQUISITE_FAIL"
    assert all(summary[k] is None for k in ("output_contract_valid", "abstained", "positive_sanity_valid"))
    assert calls == []
    assert not (tmp_path / "v4").exists()


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_legacy_preflight_does_not_gain_v4_observation_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], version: str,
) -> None:
    (_v2_cli_environment if version == "v2" else _v3_cli_environment)(tmp_path, monkeypatch)
    assert diagnostic.main() == 0
    summary = json.loads(capsys.readouterr().out)
    receipt = json.loads((tmp_path / version / "preflight.receipt.json").read_text())
    for key in ("output_contract_valid", "abstained", "positive_sanity_valid"):
        assert key not in summary
        assert key not in receipt


def test_v4_requires_preflight_only_before_data_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("invalid mode must not prepare data")
    monkeypatch.setattr(diagnostic, "load_baseline_manifest", unexpected)
    with pytest.raises(SystemExit) as caught:
        diagnostic.main(["--preflight-version", "v4"])
    assert caught.value.code == 2
    with pytest.raises(CliContractError, match="CLI_PREFLIGHT_VERSION_INVALID"):
        diagnostic.run_diagnostic(preflight_version="v4")


_V5_DOCUMENT = {
    "document_id": "preflight:codex-cli-gpt-6-sol-preflight-v5",
    "source": "github",
    "title": "Synthetic positive payroll export failure",
    "text": "I am a payroll administrator. During our monthly payroll preparation, the scheduled payroll export fails before producing a file. I cannot submit payroll until the export file is available.",
    "published_at": "2026-01-01T00:00:00Z",
    "source_url": "https://research-auto.local/preflight",
}


def _v5_cli_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> list[list[str]]:
    calls = _v4_cli_environment(tmp_path, monkeypatch, mode)
    monkeypatch.setattr(diagnostic, "V5_CUSTODY_ROOT", tmp_path / "v5", raising=False)
    monkeypatch.setattr(sys, "argv", ["codex_cli_diagnostic", "--preflight-only", "--preflight-version", "v5"])
    (tmp_path / "v4").mkdir()
    for name in ("preflight.claim.json", "preflight.receipt.json", "metric.claim.json", "metric.receipt.json"):
        (tmp_path / "v4" / name).write_bytes(b"existing v4 custody")
    previous_run = diagnostic.subprocess.run

    def process(command: list[str], **kwargs: object) -> SimpleNamespace:
        if command != ["codex", "--version"]:
            request = str(kwargs["input"])
            source = json.loads(request.split("Source document JSON:\n", 1)[1])
            assert source == {k: v for k, v in _V5_DOCUMENT.items() if k != "source_url"}
            assert "expected_output" not in request and "ground_truth" not in request
        completed = previous_run(command, **kwargs)
        if command == ["codex", "--version"] or mode in ("abstain", "event", "json", "object"):
            return completed
        events = [json.loads(line) for line in completed.stdout.splitlines()]
        output = json.loads(events[2]["item"]["text"])
        if output["actor"] == "user":
            output["actor"] = "payroll administrator"
        output.update(
            problem="the scheduled payroll export fails before producing a file",
            context="monthly payroll preparation",
            consequence="I cannot submit payroll until the export file is available.",
            evidence_quote=_V5_DOCUMENT["text"], evidence_start=0, evidence_end=len(_V5_DOCUMENT["text"]),
        )
        events[2]["item"]["text"] = json.dumps(output)
        completed.stdout = "\n".join(json.dumps(event) for event in events)
        return completed

    monkeypatch.setattr(diagnostic.subprocess, "run", process)
    return calls


@pytest.mark.parametrize("mode,reason,observed", [
    ("pass", "contract_valid", (True, False, True)),
    ("abstain", "CLI_SEMANTIC_SANITY_FAIL", (True, True, False)),
    ("negative", "CLI_SEMANTIC_SANITY_FAIL", (True, False, False)),
    ("json", "CLI_OUTPUT_SCHEMA_INVALID", (False, None, None)),
    ("object", "CLI_OUTPUT_SCHEMA_INVALID", (False, None, None)),
    ("schema", "CLI_OUTPUT_SCHEMA_INVALID", (False, None, None)),
    ("semantic", "CLI_OUTPUT_SCHEMA_INVALID", (False, None, None)),
    ("membership", "CLI_DOCUMENT_ID_MISMATCH", (False, None, None)),
    ("event", "CLI_TERMINAL_EVENT_INVALID", (None, None, None)),
    ("nonzero", "CLI_NONZERO_EXIT", (None, None, None)),
    ("timeout", "CLI_TIMEOUT", (None, None, None)),
    ("internal", "CLI_INTERNAL_ERROR", (None, None, None)),
])
def test_v5_positive_probe_cli_surface_and_frozen_prior_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    mode: str, reason: str, observed: tuple[bool | None, ...],
) -> None:
    calls = _v5_cli_environment(tmp_path, monkeypatch, mode)
    historical = {str(p): p.read_bytes() for folder in ("custody", "v2", "v3", "v4") for p in (tmp_path / folder).iterdir()}
    assert diagnostic.main() == (0 if mode == "pass" else 1)
    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    path = tmp_path / "v5/preflight.receipt.json"
    receipt_text = path.read_text()
    receipt = json.loads(receipt_text)
    claim = json.loads((tmp_path / "v5/preflight.claim.json").read_text())
    assert summary["preflight_version"] == "v5"
    assert summary["reason"] == receipt["reason"] == reason
    assert summary["status"] == receipt["status"] == ("PREFLIGHT_PASS" if mode == "pass" else "PREFLIGHT_BLOCKED")
    for key, expected in zip(("output_contract_valid", "abstained", "positive_sanity_valid"), observed):
        assert summary[key] is expected
        assert receipt[key] is expected
    assert claim["diagnostic_version"] == receipt["diagnostic_version"] == "codex-cli-gpt-6-sol-preflight-v5"
    assert claim["synthetic_document_sha256"] == diagnostic._digest(_V5_DOCUMENT)
    assert claim["execution_contract"]["preflight_version"] == "v5"
    assert claim["execution_contract"]["max_model_processes"] == 1
    assert claim["execution_contract"]["wrapper_retries"] == 0
    assert claim["execution_contract"]["timeout_seconds"] == 120
    assert claim["implementation_sha256"] == sha256(Path(diagnostic.__file__).read_bytes()).hexdigest()
    assert PRIVATE_VALUE not in stdout + receipt_text
    assert not list((tmp_path / "v5").glob("metric.*"))
    assert len(calls) == receipt["process_count"] == 1
    assert {p: Path(p).read_bytes() for p in historical} == historical
    frozen = path.read_bytes()
    assert diagnostic.main() == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "ALREADY_CONSUMED"
    assert len(calls) == 1
    assert path.read_bytes() == frozen


def test_v5_directly_supported_expected_output_passes_unchanged_validator() -> None:
    from src.extraction.development_slice import validate_extraction
    from jsonschema import Draft202012Validator

    text = _V5_DOCUMENT["text"]
    output = {
        **_output(), "document_id": _V5_DOCUMENT["document_id"],
        "actor": "payroll administrator", "problem": "the scheduled payroll export fails before producing a file",
        "context": "monthly payroll preparation", "consequence": "I cannot submit payroll until the export file is available.",
        "evidence_quote": text, "evidence_start": 0, "evidence_end": len(text),
    }
    for field in ("actor", "problem", "context", "consequence"):
        assert output[field] in text
    assert output["money_signal"] is False and output["money_signal_type"] is None
    Draft202012Validator(json.loads(SCHEMA_PATH.read_text())).validate(output)
    validate_extraction(_V5_DOCUMENT, output)


def test_v5_requires_preflight_only_before_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("invalid mode must not prepare data")
    monkeypatch.setattr(diagnostic, "load_baseline_manifest", unexpected)
    with pytest.raises(SystemExit) as caught:
        diagnostic.main(["--preflight-version", "v5"])
    assert caught.value.code == 2
    with pytest.raises(CliContractError, match="CLI_PREFLIGHT_VERSION_INVALID"):
        diagnostic.run_diagnostic(preflight_version="v5")


@pytest.mark.parametrize("texts,detail,count,detected", [
    ([], "NO_COMPLETED_AGENT_MESSAGE", 0, False),
    (["private", "private"], "MULTIPLE_COMPLETED_AGENT_MESSAGES", 2, False),
    ([None, "private"], "NON_STRING_AGENT_MESSAGE", None, True),
])
def test_terminal_diagnostics_distinguish_missing_cases(texts, detail, count, detected):
    events = [{"type": "item.completed", "item": {"type": "agent_message", "text": text}} for text in texts]
    events.append({"type": "turn.completed"})
    with pytest.raises(CliContractError, match="^CLI_OUTPUT_MISSING$") as caught:
        parse_cli_events("\n".join(json.dumps(e) for e in events), DOCUMENT)
    assert caught.value.diagnostics["terminal_diagnostics"] == {
        "reason_detail": detail, "completed_agent_message_count": count,
        "non_string_message_detected": detected,
    }
    assert "private" not in json.dumps(caught.value.diagnostics)
    assert "validation" not in caught.value.diagnostics


@pytest.mark.parametrize("count,detected,expected_count,expected_detected", [
    (True, 1, None, None), (-1, "private", None, None),
    (2.0, None, None, None), (2, False, 2, False), (None, True, None, True),
])
def test_terminal_diagnostics_are_sanitized(count, detected, expected_count, expected_detected):
    error = CliContractError("CLI_OUTPUT_MISSING", terminal_diagnostics={
        "reason_detail": "private", "completed_agent_message_count": count,
        "non_string_message_detected": detected, "private": "private",
    })
    assert error.diagnostics["terminal_diagnostics"] == {
        "reason_detail": "UNKNOWN", "completed_agent_message_count": expected_count,
        "non_string_message_detected": expected_detected,
    }


def test_terminal_diagnostics_keep_first_failure_order():
    for tail in ({"type": "turn.completed"}, {"type": "item.started", "item": {"type": "tool_call"}}):
        events = [{"type": "item.completed", "item": {"type": "agent_message", "text": None}}, tail]
        with pytest.raises(CliContractError, match="^CLI_OUTPUT_MISSING$") as caught:
            parse_cli_events("\n".join(json.dumps(e) for e in events), DOCUMENT)
        assert caught.value.diagnostics["terminal_diagnostics"]["completed_agent_message_count"] is None
    with pytest.raises(CliContractError, match="^CLI_ERROR_EVENT$"):
        parse_cli_events('{"type":"error"}\n{"type":"turn.completed"}', DOCUMENT)
    with pytest.raises(CliContractError, match="^CLI_TERMINAL_EVENT_INVALID$"):
        parse_cli_events('{"type":"turn.started"}', DOCUMENT)


def test_terminal_diagnostics_preflight_cli_and_custody(tmp_path, monkeypatch, capsys):
    _stub_diagnostic_inputs(tmp_path, monkeypatch)
    root = tmp_path / "v5"
    monkeypatch.setattr(diagnostic, "V5_CUSTODY_ROOT", root)
    # Both version probe and model transport are offline stubs.
    monkeypatch.setattr(diagnostic.subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout='{"type":"turn.completed"}', stderr="private", returncode=0,
    ))
    assert diagnostic.main(["--preflight-only", "--preflight-version", "v5"]) == 1
    summary = json.loads(capsys.readouterr().out)
    receipt = json.loads((root / "preflight.receipt.json").read_text())
    expected = {"reason_detail": "NO_COMPLETED_AGENT_MESSAGE",
                "completed_agent_message_count": 0, "non_string_message_detected": False}
    assert summary["process_diagnostics"]["terminal_diagnostics"] == expected
    assert receipt["process_diagnostics"] == summary["process_diagnostics"]
    assert summary["reason"] == "CLI_OUTPUT_MISSING"
    assert summary["output_contract_valid"] is None
    assert "private" not in json.dumps(receipt)
