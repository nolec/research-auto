"""Development diagnostic with separate excerpt and structured evidence references."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from jsonschema import Draft202012Validator
from src.extraction import economic_signals_v6 as v6
from src.extraction import codex_cli_development_v2 as previous
from src.extraction import codex_cli_diagnostic as cli
from src.extraction.codex_cli_metric import _save_progress

DIMENSIONS = v6.DIMENSIONS
RUN = v6.RUN.parent / 'codex-cli-gpt-6.2-sol-economic-v7'
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['document_id', *DIMENSIONS],
          'properties': {'document_id': {'type': 'string'}, **{s: {'type': 'object',
              'additionalProperties': False, 'required': ['state', 'quote', 'reference'], 'properties': {
                  'state': {'type': 'string', 'enum': ['yes', 'no', 'unknown']},
                  'quote': {'type': ['string', 'null']},
                  'reference': {'type': ['string', 'null'], 'enum': ['ted_award', None]}}} for s in DIMENSIONS}}}
PROMPT = '''Classify six independent economic signals using only the excerpt and allowed structured references. Title is context only.
procurement_intent: explicit buyer solicitation, purchase request, or stated purchase scope. In a result notice, purchase scope is historical, not a new or active solicitation. Generic project goals are not purchase scope.
budget_or_willingness_to_pay: explicit budget, amount to be paid or willingness to pay; voucher face values are not procurement budgets.
contract_awarded: explicit award or executed contract. If the supplied structured reference ted_award is available, use that reference for the award rather than quoting metadata as text.
actual_payment: explicit completed payment or paid expenditure; an award, planned amount, price or purchase badge is not payment.
economic_loss: concrete stated economic loss or consequence, not speculation.
labor_burden: meaningful time burden of work or necessary tasks, not leisure, generic inconvenience or relative slowdown alone.
For yes use exactly one of: quote=exact nonempty substring of the excerpt and reference=null; or quote=null and reference="ted_award" (contract_awarded only, when supplied). For unknown or no both must be null. Use unknown for missing evidence and no for clearly inapplicable evidence. Never infer one signal from another. Return only schema with unchanged document_id.'''


def project(record):
    d = {k: record[k] for k in ('document_id', 'source', 'title', 'published_at', 'excerpt')}
    form = record.get('form_type') if d['source'] == 'ted' else None
    fields = record.get('evidence_fields', {}) if d['source'] == 'ted' else {}
    d['form_type'] = form
    d['references'] = {}
    if form == 'result' and 'selec-w' in fields.get('winner_selection_status', []) and fields.get('contract_conclusion_date'):
        d['references']['ted_award'] = {'winner_selection_status': ['selec-w'],
                                        'contract_conclusion_date': list(fields['contract_conclusion_date'])}
    d['text'] = 'Excerpt:\n' + d['excerpt'] + '\nObserved form_type=' + str(form)
    d['text'] += '\nAllowed structured references: ' + json.dumps(d['references'], ensure_ascii=False)
    return d


def normalize(document, output):
    Draft202012Validator(SCHEMA).validate(output)
    if output['document_id'] != document['document_id']:
        raise ValueError('document identity mismatch')
    result = {'document_id': document['document_id']}
    for s in DIMENSIONS:
        item = output[s]
        state, quote, ref = item['state'], item['quote'], item['reference']
        reason = None
        if state != 'yes':
            if quote is not None or ref is not None:
                reason = 'NONPOSITIVE_HAS_EVIDENCE'
        elif (quote is None) == (ref is None):
            reason = 'EXACTLY_ONE_EVIDENCE_REQUIRED'
        elif ref is not None:
            if s != 'contract_awarded':
                reason = 'REFERENCE_NOT_ALLOWED_FOR_DIMENSION'
            elif ref not in document['references']:
                reason = 'REFERENCE_NOT_AVAILABLE'
        elif not quote.strip() or quote not in document['excerpt']:
            reason = 'QUOTE_NOT_IN_EXCERPT'
        if reason:
            result[s] = {'state': 'invalid', 'reason': reason, 'submitted': {
                'state': state, 'quote': quote[:500] if quote is not None else None, 'reference': ref}}
            continue
        value = {'state': state, 'quote': quote, 'reference': ref}
        if ref is not None:
            value['evidence'] = document['references'][ref]
        if s == 'procurement_intent' and state == 'yes':
            value['temporal_scope'] = ('historical_result_notice' if document['form_type'] == 'result'
                                       else 'current_status_unverified')
        result[s] = value
    return result


def load_snapshot():
    data = (v6.BASE / 'snapshot.json').read_bytes()
    if sha256(data).hexdigest() != v6.SNAPSHOT_HASH:
        raise ValueError('snapshot changed')
    records = json.loads(data)['records']
    if len(records) != 34 or len({r['document_id'] for r in records}) != 34:
        raise ValueError('snapshot membership mismatch')
    return [project(r) for r in records]


def run_batch(root, documents, call, bindings):
    root.mkdir(mode=0o700, exist_ok=False)
    cli._private_create(root / 'claim.json', {'bindings': bindings, 'model': previous.MODEL,
        'scope': 'exploratory_inference_only', 'max_processes': len(documents), 'retries': 0})
    rows, outputs = [], []
    started = time.monotonic()
    reason = None
    for i, d in enumerate(documents, 1):
        remaining = 1800 - (time.monotonic() - started)
        if remaining <= 0:
            reason = 'RUN_DEADLINE'
            break
        row = {'ordinal': i, 'state': 'attempt_started'}
        rows.append(row)
        _save_progress(root, {'rows': rows})
        try:
            raw, usage = call(d, min(120, remaining))
            o = normalize(d, raw)
            outputs.append(o)
            row.update(state='invalid' if any(o[s]['state'] == 'invalid' for s in DIMENSIONS) else 'measured', output=o)
        except cli.CliContractError as e:
            if str(e) in ('CLI_OUTPUT_SCHEMA_INVALID', 'CLI_DOCUMENT_ID_MISMATCH'):
                o = {'document_id': d['document_id'], **{s: {'state': 'invalid', 'reason': str(e)} for s in DIMENSIONS}}
                outputs.append(o)
                row.update(state='invalid', output=o, validation=e.diagnostics.get('validation'))
            else:
                reason = str(e)
                row.update(state='failed', error=reason)
        except Exception:
            reason = 'VALIDATION_OR_OPERATIONAL_FAILURE'
            row.update(state='failed', error=reason)
        _save_progress(root, {'rows': rows})
        print(f'{i}/{len(documents)} {row["state"]}', flush=True)
        if reason:
            break
    result = {'status': 'INCOMPLETE' if reason else 'MEASURED', 'attempted': len(rows),
              'reason': reason, 'bindings': bindings, 'outputs': outputs, 'quality_gate_status': 'NOT_EVALUATED'}
    cli._private_create(root / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    for option in ('check', 'execute', 'compare'):
        action.add_argument('--' + option, action='store_true')
    args = parser.parse_args()
    documents = load_snapshot()
    schema, prompt = json.dumps(SCHEMA, sort_keys=True).encode(), PROMPT.encode()
    Draft202012Validator.check_schema(SCHEMA)
    bindings = {'snapshot_sha256': v6.SNAPSHOT_HASH, 'prompt_sha256': sha256(prompt).hexdigest(),
                'schema_sha256': sha256(schema).hexdigest(), 'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
                'cli_runner_sha256': sha256(Path(previous.__file__).read_bytes()).hexdigest(),
                'comparison_sha256': sha256(Path(v6.__file__).read_bytes()).hexdigest()}
    if args.check:
        print(json.dumps({'status': 'INPUTS_VALIDATED', 'documents': len(documents), 'run_exists': RUN.exists(),
                          'structured_award_references': sum('ted_award' in d['references'] for d in documents)}))
        return 0
    if args.compare:
        result = json.loads((RUN / 'result.json').read_bytes())
        if result['status'] != 'MEASURED' or result['bindings'] != bindings or [o['document_id'] for o in result['outputs']] != [d['document_id'] for d in documents]:
            raise ValueError('inference result not complete or mismatched')
        proposal = (v6.BASE / 'ai-proposal-v1.json').read_bytes()
        assisted = json.loads((v6.BASE / 'assisted-review-v1.json').read_bytes())
        if assisted['snapshot_sha256'] != v6.SNAPSHOT_HASH or assisted['proposal_sha256'] != sha256(proposal).hexdigest():
            raise ValueError('assisted proposal mismatch')
        report = v6.compare(result['outputs'], json.loads(proposal)['records'])
        cli._private_create(RUN / 'agreement.json', report)
        print(json.dumps({'status': 'AGREEMENT_ONLY', 'differences': len(report['differences']), 'result': str(RUN / 'agreement.json')}))
        return 0
    result = run_batch(RUN, documents, lambda d, timeout: previous.run_document(d, timeout, prompt, schema,
        allow_chronicle_startup_warning=True, semantic_validator=normalize), bindings)
    print(json.dumps({'status': result['status'], 'attempted': result['attempted'], 'result': str(RUN / 'result.json')}))
    return 0 if result['status'] == 'MEASURED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
