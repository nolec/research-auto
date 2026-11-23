"""Evaluate the separate image-input stratum against manifest-bound human truth.

The candidate reader writes a token-to-string JSON object without evaluator
access. This script never runs recognition and refuses incomplete truth/reads.
"""
import csv
import json
from pathlib import Path
import sys

from src.scanned_pdf_experiment.holdout_review import sha,manifest_digest
from src.scanned_pdf_experiment.numeric_reread import parse_number


def load_truth(path,manifest):
    if manifest['manifest_sha256']!=manifest_digest(manifest):raise ValueError('Manifest integrity mismatch')
    expected={c['id'] for s in manifest['scopes'] for c in s['cells']}; result={}
    with path.open(newline='',encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            k=r['id'];v=r['human_value'].strip()
            if k not in expected or k in result or r['manifest_sha256']!=manifest['manifest_sha256'] or r['human_status']!='VERIFIED' or not v or v=='UNREADABLE':raise ValueError('Invalid verified truth')
            result[k]=v
    if result.keys()!=expected:raise ValueError('Incomplete truth')
    return result


def evaluate(packet,truth_path,read_path):
    manifest=json.loads((packet/'reviewer/manifest.json').read_text());truth=load_truth(truth_path,manifest);reads=json.loads(read_path.read_text())['reads']
    if set(reads)!=set(truth) or any(not isinstance(v,str) for v in reads.values()):raise ValueError('Incomplete/invalid candidate readings')
    for s in manifest['scopes']:
        if manifest.get('stratum')=='CONTEXT_PAGE_HOLDOUT_SHARED_SOURCE_PDFS':
            if sha(packet/'candidate-images'/s['context_image'])!=s['context_sha256']:raise ValueError('Candidate context image changed')
        else:
            for c in s['cells']:
                if sha(packet/'candidate-images'/f"{c['id']}.png")!=c['crop_sha256']:raise ValueError('Candidate image changed')
    eligible={k:parse_number(v) for k,v in truth.items() if parse_number(v) is not None}; exact=sum(parse_number(reads[k])==v for k,v in eligible.items())
    fault={}
    for s in manifest['scopes']:
        cells={(c['row'],c['column']):c['id'] for c in s['cells']}
        for i,j in [(0,0),(3,1),(6,2)]:
            key=next((cells[i,(j+k)%3] for k in range(3) if cells[i,(j+k)%3] in eligible),None)
            if key is None:raise ValueError('Frozen fault schedule cannot be constructed')
            fault[key]=eligible[key]+1000
    tp=fp=fn=uncertain=0; errors=[]
    for variant in ('clean','corrupt'):
        for k,v in eligible.items():
            actual=variant=='corrupt' and k in fault;sheet=fault[k] if actual else v;read=parse_number(reads[k]);detected=read is not None and read!=sheet
            if read is None:uncertain+=1
            if actual:tp+=int(detected);fn+=int(not detected)
            elif detected:fp+=1
            if detected!=actual or read is None:errors.append({'id':k,'variant':variant,'detected':detected,'actual_error':actual,'uncertain':read is None})
    precision=tp/(tp+fp) if tp+fp else None;recall=tp/(tp+fn) if tp+fn else None
    return {'status':'IMAGE_INPUT_NUMERIC_ONLY','documents':len(manifest['scopes']),'numeric_eligible':len(eligible),'exact':exact,'excluded_nonnumeric':len(truth)-len(eligible),'faults':len(fault),'tp':tp,'fp':fp,'fn':fn,'uncertain':uncertain,'precision':precision,'recall':recall,'thresholds_met':precision is not None and precision>=.95 and recall is not None and recall>=.90,'truth_sha256':sha(truth_path),'reads_sha256':sha(read_path),'manifest_sha256':manifest['manifest_sha256'],'reader_provenance':json.loads(read_path.read_text()).get('provenance','UNSPECIFIED'),'errors':errors,'business':'HOLD'}


if __name__=='__main__':
    packet,truth,reads=map(Path,sys.argv[1:]);result=evaluate(packet,truth,reads)
    with (packet/'results.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='errors'},indent=2))
