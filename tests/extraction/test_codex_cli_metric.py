from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.extraction import codex_cli_diagnostic as cli
from src.extraction.calibration_evaluator import evaluate_calibration
from src.extraction.development_slice import DevelopmentGoldSidecar, DevelopmentInference


PRIVATE = "PRIVATE_CONTENT_MUST_NOT_PERSIST"
SOURCES = ("github", "stackexchange", "steam", "ted")


def module():
    assert importlib.util.find_spec("src.extraction.codex_cli_metric") is not None, "isolated metric executor is required"
    return importlib.import_module("src.extraction.codex_cli_metric")


def dataset():
    docs = tuple({"document_id": f"{s}:{i:02}", "source": s, "title": PRIVATE,
                  "text": f"{PRIVATE}: user cannot export.", "published_at": "2026-01-01T00:00:00Z",
                  "source_url": f"https://example.test/{PRIVATE}"} for s in SOURCES for i in range(10))
    labels = tuple({"document_id": d["document_id"], "problem_signal": True, "money_signal": False,
                    "money_signal_type": None, "usable_evidence": True, "noise": False} for d in docs)
    common = {"selected_count": 40, "source_counts": {s: 10 for s in SOURCES},
              "source_spike_reserved_emitted": 0, "packet_validation": "PASS",
              "source_dataset_sha256": {s: "a" * 64 for s in SOURCES},
              "source_qualification_sha256": {s: "b" * 64 for s in SOURCES},
              "source_packet_manifest_sha256": {s: "c" * 64 for s in SOURCES}}
    return (DevelopmentInference(docs, {**common, "inference_corpus_sha256": cli._digest(docs)}),
            DevelopmentGoldSidecar(labels, {**common, "gold_sidecar_sha256": cli._digest(labels)}))


def output(doc, abstain=False):
    result = {"document_id": doc["document_id"], "observation_type": "user_problem", "actor": PRIVATE,
              "problem": "cannot export", "context": "export", "consequence": "no file",
              "evidence_quote": doc["text"], "evidence_start": 0, "evidence_end": len(doc["text"]),
              "problem_signal": True, "money_signal": False, "money_signal_type": None,
              "usable_evidence": True, "confidence": 0.8, "abstention_reason": None}
    if abstain:
        result = {k: None for k in result}
        result.update(document_id=doc["document_id"], abstention_reason=PRIVATE)
    return result


def run_receipt(inference, outputs):
    return {"variant_id": "fixture", "status": "success", "input_count": 40,
            "output_count": len(outputs), "output_sha256": cli._digest(tuple(outputs)),
            "inference_corpus_sha256": inference.receipt["inference_corpus_sha256"]}


@pytest.mark.parametrize("mode", ["valid", "abstain", "invalid", "missing"])
def test_existing_evaluator_compatibility_is_not_redefined(mode):
    inference, gold = dataset()
    outputs = [output(d, mode == "abstain") for d in inference.corpus]
    if mode == "invalid":
        outputs[0]["actor"] = None
    if mode == "missing":
        outputs.pop()
        with pytest.raises(ValueError, match="membership length mismatch"):
            evaluate_calibration(inference, gold, outputs, run_receipt(inference, outputs))
        return
    report = evaluate_calibration(inference, gold, outputs, run_receipt(inference, outputs))
    assert report.receipt["input_count"] == 40
    assert report.invalid_count == (1 if mode == "invalid" else 0)
    if mode == "abstain":
        assert report.abstention_count == 40
        assert report.metrics["problem_signal"]["precision"] is None
    if mode == "invalid":
        assert report.metrics["problem_signal"]["fn"] == 1


