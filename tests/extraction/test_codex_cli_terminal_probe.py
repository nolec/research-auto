from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.extraction import codex_cli_diagnostic as cli
from src.extraction.codex_cli_diagnostic import run_document as real_run_document

PRIVATE = 'PRIVATE_DO_NOT_PERSIST'


def module():
    assert importlib.util.find_spec('src.extraction.codex_cli_terminal_probe') is not None, 'isolated first-document probe is required'
    return importlib.import_module('src.extraction.codex_cli_terminal_probe')


def output(doc, abstain=False):
    value = dict(document_id=doc['document_id'], observation_type='user_problem', actor='user',
                 problem='export fails', context='export', consequence='no file',
                 evidence_quote=doc['text'], evidence_start=0, evidence_end=len(doc['text']),
                 problem_signal=True, money_signal=False, money_signal_type=None,
                 usable_evidence=True, confidence=0.8, abstention_reason=None)
    if abstain:
        value = {k: None for k in value}
        value.update(document_id=doc['document_id'], abstention_reason=PRIVATE)
    return value


@pytest.fixture
def environment(tmp_path, monkeypatch):
    m = module()
    roots = [tmp_path / f'old-v{i}' for i in range(1, 6)] + [tmp_path / 'metric-v1']
    for root in roots:
        root.mkdir()
        (root / 'preserved.json').write_text('{}')
    docs = tuple(dict(document_id=f'github:{i:02}-{PRIVATE}', source='github', title=PRIVATE,
                      text='The export fails.', published_at='2026-01-01T00:00:00Z',
                      source_url=f'https://example.test/{PRIVATE}') for i in range(40))
    prompt = b'frozen prompt'
    schema = cli.SCHEMA_PATH.read_bytes()
    bindings = dict(inference_corpus_sha256=cli._digest(docs), ordered_ids_sha256=cli._digest([d['document_id'] for d in docs]),
                    prompt_sha256=sha256(prompt).hexdigest(), output_schema_sha256=sha256(schema).hexdigest(),
                    implementation_bundle_sha256='a'*64)
    claim = dict(bindings=bindings)
    receipt = dict(bindings=bindings, status='INCOMPLETE', local_attempt_count=1)
    progress = dict(claim_sha256=cli._digest(claim), rows=[dict(ordinal=1, state='operational_failure', error_code='CLI_OUTPUT_MISSING')])
    pins = {}
    for name, value in [('metric.claim.json', claim), ('metric.receipt.json', receipt), ('progress.json', progress)]:
        raw = json.dumps(value).encode()
        (roots[-1] / name).write_bytes(raw)
        pins[name] = sha256(raw).hexdigest()
    prepared = SimpleNamespace(inference=SimpleNamespace(corpus=docs), prompt_bytes=prompt, schema_bytes=schema, bindings=bindings)
    monkeypatch.setattr(m, 'HISTORY_ROOTS', tuple(roots))
    monkeypatch.setattr(m, 'METRIC_ROOT', roots[-1])
    monkeypatch.setattr(m, 'SOURCE_HASHES', pins)
    monkeypatch.setattr(m, 'PROBE_ROOT', tmp_path / 'terminal-probe-v1')
    monkeypatch.setattr(m.metric, 'prepare', lambda: prepared)
    calls = []

    def transport(doc, **kwargs):
        assert doc == docs[0]
        assert kwargs['timeout'] == 120
        assert kwargs['prompt_text'] == prompt.decode()
        assert kwargs['schema_bytes'] == schema
        calls.append(doc)
        kwargs['usage_out'].update(input_tokens=10, output_tokens=2)
        return output(doc)

    monkeypatch.setattr(cli, 'run_document', transport)
    return m, roots, docs, calls, transport


