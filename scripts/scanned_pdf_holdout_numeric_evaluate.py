"""Evaluator-side numeric-only diagnostic; consumes frozen reads, not vice versa."""
import json
from pathlib import Path
import sys

from src.scanned_pdf_experiment.holdout_review import load_verified, sha
from src.scanned_pdf_experiment.numeric_reread import SourceCrop, NumericCandidate, Reading, Decision, confirm_numeric, parse_number
from src.scanned_pdf_experiment.numeric_evaluation import score_numeric


def evaluate(review, run):
    manifest = json.loads((review/'manifest.json').read_text())
    truth = load_verified(review/'holdout-human-verified.csv',manifest)
    reads = json.loads((run/'source-readings.json').read_text())
    lookup = {(r['id'],r['row'],r['column']):r for r in reads}
    if len(lookup) != len(reads) or set(lookup) != {(s['id'],i,j) for s in truth for i in range(len(s['rows'])) for j in range(3)}:
        raise ValueError('Source coverage mismatch')
    totals = {'baseline': [], 'agreement': []}; expected_all = []; details=[]
    for s in truth:
        values = {(i,j):v for i,row in enumerate(s['rows']) for j,v in enumerate(row[1:]) if parse_number(v) is not None}
        faults = {}
        for i,j in ((0,0),(3,1),(6,2)):
            key = next(( (i,(j+k)%3) for k in range(3) if (i,(j+k)%3) in values),None)
            if key is None: raise ValueError('Fault schedule not feasible')
            faults[key] = str(parse_number(values[key])+1000)
        for variant in ('clean','corrupt'):
            expected = []; candidates=[]; rereads={}; baseline=[]
            for (i,j),v in values.items():
                record=lookup[s['id'],i,j]; path=Path(record['path']); png=path.read_bytes()
                if sha(path)!=record['crop_sha256']: raise ValueError('Crop integrity mismatch')
                crop=SourceCrop(s['id']+'-'+variant,s['page'],f'{i}/{j}',tuple(record['crop_bbox']),png)
                sheet=faults.get((i,j),v) if variant=='corrupt' else v
                first=record['first']; raw=first['text'] if first['confidence']>=80 else ''
                candidate=NumericCandidate(crop,raw,sheet); candidates.append(candidate)
                second=record['second']; rereads[crop]=Reading(second['text'],second['confidence'],crop.digest)
                status='UNCERTAIN' if parse_number(raw) is None else 'NO_ALERT' if parse_number(raw)==parse_number(sheet) else 'DETECTED'
                baseline.append(Decision(candidate,status,'BASELINE',None))
                if variant=='corrupt' and (i,j) in faults: expected.append((crop.document,crop.page,crop.cell))
            agreement=confirm_numeric(candidates,rereads.__getitem__)
            for name,decisions in [('baseline',baseline),('agreement',agreement)]: totals[name].extend(decisions)
            expected_all.extend(expected)
            details.append({'id':s['id'],'variant':variant,'eligible_cells':len(values),'baseline':score_numeric(expected,baseline),'agreement':score_numeric(expected,agreement)})
    scores={name:score_numeric(expected_all,decisions) for name,decisions in totals.items()}
    result={'status':'EXPLORATORY_NUMERIC_ONLY_SAME_ENGINE_NOT_OFFICIAL','truth_sha256':sha(review/'holdout-human-verified.csv'),'freeze_sha256':sha(run/'freeze.json'),'readings_sha256':sha(run/'source-readings.json'),'documents':len(truth),'faults':len(expected_all),'scores':scores,'details':details,'business':'HOLD'}
    with (run/'results.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='details'},indent=2))


if __name__=='__main__':
    evaluate(*(Path(a).resolve() for a in sys.argv[1:]))
