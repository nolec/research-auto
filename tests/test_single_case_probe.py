"""Synthetic/offline tests only; no real collection, credentials, or provider calls."""
from __future__ import annotations

import importlib.util
import io
import json
import socket
import tempfile
import time
from types import SimpleNamespace
from email.message import Message
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener
from urllib.response import addinfourl

import pytest

NAME = "src.extraction.single_case_probe"
AVAILABLE = importlib.util.find_spec(NAME) is not None
ROOT = Path("/private/tmp/research-auto-66574-extraction-v1")


def test_probe_implementation_exists():
    assert AVAILABLE, "Single-case frozen preparation adapter not implemented"


@pytest.fixture
def bundle(monkeypatch):
    import src.extraction.single_case_probe as api
    def denied(*args, **kwargs): raise AssertionError("external network forbidden")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    assert not ROOT.is_symlink()
    ROOT.mkdir(mode=0o700, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="mock-", dir=ROOT))
    items = ["uninterpreted"] * 100
    items[91] = {"document_id": "github:5034214812", "source_item_id": "5034214812",
                 "source": "github", "title": "local example",
                 "text": "alpha\r\nβ🧪  preserved spaces\n", "published_at": "2026-01-01T00:00:00Z"}
    source = work / "synthetic-collection.json"
    source.write_bytes(json.dumps({"items": items}, ensure_ascii=False).encode())
    digest = sha256(source.read_bytes()).hexdigest()
    prepared = work / "prepared"
    manifest_sha = api.prepare_bundle(prepared, source_path=source, expected_source_sha256=digest)
    return api, work, prepared, source, digest, manifest_sha


def _response(output, *, status="completed"):
    return io.BytesIO(json.dumps({"status": status, "model": "mock-resolved",
        "usage": {"input_tokens": 100, "output_tokens": 30},
        "output": [{"content": [{"type": "output_text", "text": json.dumps(output)}]}]}).encode())


def _abstain(document_id="github:5034214812"):
    keys = ("observation_type actor problem context consequence evidence_quote evidence_start "
            "evidence_end problem_signal money_signal money_signal_type usable_evidence confidence").split()
    return dict.fromkeys(keys) | {"document_id": document_id, "abstention_reason": "missing consequence"}


