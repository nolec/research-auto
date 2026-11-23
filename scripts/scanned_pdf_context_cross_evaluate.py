"""Retrospective cross-reader score. The reader never receives sheet or truth."""
import json
from math import isfinite
from pathlib import Path

from scripts.scanned_pdf_context_page_holdout import BASE
from scripts.scanned_pdf_image_input_evaluate import load_truth
from src.scanned_pdf_experiment.holdout_review import sha
from src.scanned_pdf_experiment.numeric_reread import parse_number


def decide(primary,sheet,observations):
    first,target=parse_number(primary),parse_number(sheet)
    if first is None or target is None:return 'UNCERTAIN'
    if first==target:return 'NO_ALERT'
    if not observations:return 'UNCERTAIN'
    for read in observations:
        conf=read['confidence']
        if not isinstance(conf,(int,float)) or not isfinite(conf) or not 80<=conf<=100 or parse_number(read['text'])!=first:return 'UNCERTAIN'
    return 'DETECTED'


def score(manifest,truth,primary,ocr,variants):
    eligible={k:parse_number(v) for k,v in truth.items() if parse_number(v) is not None};fault={}
    for scope in manifest['scopes']:
        cells={(c['row'],c['column']):c['id'] for c in scope['cells']}
        for i,j in [(0,0),(3,1),(6,2)]:
            key=next((cells[i,(j+k)%3] for k in range(3) if cells[i,(j+k)%3] in eligible),None)
            if key is None:raise ValueError('Frozen fault schedule infeasible')
            fault[key]=eligible[key]+1000
    tp=fp=fn=uncertain=uncertain_actual=0;details=[]
    for variant in ('clean','corrupt'):
        for k,v in eligible.items():
            actual=variant=='corrupt' and k in fault;target=fault[k] if actual else v
            status=decide(primary[k],str(target),[ocr[k][name] for name in variants]);detected=status=='DETECTED'
            tp+=int(actual and detected);fp+=int(not actual and detected);fn+=int(actual and not detected);uncertain+=int(status=='UNCERTAIN');uncertain_actual+=int(actual and status=='UNCERTAIN')
            if status!='NO_ALERT' or actual:details.append({'id':k,'variant':variant,'actual_error':actual,'status':status})
    return {'tp':tp,'fp':fp,'fn':fn,'uncertain':uncertain,'uncertain_actual_errors':uncertain_actual,'review_queue':uncertain+tp+fp,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,'details':details}


def main():
    packet=BASE/'context-new-page-v2';out=packet/'cross-reader-v1';m=json.loads((packet/'reviewer/manifest.json').read_text());truthpath=packet/'adjudication-v2/truth-adjudicated.csv';truth=load_truth(truthpath,m);primarypath=packet/'candidate-images/context-reads-v1.json';primary=json.loads(primarypath.read_text())['reads'];ocrpath=out/'ocr-reads.json';rows=json.loads(ocrpath.read_text());ocr={r['id']:r for r in rows}
    if len(rows)!=len(ocr) or set(ocr)!=set(truth) or set(primary)!=set(truth):raise ValueError('Input coverage mismatch')
    for s in m['scopes']:
        if sha(packet/'candidate-images'/s['context_image'])!=s['context_sha256']:raise ValueError('Context changed')
        for c in s['cells']:
            r=ocr[c['id']]
            if r['context_sha256']!=s['context_sha256'] or (r['scope'],r['row'],r['column'])!=(s['id'],c['row'],c['column']):raise ValueError('OCR binding mismatch')
            for name in ('scaled','native'):
                if sha(out/s['id']/f"{c['id']}-{name}.png")!=r[f'{name}_sha256']:raise ValueError('OCR crop changed')
    scores={name:score(m,truth,primary,ocr,variants) for name,variants in [('strict_two_ocr_views',('scaled','native')),('scaled_only_diagnostic',('scaled',)),('native_only_diagnostic',('native',))]}
    eligible={k:parse_number(v) for k,v in truth.items() if parse_number(v) is not None};read_quality={}
    for name in ('scaled','native'):
        valid=[k for k in eligible if parse_number(ocr[k][name]['text']) is not None and 80<=ocr[k][name]['confidence']<=100]
        read_quality[name]={'exact':sum(parse_number(ocr[k][name]['text'])==v for k,v in eligible.items()),'eligible':len(eligible),'accepted':len(valid),'accepted_exact':sum(parse_number(ocr[k][name]['text'])==eligible[k] for k in valid)}
    result={'status':'RETROSPECTIVE_CONTEXT_CROSS_READER_DEVELOPMENT','truth_sha256':sha(truthpath),'primary_sha256':sha(primarypath),'ocr_sha256':sha(ocrpath),'freeze_sha256':sha(out/'freeze.json'),'scores':scores,'ocr_quality':read_quality,'business':'HOLD'}
    with (out/'results.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({'scores':{k:{a:b for a,b in v.items() if a!='details'} for k,v in scores.items()},'ocr_quality':read_quality},indent=2))


if __name__=='__main__':main()
