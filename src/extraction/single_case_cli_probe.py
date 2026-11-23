"""Frozen #66574 CLI experiment. No automatic initialization or model invocation.

Preparation is offline. execute_approved requires separately approved custody and
manifest. CLI tool prevention/internal requests remain unverified. Event rejection
is post-hoc detection; successful abstention is not a content-quality verdict.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time

from jsonschema import Draft202012Validator
from src.extraction import single_case_probe as frozen
from src.extraction.single_case_budget import canonical_json, _directory, send_once
from src.extraction.development_slice import validate_extraction

V3 = Path('/private/tmp/research-auto-66574-extraction-v1/prepared-v3')
V3_SHA = 'e87a09fc3fc63f4486b5359455d1edde64187734d5ce9b7bdf269df2c817d5a4'
MODEL = 'gpt-5.6'
LIMIT = 131072
POLICY = {'max_processes':1,'wrapper_retries':0,'process_seconds':120,
          'workflow_seconds':600,'combined_output_bytes':LIMIT,
          'tool_prevention':'UNVERIFIED','internal_request_count':'UNVERIFIED'}
RUBRIC = {'quality':'NOT_ASSESSED','human_card':'NOT_RUN','criteria':[
    'No facts invented beyond source','Quote and character offsets match source',
    'Proposals/comparison experiments distinct from performed workplace actions',
    'Abstain where required evidence is insufficient'],
    'normal_abstention_requires':'Valid schema, document identity and justified missing evidence',
    'claim':'Not independent holdout or product validation'}

class CLIBlocked(RuntimeError): pass

@dataclass(frozen=True)
class Capture:
    stdout: bytes
    stderr: bytes
    exit_code: int
    reason: str | None

class CLIStorageError(CLIBlocked):
    def __init__(self, capture):
        self.capture = capture
        super().__init__('storage failed; retain capture in memory only; durability unverified; no rerun')

def digest(raw): return sha256(raw).hexdigest()

def discover(path_value: str, *, max_entries=32, max_links=8) -> dict:
    """One bounded PATH pass; metadata/readlink only, never read wrapper bodies."""
    start=time.monotonic();links=0
    if len(os.fsencode(path_value))>131072: raise CLIBlocked('PATH too large')
    for index,entry in enumerate(path_value.split(os.pathsep)):
        if index>=max_entries or time.monotonic()-start>=600: raise CLIBlocked('discovery limit')
        if not entry: continue
        candidate=Path(entry)/'codex'
        if not candidate.is_absolute() or '..' in candidate.parts: raise CLIBlocked('invalid PATH')
        pending=list(candidate.parts[1:]);resolved=Path('/')
        while pending:
            if time.monotonic()-start>=600: raise CLIBlocked('discovery timeout')
            part=pending.pop(0)
            if part in ('','.'):continue
            if part=='..':resolved=resolved.parent;continue
            current=resolved/part
            try: info=current.lstat()
            except FileNotFoundError:break
            if stat.S_ISLNK(info.st_mode):
                if links>=max_links:raise CLIBlocked('link limit')
                links+=1;target=Path(os.readlink(current))
                if target.is_absolute():resolved=Path('/');parts=target.parts[1:]
                else:parts=target.parts
                pending=list(parts)+pending;continue
            resolved=current
            if not pending:
                if not stat.S_ISREG(info.st_mode) or not info.st_mode&0o111:break
                return {'path':str(resolved),'links_followed':links,'PATH_entries':index+1,
                        'fingerprint':[info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns],
                        'identity_scope':'metadata only, executable body not hashed'}
    raise CLIBlocked('no executable in bounded PATH; no substitution')

def code_hashes():
    names=list(frozen.DEPENDENCIES)+['src/extraction/single_case_cli_probe.py']
    return {name:digest(frozen._read(frozen.ROOT/name)) for name in names}

def prepare(destination: Path, cli: dict) -> str:
    old=frozen.load_bundle(V3,V3_SHA)
    document=frozen._read(V3/'document.json',private=True)
    prompt=old.profile.prompt_text.encode()
    schema=canonical_json(old.profile.output_schema)
    stdin=prompt+b'\n\nSource document JSON:\n'+document
    payloads={'document.json':document,'prompt.txt':prompt,'schema.json':schema,
              'stdin.txt':stdin,'human-rubric.json':canonical_json(RUBRIC)}
    root=Path(destination)
    argv=[cli['path'],'exec','--ephemeral','--ignore-user-config','--ignore-rules',
          '--strict-config','--json','--output-schema',str(root/'schema.json'),
          '--model',MODEL,'--sandbox','read-only','--cd',str(root/'work'),
          '--skip-git-repo-check','-']
    manifest={'schema_version':'single-case-cli/v1','api_manifest_sha256':V3_SHA,
              'document_id':frozen.DOC_ID,'source_sha256':old.manifest['source_sha256'],
              'requested_model':MODEL,'model_availability':'UNVERIFIED','cli':cli,'argv':argv,
              'files':{name:digest(raw) for name,raw in payloads.items()},'code_hashes':code_hashes(),
              'policy':dict(POLICY),'claim':'NOT_CALIBRATION_OR_PRODUCT_VALIDATION',
              'pricing':'CLI account billing UNVERIFIED; API price estimate does not apply',
              'import':'NOT_RUN','corpus':'NOT_RUN'}
    try:
        with _directory(root.parent) as parent:os.mkdir(root.name,0o700,dir_fd=parent)
        with _directory(root) as parent:os.mkdir('work',0o700,dir_fd=parent)
        for name,raw in payloads.items():frozen._write(root/name,raw,raw=True)
        frozen._write(root/'manifest.json',manifest)
    except OSError as error:raise CLIBlocked('prepare destination exists/unavailable; no overwrite') from error
    return digest(canonical_json(manifest))

def load(root: Path, approved_sha: str):
    raw=frozen._read(root/'manifest.json',private=True)
    if digest(raw)!=approved_sha:raise CLIBlocked('manifest mismatch')
    m=json.loads(raw)
    if m['code_hashes']!=code_hashes() or m['policy']!=POLICY:raise CLIBlocked('code/policy drift')
    data={name:frozen._read(root/name,private=True) for name in m['files']}
    if any(digest(data[k])!=v for k,v in m['files'].items()):raise CLIBlocked('bundle drift')
    info=Path(m['cli']['path']).lstat()
    if not stat.S_ISREG(info.st_mode) or [info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns]!=m['cli']['fingerprint']:
        raise CLIBlocked('CLI metadata drift')
    return m,data

def assess(stdout,stderr,exit_code,reason,document):
    result={'status':'output_contract_failure','contract_status':'FAILED','model_output':None,
            'content_quality':'NOT_ASSESSED','human_card':'NOT_RUN','reason':reason,
            'diagnostic_item_count':0}
    if reason=='tool_event':return dict(result,status='experiment_invalid')
    if reason or exit_code!=0:return dict(result,status='operational_failure',contract_status='NOT_VALIDATED')
    messages=[];completed=0
    try:
        for line in stdout.decode('utf-8').splitlines():
            e=json.loads(line);kind=e['type']
            if kind in ('error','turn.failed'):raise ValueError('error event')
            if kind=='turn.completed':completed+=1
            elif kind.startswith('item.'):
                item=e['item']
                # CLI error items can carry nonfatal metadata diagnostics. Keep the
                # raw event and judge the terminal result; this is not a tool call.
                if item['type']=='error':
                    result['diagnostic_item_count']+=1
                    continue
                if item['type'] not in ('agent_message','reasoning'):return dict(result,status='experiment_invalid',reason='tool_event')
                if kind=='item.completed' and item['type']=='agent_message':messages.append(item['text'])
            elif kind not in ('thread.started','turn.started'):raise ValueError('unknown event')
        if completed!=1 or len(messages)!=1:raise ValueError('terminal count')
        output=json.loads(messages[0]);result['model_output']=output
        profile=frozen.load_inference_profile(frozen.PROFILE)
        Draft202012Validator(profile.output_schema).validate(output)
        validate_extraction(dict(document,source_url=''),output)
    except Exception as error:return dict(result,reason=type(error).__name__)
    return dict(result,status='contract_valid',contract_status='valid_abstention' if output['abstention_reason'] else 'valid_extraction',reason=None)

def capture(argv,stdin,cwd,*,spawn=None,seconds=120,limit=LIMIT):
    """Stream with combined byte cap and process-group kill; no retries."""
    spawn=spawn or subprocess.Popen;began=time.monotonic();out=bytearray();err=bytearray();line=bytearray();reason=None
    sel=None;offset=0
    process=spawn(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                  cwd=cwd,start_new_session=True)
    try:
        # Cleanup ownership starts before any post-launch resource setup.
        sel=selectors.DefaultSelector()
        for stream,name in [(process.stdout,'out'),(process.stderr,'err'),(process.stdin,'in')]:
            os.set_blocking(stream.fileno(),False)
            if name!='in' or stdin:sel.register(stream,selectors.EVENT_WRITE if name=='in' else selectors.EVENT_READ,name)
            else:stream.close()
        while sel.get_map():
            left=seconds-(time.monotonic()-began)
            if left<=0:reason='timeout';break
            for key,_ in sel.select(min(left,0.05)):
                if key.data=='in':
                    try:n=os.write(key.fd,stdin[offset:offset+4096]);offset+=n
                    except BrokenPipeError:offset=len(stdin)
                    if offset==len(stdin):sel.unregister(key.fileobj);key.fileobj.close()
                    continue
                chunk=os.read(key.fd,4096)
                if not chunk:sel.unregister(key.fileobj);continue
                space=limit-len(out)-len(err);kept=chunk[:space]
                (out if key.data=='out' else err).extend(kept)
                if len(chunk)>space:reason='output_limit';break
                if key.data=='out':
                    line.extend(kept)
                    while b'\n' in line:
                        row,_,rest=line.partition(b'\n');line=bytearray(rest)
                        try:event=json.loads(row)
                        except (ValueError,UnicodeError):continue
                        if isinstance(event,dict) and str(event.get('type','')).startswith('item.'):
                            item=event.get('item',{})
                            if isinstance(item,dict) and item.get('type') not in ('agent_message','reasoning','error'):
                                reason='tool_event';break
                if reason:break
            if reason:break
        if reason is None:
            try:process.wait(timeout=max(0.001,seconds-(time.monotonic()-began)))
            except subprocess.TimeoutExpired:reason='timeout'
    finally:
        original_error=sys.exc_info()[1]
        cleanup_errors=[]
        # Also stop descendants if the leader exited but children retained pipes.
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        except BaseException as error:
            cleanup_errors.append(error)
            try:process.kill()
            except ProcessLookupError:pass
            except BaseException as fallback_error:cleanup_errors.append(fallback_error)
        try:process.wait(timeout=2)
        except BaseException as error:cleanup_errors.append(error)
        if sel is not None:
            try:sel.close()
            except BaseException as error:cleanup_errors.append(error)
        for stream in (process.stdin,process.stdout,process.stderr):
            try:
                if stream is not None and not stream.closed:stream.close()
            except BaseException as error:cleanup_errors.append(error)
        if cleanup_errors:
            if original_error is None:raise cleanup_errors[0]
            original_error.add_note('Additional cleanup failures: '+', '.join(type(e).__name__ for e in cleanup_errors))
    return Capture(bytes(out),bytes(err),process.returncode,reason)

@contextmanager
def sink(root):
    streams=[]
    try:
        with _directory(root.parent) as d:os.mkdir(root.name,0o700,dir_fd=d)
        with _directory(root) as d:
            for name in ('stdout.jsonl','stderr.txt','result.json'):
                fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=d)
                streams.append(os.fdopen(fd,'wb'))
        yield streams
    except FileExistsError as error:raise CLIBlocked('output already exists; no overwrite') from error
    finally:
        failure=None
        for stream in streams:
            try:stream.close()
            except BaseException as error:failure=error
        if failure is not None:raise failure

def persist(root,streams,captured,result):
    try:
        for stream,raw in zip(streams,(captured.stdout,captured.stderr,canonical_json(result))):
            if stream.write(raw)!=len(raw):raise OSError('short write')
            stream.flush();os.fsync(stream.fileno())
        with _directory(root) as d:os.fsync(d)
    except Exception as error:raise CLIStorageError(captured) from error

def store(root,captured,result):
    try:
        with sink(root) as streams:persist(root,streams,captured,result)
    except CLIBlocked:raise
    except Exception as error:raise CLIStorageError(captured) from error

def binding_for(root,approved_sha,approval_id):
    m,data=load(root,approved_sha);document=json.loads(data['document.json'])
    return {'approval_id':approval_id,'document_id':frozen.DOC_ID,'model':MODEL,
            'source_sha256':m['source_sha256'],'prompt_sha256':digest(data['prompt.txt']),
            'schema_sha256':digest(data['schema.json']),
            'code_sha256':digest(canonical_json({'manifest_sha256':approved_sha,'code':m['code_hashes']})),
            'request_sha256':digest(canonical_json(document)),'max_requests':1}

def execute_approved(root,approved_sha,budget,token,approval_id,output,*,spawn=None):
    """Separate live approval required; never initialize or recover custody here."""
    with frozen._workflow_deadline():
        m,data=load(root,approved_sha);document=json.loads(data['document.json'])
        binding=binding_for(root,approved_sha,approval_id);captured=None
        try:
            with sink(output) as streams:
                captured=send_once(budget,binding,document,
                    lambda _:capture(m['argv'],data['stdin.txt'],root/'work',spawn=spawn),completion_token=token)
                result=assess(captured.stdout,captured.stderr,captured.exit_code,captured.reason,document)
                persist(output,streams,captured,result)
        except CLIBlocked:raise
        except Exception as error:
            if captured is not None:raise CLIStorageError(captured) from error
            raise
        return result
