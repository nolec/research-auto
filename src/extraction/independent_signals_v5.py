"""Development-only independent signal classification; no product promotion."""
from __future__ import annotations

import argparse
import json
import time
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator
from src.extraction import codex_cli_diagnostic as cli
from src.extraction import codex_cli_development_v2 as previous
from src.extraction.calibration_evaluator import _empty_confusion, _record, _finish
from src.extraction.development_slice import _MONEY_TYPES
from src.extraction.codex_cli_metric import _save_progress

SIGNALS = ('problem_signal', 'money_signal', 'usable_evidence')
RUN_ID = 'codex-cli-gpt-6.2-sol-development-v5-independent-signals'
RUN_ROOT = previous.RUN_ROOT.parent / RUN_ID

def _signal_schema(money=False):
    fields = {'state': {'type': 'string', 'enum': ['yes', 'no', 'unknown']}, 'quote': {'type': ['string', 'null']}}
    if money:
        fields['type'] = {'type': ['string', 'null'], 'enum': [*sorted(_MONEY_TYPES), None]}
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}

SCHEMA = {'type': 'object', 'additionalProperties': False,
          'required': ['document_id', *SIGNALS], 'properties': {
              'document_id': {'type': 'string'}, **{s: _signal_schema(s == 'money_signal') for s in SIGNALS}}}
PROMPT = '''Classify the three signals independently from the supplied source text. Do not infer one from another.
Problem: concrete actor or situation, friction or unmet need, and consequence or desired outcome. Generic complaints are negative.
Money: author describes actual purchase, subscription, outsourcing, meaningful time spent, economic loss, explicit budget or willingness to pay, a concrete price complaint, or search for a paid alternative. A procurement request with explicit budget is willingness to pay, not completed purchase. Do not infer money from inconvenience, platform metadata, or an industry mention.
Usable evidence: a specific source quote showing who has the problem, what happens or why it matters without inventing context.
For each signal independently return yes, no or unknown. A yes needs an exact, nonempty verbatim substring of text (not title); for money also specify one matching type. Otherwise quote=null and money type=null. Use unknown if insufficient context, not for every absence of a positive signal. No need to invent actor or consequence for money. Never infer actual payment from budget. Preserve document_id. Return only the supplied schema.'''

def normalize_signals(document, output):
    Draft202012Validator(SCHEMA).validate(output)
    if output['document_id'] != document['document_id']:
        raise ValueError('document identity mismatch')
    result = {'document_id': document['document_id']}
    for signal in SIGNALS:
        item = output[signal]
        state, quote = item['state'], item['quote']
        money_type = item.get('type')
        if state == 'yes':
            start = document['text'].find(quote) if isinstance(quote, str) and quote.strip() else -1
            if start < 0 or (signal == 'money_signal' and money_type not in _MONEY_TYPES):
                result[signal] = {'state': 'invalid', 'reason': 'QUOTE_OR_TYPE_INVALID'}
            else:
                result[signal] = {'state': 'yes', 'start': start, 'end': start + len(quote)}
                if signal == 'money_signal':
                    result[signal]['type'] = money_type
        elif quote is not None or money_type is not None:
            result[signal] = {'state': 'invalid', 'reason': 'NONPOSITIVE_HAS_EVIDENCE'}
        else:
            result[signal] = {'state': state}
    return result


def score_signals(documents, labels, outputs):
    ids = [d['document_id'] for d in documents]
    if len(set(ids)) != len(ids) or len(labels) != len(ids) or len(outputs) != len(ids) or {l['document_id'] for l in labels} != set(ids) or [o['document_id'] for o in outputs] != ids:
        raise ValueError('evaluation membership mismatch')
    gold = {l['document_id']: l for l in labels}
    totals = {s: _empty_confusion() for s in SIGNALS}
    states = {s: dict.fromkeys(('yes', 'no', 'unknown', 'invalid'), 0) for s in SIGNALS}
    invalid_count = 0
    for o in outputs:
        invalid_count += any(o[s]['state'] == 'invalid' for s in SIGNALS)
        for s in SIGNALS:
            state = o[s]['state']
            actual = gold[o['document_id']][s]
            if type(actual) is not bool:
                raise ValueError('invalid gold label')
            states[s][state] += 1
            _record(totals[s], predicted=state == 'yes', actual=actual)
    return {'metrics': {s: _finish(totals[s]) for s in SIGNALS}, 'signal_states': states,
            'invalid_count': invalid_count, 'input_count': len(ids)}


