from __future__ import annotations

import json
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
