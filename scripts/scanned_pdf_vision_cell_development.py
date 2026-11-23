"""Score previously captured manual visual reads; development only, not blind."""
import json
from pathlib import Path

from src.scanned_pdf_experiment.holdout_review import load_verified, sha
from src.scanned_pdf_experiment.numeric_reread import parse_number, SourceCrop, NumericCandidate, Reading, Decision, confirm_numeric
from src.scanned_pdf_experiment.numeric_evaluation import score_numeric


def evaluate(base):
    review=base/'human-review-v2'; run=base/'numeric-diagnostic-v1'
    vision=base/'vision-cell-development-v1.json'
    truth=load_verified(review/'holdout-human-verified.csv',json.loads((review/'manifest.json').read_text()))
    visual=json.loads(vision.read_text())['rows']
    records={(r['id'],r['row'],r['column']):r for r in json.loads((run/'source-readings.json').read_text())}
    results={'vision':[], 'vision_tesseract_agreement':[]}; expected_all=[]; errors=[]; count=0
    for s in truth:
        sid=s['id']; values={(i,j):v for i,row in enumerate(s['rows']) for j,v in enumerate(row[1:]) if parse_number(v) is not None}
        if len(visual[sid])!=len(s['rows']) or any(len(row)!=3 for row in visual[sid]):raise ValueError('Visual shape mismatch')
        count+=len(values)
        for (i,j),truth_value in values.items():
            read=visual[sid][i][j]
            if parse_number(read)!=parse_number(truth_value):errors.append({'id':sid,'row':i,'column':j,'read':read,'truth':truth_value})
        faults={}
        for i,j in ((0,0),(3,1),(6,2)):
            key=next(( (i,(j+k)%3) for k in range(3) if (i,(j+k)%3) in values),None)
            if key is None:raise ValueError('Fault schedule infeasible')
            faults[key]=str(parse_number(values[key])+1000)
        for variant in ('clean','corrupt'):
            candidates=[]; second={}
            for (i,j),true_value in values.items():
                record=records[sid,i,j]; path=Path(record['path'])
                if sha(path)!=record['crop_sha256']:raise ValueError('Crop changed')
                crop=SourceCrop(sid+'-'+variant,s['page'],f'{i}/{j}',tuple(record['crop_bbox']),path.read_bytes())
                target=faults.get((i,j),true_value) if variant=='corrupt' else true_value
                first=visual[sid][i][j]; candidate=NumericCandidate(crop,first,target); candidates.append(candidate)
                st='UNCERTAIN' if parse_number(first) is None else 'DETECTED' if parse_number(first)!=parse_number(target) else 'NO_ALERT'
                results['vision'].append(Decision(candidate,st,'VISUAL',None))
                reread=record['second']; second[crop]=Reading(reread['text'],reread['confidence'],crop.digest)
                if variant=='corrupt' and (i,j) in faults:expected_all.append((crop.document,crop.page,crop.cell))
            results['vision_tesseract_agreement'].extend(confirm_numeric(candidates,second.__getitem__))
    report={'status':'DEVELOPMENT_ONLY_PRIOR_EXPOSURE_NOT_BLIND','numeric_cells':count,'exact':count-len(errors),'errors':errors,'faults':len(expected_all),'scores':{key:score_numeric(expected_all,decisions) for key,decisions in results.items()},'visual_sha256':sha(vision),'truth_sha256':sha(review/'holdout-human-verified.csv'),'ocr_sha256':sha(run/'source-readings.json'),'business':'HOLD'}
    with (base/'vision-cell-development-v1-results.json').open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    import sys
    evaluate(Path(sys.argv[1]).resolve())