@pytest.fixture
def environment(tmp_path, monkeypatch):
    m = module()
    inference, gold = dataset()
    schema_bytes = cli.SCHEMA_PATH.read_bytes()
    bindings = {"preflight_receipt_sha256": "a" * 64, "implementation_bundle_sha256": "b" * 64,
                "inference_corpus_sha256": inference.receipt["inference_corpus_sha256"],
                "gold_sidecar_sha256": gold.receipt["gold_sidecar_sha256"], "ordered_ids_sha256": "c" * 64,
                "prompt_sha256": "d" * 64, "output_schema_sha256": sha256(schema_bytes).hexdigest()}
    prepared = m.Prepared(inference, gold, b"fixed prompt", schema_bytes, bindings,
                          {"coverage": 0.35, "metrics": {}, "source_metrics": {}})
    monkeypatch.setattr(m, "RUN_ROOT", tmp_path / "metric-v1")
    monkeypatch.setattr(m, "prepare", lambda: prepared)
    clock = [0.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    calls = []

    def transport(doc, **kwargs):
        assert set(doc) == {"document_id", "source", "title", "text", "published_at", "source_url"}
        assert not any(k in doc for k in ("noise", "gold", "money_signal", "problem_signal"))
        assert kwargs["prompt_text"] == "fixed prompt"
        assert kwargs["schema_bytes"] == schema_bytes
        assert 0 < kwargs["timeout"] <= 120
        calls.append(doc["document_id"])
        kwargs["usage_out"].update(input_tokens=10, output_tokens=2)
        clock[0] += 1
        return output(doc)

    monkeypatch.setattr(cli, "run_document", transport)
    return m, prepared, calls, clock, transport


@pytest.mark.parametrize("mode,code,status,evaluation", [
    ("valid", 0, "MEASURED", "EVALUATED"),
    ("abstain", 0, "MEASURED", "EVALUATED"),
    ("invalid", 3, "COMPLETED_NOT_EVALUABLE", "NOT_EVALUABLE"),
    ("bad_return", 3, "COMPLETED_NOT_EVALUABLE", "NOT_EVALUABLE"),
    ("operational", 1, "INCOMPLETE", "INCOMPLETE"),
    ("timeout", 1, "INCOMPLETE", "INCOMPLETE"),
    ("deadline", 1, "INCOMPLETE", "INCOMPLETE"),
])
def test_metric_cli_surface_full_accounting_and_no_raw_persistence(environment, monkeypatch, capsys, mode, code, status, evaluation):
    m, prepared, calls, clock, transport = environment

    def process(doc, **kwargs):
        value = transport(doc, **kwargs)
        if mode == "abstain":
            return output(doc, True)
        if mode == "invalid":
            raise cli.CliContractError("CLI_OUTPUT_SCHEMA_INVALID", validation={"stage": "semantic", "field": "actor", "rule": "NON_EMPTY_STRING"})
        if mode == "bad_return":
            return {**value, "actor": None}
        if mode in ("operational", "timeout"):
            raise cli.CliContractError("CLI_TIMEOUT" if mode == "timeout" else "CLI_NONZERO_EXIT")
        if mode == "deadline":
            clock[0] = 1801
        return value

    monkeypatch.setattr(cli, "run_document", process)
    assert m.main(["--execute"]) == code
    public = json.loads(capsys.readouterr().out)
    receipt = json.loads((m.RUN_ROOT / "metric.receipt.json").read_text())
    assert public == receipt
    assert receipt["status"] == status
    assert receipt["evaluation_status"] == evaluation
    assert sum(receipt["counts"].values()) == 40
    assert receipt["counts"]["attempt_started"] == 0
    assert len(calls) == (1 if mode in ("operational", "timeout", "deadline") else 40)
    assert len(calls) == len(set(calls))
    if mode == "abstain":
        assert receipt["counts"]["valid_abstention"] == 40
        assert receipt["evaluation"]["metrics"]["problem_signal"]["precision"] is None
    if mode in ("invalid", "bad_return"):
        assert receipt["counts"]["invalid"] == 40
        assert receipt["evaluation"] is None
        assert receipt["evaluation_reason"] == "INVALID_OUTPUT_NOT_RETAINED"
    for p in m.RUN_ROOT.iterdir():
        assert p.stat().st_mode & 0o777 == 0o600
        assert PRIVATE not in p.read_text()
        assert "github:00" not in p.read_text()
    assert m.RUN_ROOT.stat().st_mode & 0o777 == 0o700
    frozen = {p.name: p.read_bytes() for p in m.RUN_ROOT.iterdir()}
    assert m.main(["--execute"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "ALREADY_CONSUMED"
    assert {p.name: p.read_bytes() for p in m.RUN_ROOT.iterdir()} == frozen


def test_force_stop_projects_started_to_unknown_without_rewriting_or_resuming(environment, monkeypatch, capsys):
    m, _, calls, _, transport = environment

    def stop(doc, **kwargs):
        transport(doc, **kwargs)
        raise SystemExit("simulate process death")

    monkeypatch.setattr(cli, "run_document", stop)
    with pytest.raises(SystemExit):
        m.run_metric()
    progress = m.RUN_ROOT / "progress.json"
    frozen = progress.read_bytes()
    assert json.loads(frozen)["rows"][0]["state"] == "attempt_started"
    assert not (m.RUN_ROOT / "metric.receipt.json").exists()
    assert m.main(["--inspect"]) == 1
    value = json.loads(capsys.readouterr().out)
    assert value["counts"]["attempted_unknown"] == 1
    assert value["counts"]["not_attempted"] == 39
    assert progress.read_bytes() == frozen
    assert len(calls) == 1
    assert m.main(["--execute"]) == 2
    assert len(calls) == 1


@pytest.mark.parametrize("fail_at,expected_calls", [(1, 0), (2, 0), (3, 1)])
def test_progress_publication_failure_never_starts_another_call(environment, monkeypatch, capsys, fail_at, expected_calls):
    m, _, calls, _, _ = environment
    real_save = m._save_progress
    n = [0]

    def fail(root, progress):
        n[0] += 1
        if n[0] == fail_at:
            raise OSError(PRIVATE)
        real_save(root, progress)

    monkeypatch.setattr(m, "_save_progress", fail)
    assert m.main(["--execute"]) == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "STORAGE_FAILURE"
    assert len(calls) == expected_calls
    assert not (m.RUN_ROOT / "metric.receipt.json").exists()
    assert PRIVATE not in json.dumps(summary)


def test_partial_token_usage_is_not_reported_as_complete(environment, monkeypatch, capsys):
    m, _, _, _, transport = environment
    n = [0]

    def partial(doc, **kwargs):
        value = transport(doc, **kwargs)
        n[0] += 1
        if n[0] == 1:
            kwargs["usage_out"].pop("output_tokens")
        return value

    monkeypatch.setattr(cli, "run_document", partial)
    assert m.main(["--execute"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["unobserved_usage_calls"] == 1
    assert r["usage_status"] == "PARTIAL"
    assert r["token_usage"] == {"input_tokens": 400, "output_tokens": 78}


def test_explicit_action_is_required(environment):
    m, _, calls, _, _ = environment
    with pytest.raises(SystemExit) as e:
        m.main([])
    assert e.value.code == 2
    assert calls == []
    assert not m.RUN_ROOT.exists()


@pytest.mark.parametrize("drift", ["receipt_hash", "claim", "prompt", "schema", "model", "corpus", "gold", "ids", "labels", "quota", "cli_version"])
def test_real_prepare_rejects_drift_before_model_and_claim(tmp_path, monkeypatch, drift):
    m = module()
    inference, gold = dataset()
    root = tmp_path / "v5"
    root.mkdir()
    prompt = b"test frozen prompt"
    schema = cli.SCHEMA_PATH.read_bytes()
    claim = {"diagnostic_version": "codex-cli-gpt-6-sol-preflight-v5", "execution_mode": "preflight_only",
             "requested_model": cli.MODEL, "cli_version": "codex-cli 0.163.0-alpha.10.2",
             "model_binding": "explicit_cli_argument", "prompt_sha256": sha256(prompt).hexdigest(),
             "output_schema_sha256": sha256(schema).hexdigest(),
             "baseline_manifest_sha256": "a" * 64,
             "inference_corpus_sha256": inference.receipt["inference_corpus_sha256"],
             "gold_sidecar_sha256": gold.receipt["gold_sidecar_sha256"]}
    if drift in ("prompt", "schema", "corpus", "gold"):
        claim[{"prompt": "prompt_sha256", "schema": "output_schema_sha256", "corpus": "inference_corpus_sha256", "gold": "gold_sidecar_sha256"}[drift]] = "0" * 64
    if drift == "model":
        claim["requested_model"] = "other-model"
    receipt = {**claim, "claim_sha256": cli._digest(claim), "status": "PREFLIGHT_PASS",
               "output_contract_valid": True, "abstained": False, "positive_sanity_valid": True}
    if drift == "claim":
        receipt["claim_sha256"] = "0" * 64
    payload = json.dumps(receipt).encode()
    (root / "preflight.claim.json").write_text(json.dumps(claim))
    (root / "preflight.receipt.json").write_bytes(payload)
    p = tmp_path / "prompt.txt"
    p.write_bytes(prompt)
    monkeypatch.setattr(m, "PREFLIGHT_ROOT", root)
    monkeypatch.setattr(m, "APPROVED_PREFLIGHT_SHA256", "0" * 64 if drift == "receipt_hash" else sha256(payload).hexdigest())
    monkeypatch.setattr(m, "RUN_ROOT", tmp_path / "metric")
    monkeypatch.setattr(cli, "PROMPT_PATH", p)
    monkeypatch.setattr(m, "load_baseline_manifest", lambda *a, **k: SimpleNamespace(sources={}, receipt={"manifest_sha256": "a" * 64}))
    if drift == "ids":
        gold = replace(gold, labels=gold.labels[:-1] + ({**gold.labels[-1], "document_id": "other"},))
    if drift == "labels":
        gold = replace(gold, labels=({**gold.labels[0], "problem_signal": None},) + gold.labels[1:])
    if drift == "quota":
        inference = replace(inference, receipt={**inference.receipt, "source_counts": {}})
    monkeypatch.setattr(m, "build_development_inference", lambda _: inference)
    monkeypatch.setattr(m, "build_development_gold_sidecar", lambda _: gold)
    monkeypatch.setattr(m, "_load_baseline", lambda *args: ({}, {"baseline_sha256": "b" * 64}))
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="other-cli" if drift == "cli_version" else claim["cli_version"]))
    monkeypatch.setattr(cli, "run_document", lambda *a, **k: pytest.fail("must not call model"))
    with pytest.raises(m.MetricBlocked):
        m.prepare()
    assert not m.RUN_ROOT.exists()


@pytest.mark.parametrize("payload", ["{", '{"status":"MEASURED"}'])
def test_corrupt_terminal_receipt_falls_back_to_durable_progress(environment, monkeypatch, capsys, payload):
    m, _, calls, _, transport = environment

    def stop(doc, **kwargs):
        transport(doc, **kwargs)
        raise SystemExit("simulated stop")

    monkeypatch.setattr(cli, "run_document", stop)
    with pytest.raises(SystemExit):
        m.run_metric()
    progress = m.RUN_ROOT / "progress.json"
    frozen = progress.read_bytes()
    terminal = m.RUN_ROOT / "metric.receipt.json"
    terminal.write_text(payload)
    assert m.main(["--inspect"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "TERMINAL_RECEIPT_INVALID"
    assert result["evaluation_status"] == "INCOMPLETE"
    assert result["counts"]["attempted_unknown"] == 1
    assert result["counts"]["not_attempted"] == 39
    assert sum(result["counts"].values()) == 40
    assert progress.read_bytes() == frozen
    assert terminal.read_text() == payload
    assert len(calls) == 1


def test_terminal_receipt_becomes_visible_only_as_complete_json(environment, monkeypatch, capsys):
    m, _, _, _, _ = environment
    real_link = m.os.link
    publications = []

    def publish(source, target):
        assert not Path(target).exists()
        value = json.loads(Path(source).read_text())
        assert value["status"] == "MEASURED"
        assert sum(value["counts"].values()) == 40
        assert Path(source).stat().st_mode & 0o777 == 0o600
        publications.append(value)
        real_link(source, target)

    monkeypatch.setattr(m.os, "link", publish)
    assert m.main(["--execute"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert publications == [result]
    assert m.main(["--inspect"]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert not list(m.RUN_ROOT.glob(".receipt-*"))


def test_terminal_publication_failure_retains_progress_and_no_partial_final(environment, monkeypatch, capsys):
    m, _, calls, _, _ = environment

    def fail(*args):
        raise OSError(PRIVATE)

    monkeypatch.setattr(m.os, "link", fail)
    assert m.main(["--execute"]) == 4
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "STORAGE_FAILURE"
    assert result["counts"]["valid_extraction"] == 40
    assert result["evaluation_status"] == "INCOMPLETE"
    assert len(calls) == 40
    assert not (m.RUN_ROOT / "metric.receipt.json").exists()
    assert not list(m.RUN_ROOT.glob(".receipt-*"))
    assert m.main(["--inspect"]) == 1
    assert json.loads(capsys.readouterr().out)["counts"]["valid_extraction"] == 40


def test_terminal_atomic_publisher_never_overwrites_existing_file(environment):
    m, _, _, _, _ = environment
    m.RUN_ROOT.mkdir(mode=0o700)
    path = m.RUN_ROOT / "metric.receipt.json"
    path.write_text("preserved receipt")
    publisher = getattr(m, "_publish_receipt", None)
    assert callable(publisher), "atomic terminal publisher is required"
    with pytest.raises(FileExistsError):
        publisher(m.RUN_ROOT, {"status": "INCOMPLETE"})
    assert path.read_text() == "preserved receipt"
    assert not list(m.RUN_ROOT.glob(".receipt-*"))


@pytest.mark.parametrize("delay,expected_calls", [(1801, 0), (1790, 1)])
def test_deadline_rechecked_after_durable_start_marker(environment, monkeypatch, capsys, delay, expected_calls):
    m, _, calls, clock, transport = environment
    real_save = m._save_progress
    delayed = [False]
    timeouts = []

    def save(root, progress):
        real_save(root, progress)
        if progress["rows"][0]["state"] == "attempt_started" and not delayed[0]:
            delayed[0] = True
            clock[0] += delay

    def process(doc, **kwargs):
        timeouts.append(kwargs["timeout"])
        transport(doc, **kwargs)
        raise cli.CliContractError("CLI_TIMEOUT")

    monkeypatch.setattr(m, "_save_progress", save)
    monkeypatch.setattr(cli, "run_document", process)
    assert m.main(["--execute"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "INCOMPLETE"
    assert len(calls) == expected_calls
    assert sum(result["counts"].values()) == 40
    assert result["counts"]["attempt_started"] == result["counts"]["attempted_unknown"] == 0
    if expected_calls:
        assert timeouts == [10]
    else:
        assert timeouts == []
        assert result["reason"] == "RUN_DEADLINE"
        assert result["counts"]["not_attempted"] == 40


@pytest.mark.parametrize("detail,count,detected", [
    ("NO_COMPLETED_AGENT_MESSAGE", 0, False),
    ("MULTIPLE_COMPLETED_AGENT_MESSAGES", 2, False),
    ("NON_STRING_AGENT_MESSAGE", None, True),
])
def test_metric_terminal_diagnostics_reach_cli_progress_and_receipt(environment, monkeypatch, capsys, detail, count, detected):
    m, _, calls, _, transport = environment
    expected = {"reason_detail": detail, "completed_agent_message_count": count,
                "non_string_message_detected": detected}

    def fail(doc, **kwargs):
        transport(doc, **kwargs)
        raise cli.CliContractError("CLI_OUTPUT_MISSING", terminal_diagnostics={**expected, PRIVATE: PRIVATE})

    monkeypatch.setattr(cli, "run_document", fail)
    assert m.main(["--execute"]) == 1
    result = json.loads(capsys.readouterr().out)
    progress = json.loads((m.RUN_ROOT / "progress.json").read_text())
    assert progress["rows"][0]["terminal_diagnostics"] == expected
    assert progress["rows"][0]["error_code"] == "CLI_OUTPUT_MISSING"
    assert result["terminal_diagnostics"] == [expected]
    assert result["counts"]["operational_failure"] == 1
    assert result["counts"]["not_attempted"] == 39
    assert len(calls) == 1
    assert json.loads((m.RUN_ROOT / "metric.receipt.json").read_text()) == result
    assert m.main(["--inspect"]) == 1
    assert json.loads(capsys.readouterr().out) == result
    for path in m.RUN_ROOT.iterdir():
        assert PRIVATE not in path.read_text()


def test_old_metric_receipt_and_progress_do_not_backfill_terminal_metadata(environment, monkeypatch, capsys):
    m, _, calls, _, transport = environment

    def fail(doc, **kwargs):
        transport(doc, **kwargs)
        raise cli.CliContractError("CLI_OUTPUT_MISSING")

    monkeypatch.setattr(cli, "run_document", fail)
    assert m.main(["--execute"]) == 1
    old = json.loads(capsys.readouterr().out)
    assert "terminal_diagnostics" not in old
    frozen = {p.name: p.read_bytes() for p in m.RUN_ROOT.iterdir()}
    assert m.main(["--inspect"]) == 1
    assert json.loads(capsys.readouterr().out) == old
    assert frozen == {p.name: p.read_bytes() for p in m.RUN_ROOT.iterdir()}
    (m.RUN_ROOT / "metric.receipt.json").unlink()
    assert "terminal_diagnostics" not in m.inspect_run()
    assert len(calls) == 1
