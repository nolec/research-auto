"""Preserve the first human truth and rescore captured reads after adjudication."""
import csv
import json
from pathlib import Path
import sys

from src.scanned_pdf_experiment.holdout_review import load_verified, sha
from src.scanned_pdf_experiment.numeric_reread import NumericCandidate, Reading, Decision, parse_number, confirm_numeric
from src.scanned_pdf_experiment.visual_agreement import VisualReading, confirm_visual
from src.scanned_pdf_experiment.numeric_evaluation import score_numeric
from scripts.scanned_pdf_visual_reread_development import inputs


def adjudicate(base):
    review=base/'human-review-v2'; original=review/'holdout-human-verified.csv'
    manifest=json.loads((review/'manifest.json').read_text())
    before=load_verified(original,manifest)
    # Zero-indexed numeric-column indices, excluding the semantic row key.
    fixes={('H13',1,2):('468','463'),('H15',1,0):('428,693','422,693')}
    by_id={s['id']:s for s in before}
    keyed={(sid,str(by_id[sid]['page']),str(i),by_id[sid]['columns'][j+1]):(old,new) for (sid,i,j),(old,new) in fixes.items()}
    out=base/'human-truth-adjudication-v1'; out.mkdir(exist_ok=False)
    corrected=out/'holdout-human-verified-corrected.csv'; applied=set()
    with original.open(newline='',encoding='utf-8-sig') as src, corrected.open('x',newline='',encoding='utf-8') as dst:
        reader=csv.DictReader(src); writer=csv.DictWriter(dst,fieldnames=reader.fieldnames); writer.writeheader()
        for record in reader:
            key=tuple(record[k] for k in ('id','page','row_index','column'))
            if key in keyed:
                old,new=keyed[key]
                if record['human_value'].strip()!=old:raise ValueError('Original value changed')
                record['human_value']=new; applied.add(key)
            writer.writerow(record)
    if applied!=set(keyed):raise ValueError('Missing correction target')
    after=load_verified(corrected,manifest)
    candidates,expected,_=inputs(base)
    adjusted=[]
    for c in candidates:
        sid,variant=c.crop.document.rsplit('-',1); i,j=map(int,c.crop.cell.split('/'))
        if (sid,i,j) in fixes:
            old,new=fixes[sid,i,j]
            if parse_number(c.sheet_value)!=parse_number(old):raise ValueError('Correction overlaps injected fault')
            c=NumericCandidate(c.crop,c.first_value,new)
        adjusted.append(c)
    reread=base/'visual-reread-development-v1'
    mapping=json.loads((reread/'evaluator-mapping.json').read_text())
    reads=json.loads((reread/'visual-reread.json').read_text())['reads']
    by_hash={h:VisualReading(reads[token],h) for token,h in mapping.items()}
    ocr=json.loads((base/'numeric-diagnostic-v1/source-readings.json').read_text())
    ocr_map={r['crop_sha256']:Reading(r['second']['text'],r['second']['confidence'],r['crop_sha256']) for r in ocr}
    def baseline(c):
        first,sheet=parse_number(c.first_value),parse_number(c.sheet_value)
        return Decision(c,'UNCERTAIN' if first is None else 'NO_ALERT' if first==sheet else 'DETECTED','VISUAL',None)
    scores={'vision':score_numeric(expected,map(baseline,adjusted)), 'vision_reread':score_numeric(expected,confirm_visual(adjusted,lambda c:by_hash.get(c.digest))), 'vision_tesseract':score_numeric(expected,confirm_numeric(adjusted,lambda c:ocr_map[c.digest]))}
    visual=json.loads((base/'vision-cell-development-v1.json').read_text())['rows']
    pairs=[(parse_number(v),parse_number(visual[s['id']][i][j])) for s in after for i,r in enumerate(s['rows']) for j,v in enumerate(r[1:]) if parse_number(v) is not None]
    report={'status':'RETROSPECTIVE_DEVELOPMENT_RESCORE_USER_ADJUDICATED','source_truth_sha256':sha(original),'corrected_truth_sha256':sha(corrected),'corrections':[{'id':s,'row':i,'numeric_column':j,'original':a,'corrected':b,'evidence':'user confirmed in conversation after viewing source crops'} for (s,i,j),(a,b) in fixes.items()], 'numeric_cells':len(pairs),'exact':sum(a==b for a,b in pairs),'faults':len(expected),'scores':scores,'business':'HOLD','independent_holdout':False}
    (out/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':adjudicate(Path(sys.argv[1]).resolve())