@pytest.mark.skipif(not AVAILABLE, reason="implementation absent during RED")
class TestProbe:
    def test_fixed_record_original_text_and_input_separation(self, bundle):
        api, work, prepared, source, digest, manifest_sha = bundle
        loaded = api.load_bundle(prepared, manifest_sha)
        assert loaded.document["text"] == json.loads(source.read_bytes())["items"][91]["text"]
        assert set(loaded.document) == {"document_id", "source", "title", "text", "published_at"}
        body = json.loads(loaded.request_bytes)
        assert json.loads(body["input"][1]["content"]) == loaded.document
        assert "HOLD" not in body["input"][1]["content"]
        assert body["store"] is False
        assert body["max_output_tokens"] == 1200
        assert loaded.manifest["source_sha256"] == digest
        assert prepared.stat().st_mode & 0o777 == 0o700
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in prepared.iterdir())

    def test_no_overwrite_and_hash_mismatch(self, bundle):
        api, work, prepared, source, digest, manifest_sha = bundle
        before = (prepared / "manifest.json").read_bytes()
        with pytest.raises(api.ProbeBlocked):
            api.prepare_bundle(prepared, source_path=source, expected_source_sha256=digest)
        with pytest.raises(api.ProbeBlocked):
            api.prepare_bundle(work / "bad", source_path=source, expected_source_sha256="0" * 64)
        assert before == (prepared / "manifest.json").read_bytes()
        assert not (work / "bad").exists()

    def test_identity_mismatch_never_substitutes(self, bundle):
        api, work, prepared, source, digest, manifest_sha = bundle
        value = json.loads(source.read_bytes())
        value["items"][91]["document_id"] = "github:other"
        source.write_text(json.dumps(value))
        with pytest.raises(api.ProbeBlocked):
            api.prepare_bundle(work / "bad-id", source_path=source,
                               expected_source_sha256=sha256(source.read_bytes()).hexdigest())

    @pytest.mark.parametrize("name", ["request.json", "document.json", "manifest.json"])
    def test_bundle_tampering_is_blocked(self, bundle, name):
        api, work, prepared, source, digest, manifest_sha = bundle
        with (prepared / name).open("ab") as stream: stream.write(b" ")
        with pytest.raises(api.ProbeBlocked): api.load_bundle(prepared, manifest_sha)

    def test_wrong_approval_stops_before_credentials_or_budget(self, bundle, monkeypatch):
        api, work, prepared, source, digest, manifest_sha = bundle
        with pytest.raises(api.ProbeBlocked):
            api.run_approved(prepared, work / "not-initialized", "f" * 64,
                             "MOCK-PROBE", "0" * 64, api_key="dummy")
        assert not (work / "not-initialized").exists()

    def test_transport_is_exactly_one_call_and_abstention_not_quality_pass(self, bundle):
        api, work, prepared, source, digest, manifest_sha = bundle
        loaded = api.load_bundle(prepared, manifest_sha)
        calls = []
        def opener(request, *, timeout):
            calls.append(request.data)
            assert timeout == 120
            assert request.data == loaded.request_bytes
            return _response(_abstain())
        result = api.call_transport(loaded, api_key="dummy", opener=opener)
        assert len(calls) == 1
        assert result["contract_status"] == "valid_abstention"
        assert result["content_quality"] == "NOT_ASSESSED"
        assert result["human_card"] == "NOT_RUN"
        assert result["model_output"] == _abstain()

    @pytest.mark.parametrize("error", [TimeoutError("mock"), HTTPError("https://example.test",429,"mock",{},None)])
    def test_transport_never_retries(self, bundle, error):
        api, work, prepared, source, digest, manifest_sha = bundle
        loaded = api.load_bundle(prepared, manifest_sha)
        calls = []
        def opener(*args, **kwargs): calls.append(1); raise error
        result = api.call_transport(loaded, api_key="dummy", opener=opener)
        assert len(calls) == 1
        assert result["status"] == "operational_failure"
        assert result["content_quality"] == "NOT_ASSESSED"

    def test_redirect_does_not_create_followup(self, bundle):
        api, *_ = bundle
        with pytest.raises(api.ProbeBlocked):
            api.NoRedirect().redirect_request(None,None,302,"mock",{},"https://other.test")

    def test_urllib_redirect_chain_stops_at_first_response(self, bundle):
        api, work, prepared, source, digest, manifest_sha = bundle
        calls = []
        class FakeHTTPS(HTTPSHandler):
            def https_open(self, request):
                calls.append(request.full_url)
                headers = Message()
                headers["Location"] = "https://other.test/never-follow"
                response = addinfourl(io.BytesIO(b""), headers, request.full_url, 302)
                response.msg = "mock redirect"
                return response
        opener = build_opener(ProxyHandler({}),api.NoRedirect(),FakeHTTPS()).open
        result = api.call_transport(api.load_bundle(prepared,manifest_sha),api_key="dummy",opener=opener)
        assert result["status"] == "operational_failure"
        assert calls == ["https://api.openai.com/v1/responses"]

    @pytest.mark.parametrize("kind", ["incomplete", "invalid_json", "wrong_id", "empty"])
    def test_bad_output_never_becomes_normal_abstention(self, bundle, kind):
        api, work, prepared, source, digest, manifest_sha = bundle
        loaded = api.load_bundle(prepared, manifest_sha)
        def opener(*args, **kwargs):
            if kind == "invalid_json": return io.BytesIO(b"not-json")
            if kind == "incomplete": return _response(_abstain(), status="incomplete")
            if kind == "wrong_id": return _response(_abstain("wrong"))
            return _response({})
        result = api.call_transport(loaded, api_key="dummy", opener=opener)
        assert result["status"] == "output_contract_failure"
        assert result["content_quality"] == "NOT_ASSESSED"

    def test_process_deadline_stops_hung_work(self, bundle):
        api, *_ = bundle
        start = time.monotonic()
        result = api.supervise(lambda: time.sleep(30), timeout=0.08)
        assert time.monotonic() - start < 3
        assert result["status"] == "operational_failure"

    def test_workflow_deadline_covers_preflight_without_attempt(self, bundle, monkeypatch):
        api, work, prepared, source, digest, manifest_sha = bundle
        monkeypatch.setattr(api, "WORKFLOW_SECONDS", 0.05)
        monkeypatch.setattr(api, "load_bundle", lambda *args: time.sleep(30))
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            api.run_approved(prepared,work/"budget","f"*64,"MOCK",manifest_sha,api_key="dummy")
        assert time.monotonic()-start < 3
        assert not (work/"budget").exists()

    def test_budget_is_connected_before_transport_and_not_refunded(self, bundle):
        api, work, prepared, source, digest, manifest_sha = bundle
        from src.extraction.single_case_budget import initialize_budget
        budget = work / "budget"
        token = initialize_budget(budget, api.binding_for(prepared, "MOCK-PROBE", manifest_sha))
        log = work / "fake-http.log"
        def opener(*args, **kwargs):
            with log.open("ab") as stream:stream.write(b"HTTP\n")
            raise TimeoutError("fake response lost")
        first = api.run_approved(prepared,budget,token,"MOCK-PROBE",manifest_sha,api_key="dummy",opener=opener)
        second = api.run_approved(prepared,budget,token,"MOCK-PROBE",manifest_sha,api_key="dummy",opener=opener)
        assert first["status"] == "operational_failure"
        assert second["status"] == "operational_failure"
        assert log.read_bytes() == b"HTTP\n"

    def test_invalid_result_destination_blocks_before_attempt(self, bundle, monkeypatch):
        api, work, prepared, source, digest, manifest_sha = bundle
        completion = work / "mock-completion.json"
        completion.write_text(json.dumps({"completion_token": "f" * 64}))
        completion.chmod(0o600)
        target = work / "result.json"
        target.symlink_to(work / "missing-target")
        def attempted(*args, **kwargs): pytest.fail("attempted before output reservation")
        monkeypatch.setattr(api, "run_approved", attempted)
        monkeypatch.setattr(api.sys, "argv", ["probe", "execute", "--bundle", str(prepared),
            "--budget", str(work / "budget"), "--completion-file", str(completion),
            "--output-file", str(target), "--approval-sha256", manifest_sha,
            "--approval-id", "MOCK", "--accept-config-pricing"])
        with pytest.raises(api.ProbeBlocked): api.main()

    def test_cli_deadline_includes_completion_read(self, bundle, monkeypatch):
        api, work, prepared, source, digest, manifest_sha = bundle
        completion = work / "slow-completion.json"
        completion.write_text(json.dumps({"completion_token": "f" * 64}))
        completion.chmod(0o600)
        original_read = api._read
        def slow_read(path, **kwargs):
            if path == completion: time.sleep(0.15)
            return original_read(path, **kwargs)
        monkeypatch.setattr(api, "_read", slow_read)
        monkeypatch.setattr(api, "WORKFLOW_SECONDS", 0.04)
        monkeypatch.setattr(api, "run_approved", lambda *args, **kwargs: {"status":"mock-only"})
        monkeypatch.setattr(api.sys, "argv", ["probe", "execute", "--bundle", str(prepared),
            "--budget", str(work / "budget"), "--completion-file", str(completion),
            "--output-file", str(work / "result.json"), "--approval-sha256", manifest_sha,
            "--approval-id", "MOCK", "--accept-config-pricing"])
        with pytest.raises(TimeoutError): api.main()
        assert not (work / "budget").exists()

    def test_nested_workflow_stage_does_not_restart_deadline(self, bundle, monkeypatch):
        api, *_ = bundle
        monkeypatch.setattr(api, "WORKFLOW_SECONDS", 0.07)
        with pytest.raises(TimeoutError):
            with api._workflow_deadline():
                time.sleep(0.04)
                with api._workflow_deadline():
                    time.sleep(0.04)

    @pytest.mark.parametrize("fault", ["fsync_error", "fsync_timeout", "deadline",
                                       "partial_write", "flush", "close"])
    def test_late_storage_failure_preserves_result_without_retry(self, bundle, monkeypatch, fault):
        api, work, prepared, source, digest, manifest_sha = bundle
        completion = work / "completion.json"
        completion.write_text(json.dumps({"completion_token": "f" * 64}))
        completion.chmod(0o600)
        output = work / "late-result.json"
        result = {"status": "contract_valid", "model_output": _abstain(),
                  "content_quality": "NOT_ASSESSED", "human_card": "NOT_RUN"}
        original_bytes = api.canonical_json(result)
        attempts = []
        def fake_run(*args, **kwargs):
            attempts.append(1)
            return result
        monkeypatch.setattr(api, "run_approved", fake_run)
        original_fsync = api.os.fsync
        fired = []
        def failing_fsync(fd):
            if fault in {"fsync_error", "fsync_timeout", "deadline"} and not fired:
                fired.append(1)
                if fault == "deadline": time.sleep(10)
                if fault == "fsync_timeout": raise TimeoutError("synthetic late timeout")
                raise OSError("synthetic storage failure")
            return original_fsync(fd)
        monkeypatch.setattr(api.os, "fsync", failing_fsync)
        if fault == "deadline": monkeypatch.setattr(api, "WORKFLOW_SECONDS", 0.15)
        original_fdopen = api.os.fdopen
        class FaultyStream:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args):
                self.stream.close()
                if fault == "close": raise OSError("synthetic close failure")
            def write(self, data):
                if fault == "partial_write":
                    self.stream.write(data[:12])
                    self.stream.flush()
                    raise OSError("synthetic partial write")
                return self.stream.write(data)
            def flush(self):
                if fault == "flush": raise OSError("synthetic flush failure")
                return self.stream.flush()
            def fileno(self): return self.stream.fileno()
        def fdopen(fd, mode, *args, **kwargs):
            stream = original_fdopen(fd, mode, *args, **kwargs)
            return FaultyStream(stream) if mode == "wb" else stream
        monkeypatch.setattr(api.os, "fdopen", fdopen)
        args = SimpleNamespace(bundle=prepared, budget=work/"no-live-budget",
            completion_file=completion, output_file=output, approval_sha256=manifest_sha,
            approval_id="MOCK", accept_config_pricing=True)
        with pytest.raises(Exception) as captured: api._execute(args)
        stored = output.read_bytes()
        if fault == "partial_write":
            assert stored == original_bytes[:12]
        else:
            assert json.loads(stored) == result
        assert isinstance(captured.value, api.ResultStorageError)
        assert captured.value.result == result
        assert captured.value.result_bytes == original_bytes
        expected_stage = {"partial_write":"write", "flush":"flush", "close":"close"}.get(fault, "fsync")
        assert captured.value.stage == expected_stage
        assert isinstance(captured.value.__cause__, TimeoutError if fault in {"fsync_timeout", "deadline"} else OSError)
        assert attempts == [1]
        assert not args.budget.exists()