def run_batch(root, inference, gold, call, bindings, baseline):
    if len(inference.corpus) != 40 or cli._digest(inference.corpus) != inference.receipt['inference_corpus_sha256'] or cli._digest(gold.labels) != gold.receipt['gold_sidecar_sha256']:
        raise ValueError('frozen corpus mismatch')
    # Validate membership before starting a process.
    unknown = [{'document_id': d['document_id'], **{s: {'state': 'unknown'} for s in SIGNALS}} for d in inference.corpus]
    score_signals(inference.corpus, gold.labels, unknown)
    root.mkdir(mode=0o700, exist_ok=False)
    cli._private_create(root / 'claim.json', {'run_id': RUN_ID, 'model': previous.MODEL, 'bindings': bindings,
                                         'policy': previous.POLICY, 'scope': 'independent_signal_diagnostic'})
    rows, outputs = [], []
    started = time.monotonic()
    reason = None
    for ordinal, d in enumerate(inference.corpus, 1):
        remaining = previous.POLICY['max_run_seconds'] - (time.monotonic() - started)
        if remaining <= 0:
            reason = 'RUN_DEADLINE'
            break
        row = {'ordinal': ordinal, 'state': 'attempt_started'}
        rows.append(row)
        _save_progress(root, {'rows': rows})
        try:
            raw, usage = call(d, min(remaining, previous.POLICY['timeout_seconds']))
            output = normalize_signals(d, raw)
        except cli.CliContractError as e:
            if str(e) in ('CLI_OUTPUT_SCHEMA_INVALID', 'CLI_DOCUMENT_ID_MISMATCH') and e.diagnostics.get('validation', {}).get('stage') in cli._VALIDATION_STAGES:
                output = {'document_id': d['document_id'], **{s: {'state': 'invalid', 'reason': 'OUTPUT_INVALID'} for s in SIGNALS}}
                usage = {}
                row['validation'] = e.diagnostics['validation']
            else:
                reason = str(e)
                row.update(state='failed', error=reason, error_class=e.diagnostics.get('error_class'))
        except Exception:
            reason = 'VALIDATION_OR_OPERATIONAL_FAILURE'
            row.update(state='failed', error=reason)
        if not reason:
            outputs.append(output)
            states = {s: output[s]['state'] for s in SIGNALS}
            row.update(state='invalid' if 'invalid' in states.values() else 'measured', signals={s: output[s] for s in SIGNALS},
                       usage={k: v for k, v in usage.items() if k in ('input_tokens', 'output_tokens') and type(v) is int and v >= 0})
        _save_progress(root, {'rows': rows})
        print(f'{ordinal}/40 {row["state"]}', flush=True)
        if reason:
            break
    result = {'run_id': RUN_ID, 'status': 'INCOMPLETE' if reason else 'MEASURED', 'reason': reason,
              'attempted': len(rows), 'elapsed_seconds': round(time.monotonic()-started, 3),
              'bindings': bindings, 'quality_gate_status': 'NOT_EVALUATED',
              'scope': 'signal classification only; not full observation extraction'}
    if not reason:
        result['evaluation'] = score_signals(inference.corpus, gold.labels, outputs)
        result['evaluation']['rule_baseline'] = baseline
        result['evaluation']['projection_sha256'] = cli._digest(outputs)
    cli._private_create(root / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    inference, gold, baseline, bindings, _, _ = previous.prepare()
    schema = json.dumps(SCHEMA, sort_keys=True).encode()
    Draft202012Validator.check_schema(SCHEMA)
    prompt = PROMPT.encode()
    bindings.update(v5_prompt_sha256=sha256(prompt).hexdigest(), v5_schema_sha256=sha256(schema).hexdigest(),
                    v5_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
    if args.check:
        print(json.dumps({'status': 'INPUTS_VALIDATED', 'documents': len(inference.corpus), 'run_exists': RUN_ROOT.exists()}))
        return 0
    if RUN_ROOT.exists():
        print('Run already exists; no retry.')
        return 2
    result = run_batch(RUN_ROOT, inference, gold, lambda d, timeout: previous.run_document(
        d, timeout, prompt, schema, allow_chronicle_startup_warning=True, semantic_validator=normalize_signals), bindings, baseline)
    print(json.dumps({'status': result['status'], 'attempted': result['attempted'], 'result': str(RUN_ROOT / 'result.json')}))
    return 0 if result['status'] == 'MEASURED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