@pytest.mark.parametrize('mode,status,code', [
    ('valid', 'NOT_REPRODUCED', 0), ('abstain', 'NOT_REPRODUCED', 0),
    ('absent', 'REPRODUCED', 1), ('multiple', 'REPRODUCED', 1), ('nonstring', 'REPRODUCED', 1),
    ('timeout', 'OTHER_FAILURE', 2), ('other', 'OTHER_FAILURE', 2), ('invalid', 'OTHER_FAILURE', 2),
])
def test_probe_cli_receipt_and_one_call(environment, monkeypatch, capsys, mode, status, code):
    m, roots, docs, calls, transport = environment
    before = m.inventory()
    expected = {'reason_detail': {'absent': 'NO_COMPLETED_AGENT_MESSAGE', 'multiple': 'MULTIPLE_COMPLETED_AGENT_MESSAGES',
                                'nonstring': 'NON_STRING_AGENT_MESSAGE'}.get(mode),
                'completed_agent_message_count': {'absent': 0, 'multiple': 2}.get(mode),
                'non_string_message_detected': mode == 'nonstring'}

    def process(doc, **kwargs):
        value = transport(doc, **kwargs)
        if mode == 'abstain':
            return output(doc, True)
        if mode in ('absent', 'multiple', 'nonstring'):
            raise cli.CliContractError('CLI_OUTPUT_MISSING', terminal_diagnostics={**expected, PRIVATE: PRIVATE})
        if mode in ('timeout', 'other'):
            raise cli.CliContractError('CLI_TIMEOUT' if mode == 'timeout' else 'CLI_TOOL_EVENT')
        if mode == 'invalid':
            return {**value, 'actor': None}
        return value

    monkeypatch.setattr(cli, 'run_document', process)
    assert m.main(['--execute']) == code
    value = json.loads(capsys.readouterr().out)
    assert value['status'] == status
    assert value['integrity'] == 'VERIFIED'
    assert value['historical_metric_v1_subtype'] == 'UNKNOWN'
    assert value['quality_metrics'] == 'NOT_EVALUATED'
    assert value['local_model_process_count'] == 1
    assert len(calls) == 1
    assert m.inventory() == before
    if status == 'REPRODUCED':
        assert value['terminal_diagnostics'] == expected
    else:
        assert 'terminal_diagnostics' not in value
    saved = json.loads((m.PROBE_ROOT / 'probe.receipt.json').read_text())
    assert saved == value
    claim = json.loads((m.PROBE_ROOT / 'probe.claim.json').read_text())
    assert value['claim_sha256'] == cli._digest(claim)
    assert value['bindings']['selected_document_sha256'] == cli._digest(docs[0])
    actual = {k: docs[0][k] for k in ('document_id', 'source', 'title', 'text', 'published_at')}
    assert value['bindings']['model_input_sha256'] == cli._digest(actual)
    assert value['bindings']['model_input_sha256'] != value['bindings']['selected_document_sha256']
    for name in ('source_metric_claim_sha256', 'source_metric_receipt_sha256', 'implementation_bundle_sha256', 'policy_sha256'):
        assert len(value['bindings'][name]) == 64
    for path in m.PROBE_ROOT.iterdir():
        assert PRIVATE not in path.read_text()
        assert path.stat().st_mode & 0o777 == 0o600
    frozen = {p.name: p.read_bytes() for p in m.PROBE_ROOT.iterdir()}
    assert m.main(['--inspect']) == code
    assert json.loads(capsys.readouterr().out) == value
    assert m.main(['--execute']) == 4
    assert json.loads(capsys.readouterr().out)['reason'] == 'ALREADY_CONSUMED'
    assert len(calls) == 1
    assert frozen == {p.name: p.read_bytes() for p in m.PROBE_ROOT.iterdir()}


@pytest.mark.parametrize('mode,expected_count', [
    ('missing', 0), ('permission', 0), ('operational', 0),
    ('timeout', 1), ('nonzero', 1), ('missing_output', 1), ('valid', 1), ('unknown', None),
])
def test_real_cli_wrapper_process_observations_reach_cli_and_receipt(environment, monkeypatch, capsys, mode, expected_count):
    m, _, docs, _, _ = environment
    invocations = []

    def subprocess_stub(command, **kwargs):
        invocations.append(command)
        if mode == 'missing':
            raise FileNotFoundError(PRIVATE)
        if mode == 'permission':
            raise PermissionError(PRIVATE)
        if mode == 'operational':
            raise OSError(PRIVATE)
        if mode == 'timeout':
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        if mode == 'unknown':
            raise RuntimeError(PRIVATE)
        events = [{'type': 'turn.completed'}]
        if mode == 'valid':
            events.insert(0, {'type': 'item.completed', 'item': {
                'type': 'agent_message', 'text': json.dumps(output(docs[0])),
            }})
        return SimpleNamespace(returncode=2 if mode == 'nonzero' else 0,
                               stdout='\n'.join(json.dumps(e) for e in events), stderr=PRIVATE)

    monkeypatch.setattr(cli, 'run_document', real_run_document)
    monkeypatch.setattr(cli.subprocess, 'run', subprocess_stub)
    code = m.main(['--execute'])
    value = json.loads(capsys.readouterr().out)
    assert value['local_model_process_count'] == expected_count
    assert value['local_model_call_attempt_count'] == 1
    assert len(invocations) == 1
    assert code == (0 if mode == 'valid' else 1 if mode == 'missing_output' else 2)
    assert PRIVATE not in json.dumps(value)
    assert json.loads((m.PROBE_ROOT / 'probe.receipt.json').read_text()) == value
    assert m.main(['--inspect']) == code
    assert json.loads(capsys.readouterr().out) == value


