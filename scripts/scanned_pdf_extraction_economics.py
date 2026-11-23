"""Retrospective extraction economics; no new inference or customer claims."""
import json
from math import isfinite
from pathlib import Path
from statistics import median, mean

from scripts.scanned_pdf_image_input_evaluate import load_truth
from src.scanned_pdf_experiment.numeric_reread import parse_number
from src.scanned_pdf_experiment.holdout_review import sha

ROOT = Path(__file__).resolve().parents[1] / 'artifacts/scanned-pdf-experiment'
PACKETS = (ROOT/'prospective-holdout-20261122/context-new-page-v2', ROOT/'assisted-independent-intake-20261122')


def extraction_gate(primary, observations):
    n = parse_number(primary)
    return n is not None and bool(observations) and all(
        isfinite(r['confidence']) and 80 <= r['confidence'] <= 100 and parse_number(r['text']) == n
        for r in observations)


def analyze(packet):
    result = json.loads((packet/'cross-reader-v1/results.json').read_text())
    files = {'truth_sha256':packet/'adjudication-v2/truth-adjudicated.csv', 'primary_sha256':packet/'candidate-images/context-reads-v1.json', 'ocr_sha256':packet/'cross-reader-v1/ocr-reads.json'}
    for key,path in files.items():
        if sha(path) != result[key]: raise ValueError('Frozen input changed')
    m = json.loads((packet/'reviewer/manifest.json').read_text()); truth = load_truth(files['truth_sha256'],m)
    primary = json.loads(files['primary_sha256'].read_text())['reads']; ocr = {r['id']:r for r in json.loads(files['ocr_sha256'].read_text())}
    if not set(truth)==set(primary)==set(ocr): raise ValueError('Coverage mismatch')
    eligible = {k:parse_number(v) for k,v in truth.items() if parse_number(v) is not None}
    accepted = [k for k in eligible if extraction_gate(primary[k],[ocr[k]['scaled'],ocr[k]['native']])]
    return {'numeric_cells':len(eligible),'primary_errors':sum(parse_number(primary[k])!=y for k,y in eligible.items()),'accepted':len(accepted),'review':len(eligible)-len(accepted),'accepted_errors':sum(parse_number(primary[k])!=eligible[k] for k in accepted)}


def cost(price,cells,seconds_per_cell,fee=.15,overhead_minutes=15,nonlabor=1,hourly=15):
    minutes = cells*seconds_per_cell/60+overhead_minutes
    total = minutes*hourly/60+nonlabor
    return {'minutes':round(minutes,2),'net_contribution':round(price*(1-fee)-total,2),'break_even_price':round(total/(1-fee),2)}


if __name__=='__main__':
    records = {p.name:analyze(p) for p in PACKETS}
    totals = {k:sum(x[k] for x in records.values()) for k in next(iter(records.values()))}
    p = PACKETS[1]/'assisted-review-v2/assisted-review-results.json'; times = [x['ms']/1000 for x in json.loads(p.read_text())['responses'].values()]
    prices = [{'price':price,'cells':cells,'median_proxy':cost(price,cells,median(times)), 'mean_proxy':cost(price,cells,mean(times))} for price,cells in [(19,100),(19,500),(25,100),(49,250),(79,500)]]
    print(json.dumps({'status':'RETROSPECTIVE_SCENARIO_NOT_PRODUCTION_BENCHMARK','cohorts':records,'totals':totals,'review_time_proxy':{'n':len(times),'median':median(times),'mean':mean(times)},'scenarios':prices},indent=2))
