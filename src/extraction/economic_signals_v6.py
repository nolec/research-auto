"""Six-dimension exploratory extraction; assisted agreement is not accuracy."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from jsonschema import Draft202012Validator
from src.extraction import codex_cli_development_v2 as previous
from src.extraction import codex_cli_diagnostic as cli
from src.extraction.codex_cli_metric import _save_progress

BASE = previous.RUN_ROOT.parent / 'fresh-economic-review-v2-20261123'
RUN = previous.RUN_ROOT.parent / 'codex-cli-gpt-6.2-sol-economic-v6'
SNAPSHOT_HASH = '187054a1cf263fb5557c99ba49100d99ec4ddc676ac5f9d3d43b25f5285a1449'
DIMENSIONS = ('procurement_intent', 'budget_or_willingness_to_pay', 'contract_awarded',
              'actual_payment', 'economic_loss', 'labor_burden')
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['document_id', *DIMENSIONS],
          'properties': {'document_id': {'type': 'string'}, **{s: {'type': 'object',
              'additionalProperties': False, 'required': ['state', 'quote'], 'properties': {
                  'state': {'type': 'string', 'enum': ['yes', 'no', 'unknown']},
                  'quote': {'type': ['string', 'null']}}} for s in DIMENSIONS}}}
PROMPT = '''Classify six independent economic evidence dimensions. Use only the supplied excerpt and explicitly permitted structured observations, not the title or outside knowledge.
procurement_intent: explicit buyer solicitation, purchase request, order scope or purchasing mechanism; not generic project descriptions.
budget_or_willingness_to_pay: explicit budget, amount to be paid, or willingness to pay; face values of vouchers are not procurement budgets.
contract_awarded: explicitly reported award or executed contract; not invitation or candidate selection alone. TED winner_selection_status=selec-w together with contract conclusion date supports an award.
actual_payment: explicit completed payment or paid expenditure, not award, budget, displayed prices or purchase metadata.
economic_loss: concrete stated economic consequence or loss, not speculative impact.
labor_burden: meaningful work or necessary-task time burden stated; not leisure, generic inconvenience, or relative performance slowdown without evidence of meaningful work burden.
Classify independently. yes requires an exact nonempty substring of the excerpt, or for contract_awarded the permitted TED winner status with a recorded contract date. For no or unknown quote must be null. Use unknown for missing evidence, no for clearly inapplicable evidence. Do not equate economic signals with actionable online business opportunities. Preserve document_id. Return only the supplied schema.'''


def project(record):
    d = {k: record[k] for k in ('document_id', 'source', 'title', 'published_at')}
    d['excerpt'] = record['excerpt']
    fields = record.get('evidence_fields', {}) if d['source'] == 'ted' else {}
    d['award_supported'] = ('selec-w' in fields.get('winner_selection_status', [])
                            and bool(fields.get('contract_conclusion_date')))
    d['text'] = 'Excerpt:\n' + d['excerpt']
    if d['source'] == 'ted':
        d['text'] += '\nObserved form_type=' + record.get('form_type', 'unknown')
        if d['award_supported']:
            d['text'] += '\nObserved winner_selection_status=selec-w\ncontract_conclusion_date=' + ','.join(fields['contract_conclusion_date'])
    return d


def normalize(document, output):
    Draft202012Validator(SCHEMA).validate(output)
    if output['document_id'] != document['document_id']:
        raise ValueError('document identity mismatch')
    result = {'document_id': document['document_id']}
    for s in DIMENSIONS:
        state, quote = output[s]['state'], output[s]['quote']
        valid_quote = isinstance(quote, str) and bool(quote.strip()) and (
            quote in document['excerpt'] or (s == 'contract_awarded' and document['award_supported']
                                             and quote == 'winner_selection_status=selec-w'))
        if (state == 'yes' and not valid_quote) or (state != 'yes' and quote is not None):
            result[s] = {'state': 'invalid', 'reason': 'EVIDENCE_INVALID'}
        else:
            result[s] = {'state': state, 'quote': quote}
    return result


def compare(outputs, proposals):
    if len(outputs) != len(proposals) or [p['row'] for p in proposals] != list(range(1, len(outputs)+1)):
        raise ValueError('comparison membership mismatch')
    differences = []
    counts = {s: Counter() for s in DIMENSIONS}
    for o, p in zip(outputs, proposals):
        for s in DIMENSIONS:
            proposed = 'yes' if s in p.get('yes', {}) else 'no' if s in p.get('no', {}) else 'unknown'
            predicted = o[s]['state']
            counts[s][predicted] += 1
            if proposed != predicted:
                differences.append({'row': p['row'], 'dimension': s, 'proposal': proposed, 'prediction': predicted})
    return {'scope': 'assisted_agreement_only', 'dimensions': {s: dict(c) for s, c in counts.items()},
            'differences': differences}


def load_snapshot():
    data = (BASE / 'snapshot.json').read_bytes()
    if sha256(data).hexdigest() != SNAPSHOT_HASH:
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
                o = {'document_id': d['document_id'], **{s: {'state': 'invalid'} for s in DIMENSIONS}}
                outputs.append(o)
                row.update(state='invalid', output=o)
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
    p = argparse.ArgumentParser(description=__doc__)
    action = p.add_mutually_exclusive_group(required=True)
    for option in ('check', 'execute', 'compare'):
        action.add_argument('--' + option, action='store_true')
    args = p.parse_args()
    documents = load_snapshot()
    schema, prompt = json.dumps(SCHEMA, sort_keys=True).encode(), PROMPT.encode()
    Draft202012Validator.check_schema(SCHEMA)
    bindings = {'snapshot_sha256': SNAPSHOT_HASH, 'prompt_sha256': sha256(prompt).hexdigest(),
                'schema_sha256': sha256(schema).hexdigest(), 'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
                'cli_runner_sha256': sha256(Path(previous.__file__).read_bytes()).hexdigest()}
    if args.check:
        print(json.dumps({'status': 'INPUTS_VALIDATED', 'documents': len(documents), 'run_exists': RUN.exists()}))
        return 0
    if args.compare:
        result = json.loads((RUN / 'result.json').read_bytes())
        if result['status'] != 'MEASURED' or result['bindings'] != bindings or [o['document_id'] for o in result['outputs']] != [d['document_id'] for d in documents]:
            raise ValueError('inference result not complete or mismatched')
        proposal = (BASE / 'ai-proposal-v1.json').read_bytes()
        assisted = json.loads((BASE / 'assisted-review-v1.json').read_bytes())
        if assisted['snapshot_sha256'] != SNAPSHOT_HASH or assisted['proposal_sha256'] != sha256(proposal).hexdigest():
            raise ValueError('assisted proposal mismatch')
        report = compare(result['outputs'], json.loads(proposal)['records'])
        cli._private_create(RUN / 'agreement.json', report)
        print(json.dumps({'status': 'AGREEMENT_ONLY', 'differences': len(report['differences']), 'result': str(RUN / 'agreement.json')}))
        return 0
    result = run_batch(RUN, documents, lambda d, timeout: previous.run_document(d, timeout, prompt, schema,
        allow_chronicle_startup_warning=True, semantic_validator=normalize), bindings)
    print(json.dumps({'status': result['status'], 'attempted': result['attempted'], 'result': str(RUN / 'result.json')}))
    return 0 if result['status'] == 'MEASURED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