@pytest.mark.parametrize('mode', ['nonzero', 'timeout', 'launch', 'unsafe'])
def test_safe_process_diagnostics_survive_receipt_and_inspection(environment, monkeypatch, capsys, mode):
    m, _, _, calls, transport = environment
    before = m.inventory()
    expected = {
        'nonzero': dict(returncode=2, failure_stage='subprocess_exit', error_class='AUTHENTICATION_ERROR'),
        'timeout': dict(returncode=None, failure_stage='subprocess_timeout', error_class='TIMEOUT'),
        'launch': dict(returncode=None, failure_stage='subprocess_launch', error_class='PERMISSION_ERROR'),
        'unsafe': dict(returncode=None, failure_stage='contract_validation', error_class='UNKNOWN'),
    }[mode]

    def process(doc, **kwargs):
        transport(doc, **kwargs)
        error = cli.CliContractError('CLI_NONZERO_EXIT', **expected)
        error.diagnostics.update(stdout=PRIVATE, stderr=PRIVATE)
        if mode == 'unsafe':
            error.diagnostics.update(returncode=True, failure_stage=PRIVATE, error_class=PRIVATE)
        raise error

    monkeypatch.setattr(cli, 'run_document', process)
    assert m.main(['--execute']) == 2
    value = json.loads(capsys.readouterr().out)
    assert value['process_diagnostics'] == expected
    receipt_path = m.PROBE_ROOT / 'probe.receipt.json'
    assert json.loads(receipt_path.read_text()) == value
    assert PRIVATE not in receipt_path.read_text()
    assert m.main(['--inspect']) == 2
    assert json.loads(capsys.readouterr().out) == value
    assert m.inventory() == before
    assert len(calls) == 1

    # A legacy receipt without the optional metadata remains readable.
    legacy = {k: v for k, v in value.items() if k != 'process_diagnostics'}
    receipt_path.write_text(json.dumps(legacy))
    assert m.inspect_probe() == legacy
    for invalid in (None, {**expected, 'stderr': PRIVATE},
                    {**expected, 'returncode': True},
                    {**expected, 'failure_stage': [PRIVATE]},
                    {**expected, 'error_class': PRIVATE}):
        receipt_path.write_text(json.dumps({**value, 'process_diagnostics': invalid}))
        assert m.inspect_probe()['reason'] == 'TERMINAL_RECEIPT_INVALID'


def test_unobserved_call_attempts_are_not_inferred_from_claim(environment, monkeypatch, capsys):
    m, _, _, _, _ = environment
    monkeypatch.setattr(cli, 'run_document', lambda *a, **k: (_ for _ in ()).throw(SystemExit('stop')))
    with pytest.raises(SystemExit):
        m.run_probe()
    assert m.main(['--inspect']) == 5
    value = json.loads(capsys.readouterr().out)
    assert value['local_model_call_attempt_count'] is None
    assert value['local_model_process_count'] is None
    assert m.main(['--execute']) == 4
    blocked = json.loads(capsys.readouterr().out)
    assert blocked['local_model_call_attempt_count'] == 0
    assert blocked['local_model_process_count'] == 0


@pytest.mark.parametrize('drift', ['artifact', 'corpus', 'order', 'prompt', 'schema'])
def test_prerequisite_blocks_before_claim_and_call(environment, monkeypatch, capsys, drift):
    m, roots, _, calls, _ = environment
    if drift == 'artifact':
        (roots[-1] / 'metric.receipt.json').write_text('{}')
    else:
        real = m.metric.prepare
        def changed():
            value = real()
            key = {'corpus': 'inference_corpus_sha256', 'order': 'ordered_ids_sha256',
                   'prompt': 'prompt_sha256', 'schema': 'output_schema_sha256'}[drift]
            value.bindings[key] = '0'*64
            return value
        monkeypatch.setattr(m.metric, 'prepare', changed)
    assert m.main(['--execute']) == 4
    assert json.loads(capsys.readouterr().out)['status'] == 'BLOCKED'
    assert calls == []
    assert not m.PROBE_ROOT.exists()


