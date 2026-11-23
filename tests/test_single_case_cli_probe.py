"""Offline CLI preparation tests; never invoke codex exec or a network provider."""
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import signal
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

AVAILABLE = importlib.util.find_spec('src.extraction.single_case_cli_probe') is not None


def test_cli_probe_exists():
    assert AVAILABLE, 'approved CLI preparation runner absent'


@pytest.fixture
def case(monkeypatch):
    from src.extraction import single_case_cli_probe as api
    def denied(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    root = Path('/private/tmp/research-auto-cli-offline-tests')
    root.mkdir(mode=0o700, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='mock-', dir=root))
    document = {'document_id':'github:5034214812','source':'github','title':'synthetic',
                'text':'alpha\r\nβ🧪  original','published_at':'2026-01-01'}
    return api, work, document


def abstain():
    fields = 'observation_type actor problem context consequence evidence_quote evidence_start evidence_end problem_signal money_signal money_signal_type usable_evidence confidence'.split()
    return dict.fromkeys(fields) | {'document_id':'github:5034214812','abstention_reason':'insufficient evidence'}


def events(output=None):
    return (json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(output or abstain())}})+'\n'+json.dumps({'type':'turn.completed'})+'\n').encode()


@pytest.mark.skipif(not AVAILABLE, reason='implementation absent during RED')
class TestCLI:
    @pytest.mark.parametrize('kind', ['missing','duplicate','incomplete','invalid','wrong_id','error','tool'])
    def test_contract_failures_not_normal_abstention(self, case, kind):
        api, work, doc = case
        raw = events()
        if kind == 'missing': raw = b'{"type":"turn.completed"}\n'
        if kind == 'duplicate': raw = events()+events()
        if kind == 'incomplete': raw = raw.splitlines(keepends=True)[0]
        if kind == 'invalid': raw = b'not-json\n'
        if kind == 'wrong_id': raw = events(dict(abstain(), document_id='wrong'))
        if kind == 'error': raw += b'{"type":"error"}\n'
        if kind == 'tool': raw += b'{"type":"item.started","item":{"type":"command_execution"}}\n'
        result = api.assess(raw, b'', 0, None, doc)
        assert result['status'] in {'output_contract_failure','experiment_invalid'}
        assert result['content_quality'] == 'NOT_ASSESSED'

    def test_raw_output_separate_from_human_judgment(self, case):
        api, work, doc = case
        raw = events()
        result = api.assess(raw,b'',0,None,doc)
        assert result['contract_status'] == 'valid_abstention'
        assert result['model_output'] == abstain()
        assert result['content_quality'] == 'NOT_ASSESSED' and result['human_card'] == 'NOT_RUN'
        assert raw == events()

    @pytest.mark.parametrize('program,reason', [
        ('import time; time.sleep(5)', 'timeout'),
        ('import os; os.write(1,b"x"*10000)', 'output_limit'),
        ('print(\'{"type":"item.started","item":{"type":"command_execution"}}\',flush=True); import time;time.sleep(5)', 'tool_event')])
    def test_streamed_limits_terminate_without_retry(self, case, program, reason):
        api, work, doc = case
        calls=[]
        def spawn(*args, **kwargs):
            calls.append(1)
            return subprocess.Popen([sys.executable,'-B','-c',program], **kwargs)
        capture = api.capture(['not-a-real-cli'],b'',work,spawn=spawn,seconds=0.1,limit=512)
        assert capture.reason == reason
        assert len(capture.stdout)+len(capture.stderr)<=512 and calls == [1]

    def test_successful_capture_preserves_raw_stream(self, case):
        api, work, doc = case
        raw=events()
        def spawn(*args, **kwargs):
            return subprocess.Popen([sys.executable,'-B','-c','import os;os.write(1,'+repr(raw)+')'],**kwargs)
        captured=api.capture(['fake'],b'',work,spawn=spawn)
        assert captured.stdout==raw and captured.reason is None and captured.exit_code==0

    @pytest.mark.parametrize('kind', ['item.started', 'item.completed'])
    def test_error_diagnostic_does_not_stop_capture_or_discard_answer(self, case, kind):
        api, work, doc = case
        diagnostic = json.dumps({'type':kind, 'item':{'type':'error',
            'message':'Model metadata not found; defaulting to fallback metadata'}}).encode()+b'\n'
        raw = diagnostic+events()
        calls = []
        def spawn(*args, **kwargs):
            calls.append(1)
            return subprocess.Popen([sys.executable,'-B','-c',
                'import os;os.write(1,'+repr(raw)+')'], **kwargs)
        captured = api.capture(['synthetic-only'],b'',work,spawn=spawn)
        assert captured.reason is None, 'error item incorrectly stopped capture as a tool'
        assert captured.stdout == raw and captured.exit_code == 0 and calls == [1]
        result = api.assess(captured.stdout,b'',0,None,doc)
        assert result['contract_status'] == 'valid_abstention'
        assert result['diagnostic_item_count'] == 1
        assert result['content_quality'] == 'NOT_ASSESSED' and result['human_card'] == 'NOT_RUN'

    @pytest.mark.parametrize('terminal', ['valid', 'missing', 'error', 'turn.failed'])
    def test_assess_error_item_uses_terminal_result_not_tool_classification(self, case, terminal):
        api, work, doc = case
        diagnostic = b'{"type":"item.completed","item":{"type":"error","message":"diagnostic"}}\n'
        raw = diagnostic+(events() if terminal != 'missing' else b'')
        if terminal in ('error','turn.failed'):
            raw += json.dumps({'type':terminal}).encode()+b'\n'
        result = api.assess(raw,b'',0,None,doc)
        assert result['status'] != 'experiment_invalid', 'diagnostic is not a tool event'
        assert result['diagnostic_item_count'] == 1
        if terminal == 'valid':
            assert result['contract_status'] == 'valid_abstention'
        else:
            assert result['status'] == 'output_contract_failure'
            assert result['contract_status'] == 'FAILED'
        assert result['content_quality'] == 'NOT_ASSESSED' and result['human_card'] == 'NOT_RUN'

    @pytest.mark.parametrize('tool', ['command_execution', 'mcp_tool_call', 'web_search', 'unknown_item'])
    def test_error_item_does_not_allow_following_tool_event(self, case, tool):
        api, work, doc = case
        raw = b'{"type":"item.completed","item":{"type":"error","message":"diagnostic"}}\n'
        raw += json.dumps({'type':'item.started','item':{'type':tool}}).encode()+b'\n'
        result = api.assess(raw,b'',0,None,doc)
        assert result['status'] == 'experiment_invalid' and result['reason'] == 'tool_event'
        calls = []
        def spawn(*args, **kwargs):
            calls.append(1)
            return subprocess.Popen([sys.executable,'-B','-c',
                'import os,time;os.write(1,'+repr(raw)+');time.sleep(5)'], **kwargs)
        captured = api.capture(['synthetic-only'],b'',work,spawn=spawn,seconds=0.5)
        assert captured.reason == 'tool_event' and calls == [1]

    def test_discovery_link_bound_and_no_wrapper_read(self, case):
        api, work, doc = case
        executable=work/'entry';executable.write_text('do not execute or read body');executable.chmod(0o700)
        (work/'codex').symlink_to(executable)
        result=api.discover(str(work))
        assert result['path']==str(executable) and result['links_followed']==1
        with pytest.raises(api.CLIBlocked):api.discover(str(work),max_links=0)
        with pytest.raises(api.CLIBlocked):api.discover(str(work),max_entries=0)

    def test_attempt_budget_concurrent_failure_never_refunded(self, case):
        api, work, doc = case
        from src.extraction.single_case_budget import initialize_budget,send_once,BudgetBlocked,canonical_json
        from hashlib import sha256
        binding={'approval_id':'MOCK-CLI','document_id':doc['document_id'],'model':'mock',
                 **{k:'a'*64 for k in ['source_sha256','prompt_sha256','schema_sha256','code_sha256']},
                 'request_sha256':sha256(canonical_json(doc)).hexdigest(),'max_requests':1}
        token=initialize_budget(work/'budget',binding);calls=[]
        def sender(value):calls.append(1);raise TimeoutError('synthetic')
        def attempt(_):
            try:send_once(work/'budget',binding,doc,sender,completion_token=token)
            except (BudgetBlocked,TimeoutError):pass
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(attempt,range(12)))
        assert calls==[1]

    def test_storage_failure_retains_capture_and_never_appends(self, case, monkeypatch):
        api,work,doc=case
        capture=api.Capture(events(),b'',0,None)
        real=api.os.fsync
        def fail(fd):raise OSError('synthetic storage failure')
        monkeypatch.setattr(api.os,'fsync',fail)
        with pytest.raises(api.CLIStorageError) as caught:
            api.store(work/'result',capture,api.assess(capture.stdout,b'',0,None,doc))
        assert caught.value.capture.stdout==capture.stdout
        assert (work/'result'/'stdout.jsonl').read_bytes()==capture.stdout
        monkeypatch.setattr(api.os,'fsync',real)
        with pytest.raises(api.CLIBlocked):api.store(work/'result',capture,{})

    def prepared(self, case, monkeypatch):
        api,work,doc=case
        original=work/'old';original.mkdir(mode=0o700)
        api.frozen._write(original/'document.json',doc)
        profile=api.frozen.load_inference_profile(api.frozen.PROFILE)
        monkeypatch.setattr(api,'V3',original)
        monkeypatch.setattr(api.frozen,'load_bundle',lambda *args:SimpleNamespace(profile=profile,manifest={'source_sha256':'a'*64}))
        exe=work/'fake-cli';exe.write_text('never execute');exe.chmod(0o700);info=exe.stat()
        cli={'path':str(exe),'fingerprint':[info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns], 'version':'synthetic'}
        root=work/'prepared';digest=api.prepare(root,cli)
        return root,digest

    def test_preparation_preserves_input_and_evaluation_separation(self,case,monkeypatch):
        api,work,doc=case;root,digest=self.prepared(case,monkeypatch)
        m,data=api.load(root,digest)
        assert data['document.json']==api.canonical_json(doc)
        assert data['stdin.txt'].endswith(data['document.json'])
        assert b'criteria' not in data['stdin.txt'] and b'human_card' not in data['stdin.txt']
        assert m['policy']['internal_request_count']=='UNVERIFIED'
        assert root.stat().st_mode&0o777==0o700
        assert all(v.stat().st_mode&0o777==0o600 for v in root.iterdir() if v.is_file())
        with pytest.raises(api.CLIBlocked):api.prepare(root,m['cli'])

    @pytest.mark.parametrize('name',['stdin.txt','schema.json','document.json','human-rubric.json'])
    def test_bundle_drift_blocks(self,case,monkeypatch,name):
        api,work,doc=case;root,digest=self.prepared(case,monkeypatch)
        with (root/name).open('ab') as stream:stream.write(b' ')
        with pytest.raises(api.CLIBlocked):api.load(root,digest)

    def test_connected_fake_execution_spends_once_and_preserves_raw(self,case,monkeypatch):
        api,work,doc=case;root,digest=self.prepared(case,monkeypatch)
        from src.extraction.single_case_budget import initialize_budget,BudgetBlocked
        token=initialize_budget(work/'budget',api.binding_for(root,digest,'MOCK'))
        calls=[];raw=events()
        def spawn(*args,**kwargs):
            calls.append(1)
            return subprocess.Popen([sys.executable,'-B','-c','import sys,os;sys.stdin.buffer.read();os.write(1,'+repr(raw)+')'],**kwargs)
        result=api.execute_approved(root,digest,work/'budget',token,'MOCK',work/'result',spawn=spawn)
        assert result['contract_status']=='valid_abstention'
        assert (work/'result'/'stdout.jsonl').read_bytes()==raw
        assert json.loads((work/'result'/'result.json').read_bytes())['human_card']=='NOT_RUN'
        with pytest.raises(BudgetBlocked):api.execute_approved(root,digest,work/'budget',token,'MOCK',work/'other-result',spawn=spawn)
        assert calls==[1]

    def test_close_failure_keeps_capture_and_closes_remaining_outputs(self,case,monkeypatch):
        api,work,doc=case;captured=api.Capture(events(),b'',0,None)
        original=api.os.fdopen;closed=[]
        class Stream:
            def __init__(self,inner):self.inner=inner
            def __getattr__(self,name):return getattr(self.inner,name)
            def close(self):
                self.inner.close();closed.append(1)
                if len(closed)==1:raise OSError('synthetic late close')
        monkeypatch.setattr(api.os,'fdopen',lambda *args,**kwargs:Stream(original(*args,**kwargs)))
        with pytest.raises(api.CLIStorageError) as caught:api.store(work/'close-result',captured,{})
        assert caught.value.capture is captured and closed==[1,1,1]
        assert (work/'close-result'/'stdout.jsonl').read_bytes()==captured.stdout

    def test_bad_output_path_blocks_before_launch_or_spend(self,case,monkeypatch):
        api,work,doc=case;root,digest=self.prepared(case,monkeypatch)
        from src.extraction.single_case_budget import initialize_budget
        token=initialize_budget(work/'budget',api.binding_for(root,digest,'MOCK'))
        output=work/'already-there';output.mkdir()
        with pytest.raises(api.CLIBlocked):
            api.execute_approved(root,digest,work/'budget',token,'MOCK',output,
                spawn=lambda *args,**kwargs:pytest.fail('unexpected launcher'))
        assert not (work/'budget'/'consumed.json').exists()

    def test_whole_workflow_deadline_does_not_create_or_spend(self,case,monkeypatch):
        api,work,doc=case
        import time
        monkeypatch.setattr(api.frozen,'WORKFLOW_SECONDS',0.03)
        monkeypatch.setattr(api,'load',lambda *args:time.sleep(1))
        with pytest.raises(TimeoutError):
            api.execute_approved(work/'bundle','a'*64,work/'missing-budget','f'*64,'MOCK',work/'out')
        assert not (work/'out').exists() and not (work/'missing-budget').exists()

    @pytest.mark.parametrize('fault', ['selector_create','blocking_1','blocking_2','blocking_3',
                                      'register_1','register_2','register_3','stdin_close'])
    def test_post_launch_setup_failure_reaps_and_closes(self,case,monkeypatch,fault):
        api,work,doc=case
        children=[];watchers=[];kills=[];blocking=[];closed=[]
        original_selector=api.selectors.DefaultSelector
        original_blocking=api.os.set_blocking;original_killpg=api.os.killpg
        error=OSError('synthetic setup failure')
        class Watcher:
            def __init__(self):
                if fault=='selector_create':raise error
                self.inner=original_selector();self.registrations=0;self.was_closed=False
                watchers.append(self)
            def register(self,*args,**kwargs):
                self.registrations+=1
                if fault=='register_'+str(self.registrations):raise error
                return self.inner.register(*args,**kwargs)
            def close(self):self.was_closed=True;self.inner.close()
            def __getattr__(self,name):return getattr(self.inner,name)
        def set_blocking(*args):
            blocking.append(1)
            if fault=='blocking_'+str(len(blocking)):raise error
            return original_blocking(*args)
        def killpg(pid,sig):
            kills.append((pid,sig));return original_killpg(pid,sig)
        class CloseFailure:
            def __init__(self,inner):self.inner=inner;self.calls=0
            def close(self):
                self.calls+=1
                if self.calls==1:raise error
                self.inner.close()
            def __getattr__(self,name):return getattr(self.inner,name)
        def spawn(*args,**kwargs):
            child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'],**kwargs)
            children.append(child)
            if fault=='stdin_close':child.stdin=CloseFailure(child.stdin)
            return child
        monkeypatch.setattr(api.selectors,'DefaultSelector',Watcher)
        monkeypatch.setattr(api.os,'set_blocking',set_blocking)
        monkeypatch.setattr(api.os,'killpg',killpg)
        try:
            with pytest.raises(OSError) as caught:
                api.capture(['synthetic-only'],b'' if fault=='stdin_close' else b'input',work,spawn=spawn,seconds=.1)
            child=children[0]
            assert child.poll() is not None, 'post-launch setup failure left child alive'
            assert caught.value is error, 'original setup error lost'
            assert len(children)==1 and (child.pid,signal.SIGKILL) in kills
            assert all(w.was_closed for w in watchers)
            assert all(s.closed for s in (child.stdin,child.stdout,child.stderr))
        finally:
            # Reap on RED too: failing implementation must not leak test children.
            for child in children:
                if child.poll() is None:
                    try:original_killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                child.wait(timeout=2)
                for stream in (child.stdin,child.stdout,child.stderr):
                    if not stream.closed:stream.close()
            for w in watchers:
                if not w.was_closed:w.close()

    @pytest.mark.parametrize('cleanup_fault',['selector_close','wait','stdin_close'])
    def test_cleanup_failure_does_not_skip_other_resources_or_mask_setup_error(self,case,monkeypatch,cleanup_fault):
        api,work,doc=case;children=[];watchers=[]
        original_selector=api.selectors.DefaultSelector
        setup_error=OSError('synthetic setup failure')
        class Watcher:
            def __init__(self):self.inner=original_selector();self.closed=False;watchers.append(self)
            def register(self,*args,**kwargs):raise setup_error
            def close(self):
                self.inner.close();self.closed=True
                if cleanup_fault=='selector_close':raise OSError('synthetic selector close')
        class Pipe:
            def __init__(self,inner):self.inner=inner
            def __getattr__(self,name):return getattr(self.inner,name)
            def close(self):self.inner.close();raise OSError('synthetic pipe close')
        def spawn(*args,**kwargs):
            child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'],**kwargs)
            children.append(child)
            if cleanup_fault=='wait':
                original_wait=child.wait
                def wait(*args,**kwargs):original_wait(*args,**kwargs);raise OSError('synthetic wait failure after reap')
                child.wait=wait
            if cleanup_fault=='stdin_close':child.stdin=Pipe(child.stdin)
            return child
        monkeypatch.setattr(api.selectors,'DefaultSelector',Watcher)
        with pytest.raises(OSError) as caught:api.capture(['synthetic'],b'input',work,spawn=spawn)
        assert caught.value is setup_error
        assert children[0].poll() is not None and len(children)==1
        assert all(s.closed for s in (children[0].stdin,children[0].stdout,children[0].stderr))
        assert all(s.closed for s in watchers)
        assert any('Additional cleanup failures' in n for n in setup_error.__notes__)
