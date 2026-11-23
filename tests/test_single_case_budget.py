"""Offline custody tests. All files stay in a separate synthetic sandbox."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import pytest


NAME = "src.extraction.single_case_budget"
AVAILABLE = importlib.util.find_spec(NAME) is not None
SANDBOX = Path("/private/tmp/research-auto-66574-mock-v1")
# Synthetic test-client custody, separate from budget files. Tokens are retained only
# when initialize_budget returns successfully and explicitly passed to child processes.
_COMPLETIONS: dict[str, str] = {}


def _initialize(api, root, binding):
    token = api.initialize_budget(root, binding)
    _COMPLETIONS[str(root)] = token
    return token


def _send(api, root, binding, payload, sender):
    return api.send_once(root, binding, payload, sender,
                         completion_token=_COMPLETIONS.get(str(root)))


def test_budget_implementation_exists():
    assert AVAILABLE, "Approved durable budget implementation has not been created"


@pytest.fixture
def case(monkeypatch):
    import src.extraction.single_case_budget as api

    def denied(*args, **kwargs):
        raise AssertionError("network is forbidden in offline tests")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    assert not SANDBOX.is_symlink()
    SANDBOX.mkdir(mode=0o700, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="case-", dir=SANDBOX))
    payload = {"document_id": "github:5034214812", "text": "synthetic offline input"}
    binding = {
        "approval_id": "MOCK-66574-" + work.name,
        "document_id": payload["document_id"], "model": "mock-only",
        "source_sha256": "a" * 64, "prompt_sha256": "b" * 64,
        "schema_sha256": "c" * 64, "code_sha256": "d" * 64,
        "request_sha256": sha256(api.canonical_json(payload)).hexdigest(),
        "max_requests": 1,
    }
    return api, work / "budget", binding, payload


def _child(root, binding, payload, action="send", crash=False, completion_token=None):
    # Separate interpreter: no inherited Python budget object or fake call counter.
    program = r'''
import json, os, socket, sys
from pathlib import Path
from src.extraction.single_case_budget import BudgetBlocked, initialize_budget, send_once
def deny(*args, **kwargs): raise AssertionError("network forbidden")
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
root = Path(sys.argv[1]); binding = json.loads(sys.argv[2]); payload = json.loads(sys.argv[3])
def sender(value):
    with (root.parent / "fake-sends.log").open("ab", buffering=0) as stream:
        stream.write(b"SEND\n"); os.fsync(stream.fileno())
    if sys.argv[5] == "True": os._exit(17)
    return {"mock": True}
try:
    if sys.argv[4] == "initialize": initialize_budget(root, binding)
    else: send_once(root, binding, payload, sender, completion_token=json.loads(sys.argv[6]))
except BudgetBlocked:
    sys.exit(3)
'''
    return [sys.executable, "-B", "-c", program, str(root), json.dumps(binding),
            json.dumps(payload), action, str(crash),
            json.dumps(completion_token if completion_token is not None else _COMPLETIONS.get(str(root)))]


@pytest.mark.skipif(not AVAILABLE, reason="implementation absent during RED")
class TestBudget:
    def test_one_send_and_separate_results(self, case):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        raw = {"abstention_reason": "missing required fact", "actor": None}
        output = _send(api, root, binding, payload, lambda value: raw)
        packet = api.separate_assessments(output, {"status": "NOT_ASSESSED"},
                                          {"status": "NOT_ASSESSED"}, {"decision": "HOLD"})
        packet["human_card"]["supplement"] = "human-only interpretation"
        assert json.loads(packet["model_raw_json"]) == raw
        assert packet["model_contract"]["status"] == "NOT_ASSESSED"
        assert packet["model_content_quality"]["status"] == "NOT_ASSESSED"
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, lambda value: pytest.fail("second send"))

    def test_simultaneous_processes(self, case):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        children = [subprocess.Popen(_child(root, binding, payload), stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE) for _ in range(8)]
        codes = []
        for child in children:
            _, err = child.communicate(timeout=15)
            assert child.returncode in (0, 3), err.decode()
            codes.append(child.returncode)
        assert codes.count(0) == 1
        assert (root.parent / "fake-sends.log").read_bytes() == b"SEND\n"

    def test_thread_and_reentrant_entry(self, case):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        calls = []
        def sender(value):
            calls.append(value)
            with pytest.raises(api.BudgetBlocked):
                _send(api, root, binding, payload, sender)
            return {"mock": True}
        def attempt(_):
            try:
                _send(api, root, binding, payload, sender)
                return True
            except api.BudgetBlocked:
                return False
        with ThreadPoolExecutor(max_workers=16) as pool:
            assert sum(pool.map(attempt, range(32))) == 1
        assert len(calls) == 1

    @pytest.mark.parametrize("error", [OSError("response lost"), TimeoutError("timeout")])
    def test_failure_never_refunds(self, case, error):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        calls = []
        def sender(value):
            calls.append(value)
            raise error
        with pytest.raises(type(error)):
            _send(api, root, binding, payload, sender)
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, sender)
        assert len(calls) == 1

    def test_restart_after_sender_crash(self, case):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        assert subprocess.run(_child(root, binding, payload, crash=True), timeout=15).returncode == 17
        assert subprocess.run(_child(root, binding, payload), timeout=15).returncode == 3
        assert (root.parent / "fake-sends.log").read_bytes() == b"SEND\n"

    def test_crash_after_consumption_before_send(self, case):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        command = _child(root, binding, payload)
        original = 'if sys.argv[4] == "initialize": initialize_budget(root, binding)'
        command[3] = command[3].replace(original,
            'import src.extraction.single_case_budget as api\n'
            '    real_sync = api._sync_directory\n'
            '    def crash(fd): real_sync(fd); os._exit(19)\n'
            '    api._sync_directory = crash\n'
            '    if sys.argv[4] == "initialize": initialize_budget(root, binding)')
        assert subprocess.run(command, timeout=15).returncode == 19
        assert not (root.parent / "fake-sends.log").exists()
        assert subprocess.run(_child(root, binding, payload), timeout=15).returncode == 3

    @pytest.mark.parametrize("filename", ["approval.json", "state.json", "lock", "ready.json"])
    @pytest.mark.parametrize("damage", ["missing", "corrupt"])
    def test_missing_or_corrupt_custody(self, case, filename, damage):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        if damage == "missing": (root / filename).unlink()
        else: (root / filename).write_bytes(b"corrupt")
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, lambda value: pytest.fail("unsafe send"))
        assert subprocess.run(_child(root, binding, payload), timeout=15).returncode == 3
        with pytest.raises(api.BudgetBlocked): _initialize(api, root, binding)

    def test_missing_root_not_recreated(self, case):
        api, root, binding, payload = case
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, lambda value: pytest.fail("uninitialized"))
        assert not root.exists()

    @pytest.mark.parametrize("field", ["approval_id", "document_id", "model", "source_sha256",
                                      "prompt_sha256", "schema_sha256", "code_sha256", "request_sha256"])
    def test_binding_mismatch(self, case, field):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        changed = dict(binding, **{field: "e" * 64})
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, changed, payload, lambda value: pytest.fail("mismatch"))

    def test_payload_hash_mismatch(self, case):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, dict(payload, text="changed"), lambda value: pytest.fail("drift"))

    def test_duplicate_initialization_preserves_record(self, case):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        before = (root / "approval.json").read_bytes()
        with pytest.raises(api.BudgetBlocked): _initialize(api, root, binding)
        assert before == (root / "approval.json").read_bytes()

    @pytest.mark.parametrize("failure_at", range(1, 8))
    def test_initialization_sync_failure_stays_blocked_after_restart(self, case, monkeypatch, failure_at):
        api, root, binding, payload = case
        real_sync = api.os.fsync
        sync_count = 0
        def fail_selected(fd):
            nonlocal sync_count
            sync_count += 1
            if sync_count == failure_at:
                raise OSError("injected initialization sync failure")
            return real_sync(fd)
        with monkeypatch.context() as patch:
            patch.setattr(api.os, "fsync", fail_selected)
            with pytest.raises(api.BudgetBlocked): _initialize(api, root, binding)
        assert sync_count >= failure_at
        calls = []
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, lambda value: calls.append(value))
        assert calls == []
        assert subprocess.run(_child(root, binding, payload), timeout=15).returncode == 3
        assert not (root.parent / "fake-sends.log").exists()
        with pytest.raises(api.BudgetBlocked): _initialize(api, root, binding)

    def test_initialization_holds_lock_through_final_sync(self, case, monkeypatch):
        api, root, binding, payload = case
        # Knowing a token must not bypass the initializer's lock before it returns.
        monkeypatch.setattr(api.secrets, "token_hex", lambda size: "f" * 64)
        real_sync = api._sync_directory
        raced = False
        def race_before_sync(fd):
            nonlocal raced
            if (root / "ready.json").exists() and not raced:
                raced = True
                result = subprocess.run(_child(root, binding, payload, completion_token="f" * 64), timeout=15)
                assert result.returncode == 3, "execution admitted before initialization finalized"
            return real_sync(fd)
        monkeypatch.setattr(api, "_sync_directory", race_before_sync)
        _initialize(api, root, binding)
        assert raced
        assert not (root.parent / "fake-sends.log").exists()
        assert subprocess.run(_child(root, binding, payload), timeout=15).returncode == 0
        assert (root.parent / "fake-sends.log").read_bytes() == b"SEND\n"

    def test_failed_initialization_blocks_even_if_ready_rename_fails(self, case, monkeypatch):
        api, root, binding, payload = case
        real_sync = api._sync_directory
        def fail_after_ready(fd):
            if (root / "ready.json").exists():
                raise OSError("injected initialization sync failure")
            return real_sync(fd)
        def fail_rename(*args, **kwargs):
            raise PermissionError("injected ready rename failure")
        with monkeypatch.context() as patch:
            patch.setattr(api, "_sync_directory", fail_after_ready)
            patch.setattr(api.os, "rename", fail_rename)
            with pytest.raises(api.BudgetBlocked): _initialize(api, root, binding)
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, lambda value: pytest.fail("failed cleanup admitted send"))
        assert subprocess.run(_child(root, binding, payload), timeout=15).returncode == 3

    @pytest.mark.parametrize("ready_sync", [1, 2, 3])
    def test_initializer_crash_requires_returned_completion(self, case, ready_sync):
        api, root, binding, payload = case
        command = _child(root, binding, payload, action="initialize")
        original = 'if sys.argv[4] == "initialize": initialize_budget(root, binding)'
        command[3] = command[3].replace(original,
            'import src.extraction.single_case_budget as api\n'
            '    original_sync = api._sync_directory\n'
            '    ready_syncs = 0\n'
            '    def kill_before_completion(fd):\n'
            '        global ready_syncs\n'
            '        if (root / "ready.json").exists():\n'
            '            ready_syncs += 1\n'
            f'            if {ready_sync} < 3 and ready_syncs == {ready_sync}: os._exit(23)\n'
            '        original_sync(fd)\n'
            f'        if {ready_sync} == 3 and ready_syncs == 2: os._exit(23)\n'
            '    api._sync_directory = kill_before_completion\n'
            '    if sys.argv[4] == "initialize": initialize_budget(root, binding)')
        assert subprocess.run(command, timeout=15).returncode == 23
        calls = []
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, lambda value: calls.append(value))
        assert calls == []
        assert subprocess.run(_child(root, binding, payload), timeout=15).returncode == 3
        assert not (root.parent / "fake-sends.log").exists()

    @pytest.mark.parametrize("provided", ["missing", "malformed", "stored_hash", "foreign"])
    def test_completion_cannot_be_recovered_or_substituted(self, case, provided):
        api, root, binding, payload = case
        token = _initialize(api, root, binding)
        ready = json.loads((root / "ready.json").read_text())
        assert ready["completion_sha256"] == sha256(token.encode("ascii")).hexdigest()
        assert all(token.encode() not in path.read_bytes() for path in root.iterdir())
        if provided == "missing":
            wrong = None
        elif provided == "malformed":
            wrong = "not-a-completion-token"
        elif provided == "stored_hash":
            wrong = ready["completion_sha256"]
        else:
            other = root.parent / "other-budget"
            wrong = _initialize(api, other, dict(binding, approval_id="MOCK-OTHER"))
        with pytest.raises(api.BudgetBlocked):
            api.send_once(root, binding, payload, lambda value: pytest.fail("invalid completion"),
                          completion_token=wrong)
        assert not (root / "consumed.json").exists()
        # A valid caller-held token still works; invalid input did not spend/refund it.
        assert _send(api, root, binding, payload, lambda value: "mock") == "mock"

    def test_completion_loss_stops_client_and_restarted_process(self, case):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        del _COMPLETIONS[str(root)]
        before = {path.name: path.read_bytes() for path in root.iterdir()}
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, lambda value: pytest.fail("token recovered"))
        assert subprocess.run(_child(root, binding, payload), timeout=15).returncode == 3
        assert before == {path.name: path.read_bytes() for path in root.iterdir()}
        assert not (root.parent / "fake-sends.log").exists()

    @pytest.mark.parametrize("boundary", ["file", "directory"])
    def test_sync_failure_sends_nothing_and_never_retries(self, case, monkeypatch, boundary):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        with monkeypatch.context() as patch:
            def fail(*args): raise OSError("injected fsync failure")
            patch.setattr(api.os if boundary == "file" else api,
                          "fsync" if boundary == "file" else "_sync_directory", fail)
            with pytest.raises(api.BudgetBlocked):
                _send(api, root, binding, payload, lambda value: pytest.fail("sync failure"))
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, lambda value: pytest.fail("refunded"))

    @pytest.mark.parametrize("filename", ["approval.json", "state.json", "lock", "ready.json"])
    def test_symlink_custody_rejected(self, case, filename):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        target = root.parent / "outside"
        (root / filename).rename(target)
        (root / filename).symlink_to(target)
        with pytest.raises(api.BudgetBlocked):
            _send(api, root, binding, payload, lambda value: pytest.fail("link followed"))

    def test_symlink_parent_rejected(self, case):
        api, root, binding, payload = case
        root.mkdir()
        link = root.parent / "link"
        link.symlink_to(root, target_is_directory=True)
        with pytest.raises(api.BudgetBlocked): _initialize(api, link / "new", binding)
        assert not (root / "new").exists()

    def test_file_modes(self, case):
        api, root, binding, payload = case
        _initialize(api, root, binding)
        _send(api, root, binding, payload, lambda value: {})
        assert root.stat().st_mode & 0o777 == 0o700
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
