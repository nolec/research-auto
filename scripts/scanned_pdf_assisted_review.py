"""Build and score a retrospective, truth-hidden assisted-review exercise."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from scripts.scanned_pdf_context_page_holdout import BASE
from scripts.scanned_pdf_context_cross_evaluate import decide
from scripts.scanned_pdf_image_input_evaluate import load_truth
from scripts.scanned_pdf_image_input_review import image_url
from src.scanned_pdf_experiment.holdout_review import sha
from src.scanned_pdf_experiment.numeric_reread import parse_number
from PIL import Image


def build(packet, out, *, version=2):
    cross = packet / 'cross-reader-v1'
    manifest = json.loads((packet / 'reviewer/manifest.json').read_text())
    truth_path = packet / 'adjudication-v2/truth-adjudicated.csv'
    primary_path = packet / 'candidate-images/context-reads-v1.json'
    result = json.loads((cross / 'results.json').read_text())
    for path, key in [(truth_path, 'truth_sha256'), (primary_path, 'primary_sha256'), (cross / 'ocr-reads.json', 'ocr_sha256')]:
        if sha(path) != result[key]:
            raise ValueError('Frozen input changed')
    truth = load_truth(truth_path, manifest)
    primary = json.loads(primary_path.read_text())['reads']
    ocr = {r['id']: r for r in json.loads((cross / 'ocr-reads.json').read_text())}
    eligible = {k: parse_number(v) for k, v in truth.items() if parse_number(v) is not None}
    cells = {}; faults = {}; images = {}; items = []; answers = {}
    for s in manifest['scopes']:
        path = packet / 'candidate-images' / s['context_image']
        if sha(path) != s['context_sha256']:
            raise ValueError('Changed source image')
        images[s['id']] = image_url(Image.open(path))
        positions = {(c['row'], c['column']): c['id'] for c in s['cells']}
        for i, j in [(0, 0), (3, 1), (6, 2)]:
            k = next(positions[i, (j+d)%3] for d in range(3) if positions[i, (j+d)%3] in eligible)
            faults[k] = eligible[k]+1000
        cells.update({c['id']: (s, c) for c in s['cells']})
    for variant in ('clean', 'corrupt'):
        for k, value in eligible.items():
            actual = variant == 'corrupt' and k in faults
            sheet = faults[k] if actual else value
            r = ocr[k]; status = decide(primary[k], str(sheet), [r['scaled'], r['native']])
            if status == 'NO_ALERT':
                continue
            s, c = cells[k]
            token = hashlib.sha256(f'assisted-v1/{variant}/{k}'.encode()).hexdigest()[:20]
            items.append(dict(id=token, scope=s['id'], title=s['scope'], page=s['page'], row=c['row']+1, column=c['column']+1, header=s['headers'][c['column']], sheet=str(sheet), box=r['box']))
            answers[token] = {'actual_error': actual, 'source_value': str(value), **({'sheet_value':str(sheet)} if version>=2 else {})}
    expected = {(r['id'],r['variant']) for r in result['scores']['strict_two_ocr_views']['details'] if r['status'] != 'NO_ALERT'}
    actual_ids = {hashlib.sha256(f'assisted-v1/{v}/{k}'.encode()).hexdigest()[:20] for k,v in expected}
    if actual_ids != set(answers):
        raise ValueError('Queue mismatch')
    random.Random(20261122).shuffle(items)
    payload = {'items': items, 'images': images, 'ui_version':version}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    payload['packet'] = digest
    out.mkdir(exist_ok=False)
    template = Path(__file__).with_suffix('.html').read_text()
    (out / 'review.html').write_text(template.replace('__PAYLOAD__', json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')))
    (out / 'answer-key.json').write_text(json.dumps({'packet':digest,'answers':answers,'total_faults':len(faults),'total_positions':2*len(eligible)},indent=2))
    print(f'Prepared {len(items)} review items')


def evaluate(key, submission):
    if submission['packet'] != key['packet']:
        raise ValueError('Wrong review packet')
    rows = submission['responses']; expected = key['answers']
    if set(rows) != set(expected):
        raise ValueError('Incomplete review')
    tp = fp = unresolved = correct_values = 0; seconds = 0
    for token, answer in expected.items():
        r = rows[token]; d = r['decision']; elapsed = r['ms']
        if d not in ('match','error','unknown') or type(elapsed) is not int or elapsed < 0:
            raise ValueError('Invalid response')
        if d == 'error' and 'sheet_value' in answer:
            value = parse_number(r['value'])
            if value is None or value == parse_number(answer['sheet_value']):
                raise ValueError('Correction must be a valid number different from the sheet value')
        seconds += elapsed/1000
        unresolved += d == 'unknown'
        tp += d == 'error' and answer['actual_error']
        fp += d == 'error' and not answer['actual_error']
        correct_values += d == 'error' and answer['actual_error'] and parse_number(r['value']) == parse_number(answer['source_value'])
    return {'status':'RETROSPECTIVE_ASSISTED_REVIEW','tp':tp,'fp':fp,'fn':key['total_faults']-tp,'unresolved':unresolved,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/key['total_faults'],'corrected_fault_values':correct_values,'active_seconds':seconds,'reviewed':len(rows),'total_positions':key['total_positions'],'business':'HOLD'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--submission',type=Path); parser.add_argument('--version',type=int,choices=(1,2),default=2)
    args = parser.parse_args(); packet = BASE/'context-new-page-v2'; out = packet/f'assisted-review-v{args.version}'
    if args.submission:
        result = evaluate(json.loads((out/'answer-key.json').read_text()),json.loads(args.submission.read_text()))
        print(json.dumps(result,indent=2))
    else:
        if args.version != 2: parser.error('Version 1 is archived; build version 2')
        build(packet,out,version=args.version)