@pytest.mark.parametrize('mode', ['forced', 'publish'])
def test_interruption_is_read_only_unknown_and_consumed(environment, monkeypatch, capsys, mode):
    m, _, _, calls, transport = environment
    if mode == 'forced':
        def stop(doc, **kwargs):
            transport(doc, **kwargs)
            raise SystemExit('simulated interruption')
        monkeypatch.setattr(cli, 'run_document', stop)
        with pytest.raises(SystemExit):
            m.run_probe()
    else:
        monkeypatch.setattr(m, 'publish', lambda *args: (_ for _ in ()).throw(OSError(PRIVATE)))
        assert m.main(['--execute']) == 5
        capsys.readouterr()
    assert (m.PROBE_ROOT / 'probe.claim.json').exists()
    assert not (m.PROBE_ROOT / 'probe.receipt.json').exists()
    before = {p.name: p.read_bytes() for p in m.PROBE_ROOT.iterdir()}
    assert m.main(['--inspect']) == 5
    value = json.loads(capsys.readouterr().out)
    assert value['status'] == 'INCOMPLETE'
    assert value['integrity'] == 'UNVERIFIED'
    assert value['local_model_process_count'] is None
    assert m.main(['--execute']) == 4
    assert json.loads(capsys.readouterr().out)['reason'] == 'ALREADY_CONSUMED'
    assert len(calls) == 1
    assert before == {p.name: p.read_bytes() for p in m.PROBE_ROOT.iterdir()}


@pytest.mark.parametrize('mode', ['changed', 'unreadable'])
def test_integrity_failure_overrides_exit_not_observed_outcome(environment, monkeypatch, capsys, mode):
    m, roots, _, calls, transport = environment
    real_inventory = m.inventory
    if mode == 'unreadable':
        def inventory():
            if calls:
                raise OSError(PRIVATE)
            return real_inventory()
        monkeypatch.setattr(m, 'inventory', inventory)
    def process(doc, **kwargs):
        value = transport(doc, **kwargs)
        if mode == 'changed':
            (roots[0] / 'preserved.json').write_text('external change')
        return value
    monkeypatch.setattr(cli, 'run_document', process)
    assert m.main(['--execute']) == 5
    value = json.loads(capsys.readouterr().out)
    assert value['status'] == 'NOT_REPRODUCED'
    assert value['integrity'] == ('FAILED' if mode == 'changed' else 'UNVERIFIED')
    assert len(calls) == 1
    if mode == 'changed':
        assert (roots[0] / 'preserved.json').read_text() == 'external change'


def test_atomic_publish_and_no_overwrite(environment, monkeypatch):
    m, _, _, _, _ = environment
    m.PROBE_ROOT.mkdir()
    real_link = m.os.link
    def link(source, target):
        assert not Path(target).exists()
        assert json.loads(Path(source).read_text()) == {'complete': True}
        real_link(source, target)
    monkeypatch.setattr(m.os, 'link', link)
    m.publish({'complete': True})
    frozen = (m.PROBE_ROOT / 'probe.receipt.json').read_bytes()
    monkeypatch.setattr(m.os, 'link', real_link)
    with pytest.raises(FileExistsError):
        m.publish({'complete': True})
    assert (m.PROBE_ROOT / 'probe.receipt.json').read_bytes() == frozen
    assert not list(m.PROBE_ROOT.glob('.receipt-*'))


def test_explicit_action_required(environment):
    m, _, _, calls, _ = environment
    with pytest.raises(SystemExit) as caught:
        m.main([])
    assert caught.value.code == 2
    assert not m.PROBE_ROOT.exists()
    assert calls == []


def test_real_fake_child_timeout_is_reaped_without_retry(tmp_path, monkeypatch):
    module()
    real_run = subprocess.run
    pid_path = tmp_path / 'child.pid'
    calls = []
    def local_child(command, **kwargs):
        calls.append(command)
        script = 'import os,time,pathlib; pathlib.Path(' + repr(str(pid_path)) + ').write_text(str(os.getpid())); time.sleep(30)'
        return real_run([sys.executable, '-c', script], **kwargs)
    monkeypatch.setattr(cli.subprocess, 'run', local_child)
    doc = dict(document_id='synthetic', source='github', title='local', text='export fails', published_at='2026-01-01')
    with pytest.raises(cli.CliContractError, match='CLI_TIMEOUT'):
        cli.run_document(doc, schema_path=cli.SCHEMA_PATH, prompt_text='local fake only', timeout=0.5)
    pid = int(pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert len(calls) == 1
