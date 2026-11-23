"""Two-phase, retrospective visual reread experiment. Never claim blindness."""
import json
from pathlib import Path
import random
import sys

from PIL import Image, ImageDraw, ImageOps

from src.scanned_pdf_experiment.holdout_review import load_verified, sha
from src.scanned_pdf_experiment.numeric_reread import parse_number, SourceCrop, NumericCandidate
from src.scanned_pdf_experiment.visual_agreement import VisualReading, confirm_visual
from src.scanned_pdf_experiment.numeric_evaluation import score_numeric


def inputs(base):
    review=base/'human-review-v2'; run=base/'numeric-diagnostic-v1'
    truth=load_verified(review/'holdout-human-verified.csv',json.loads((review/'manifest.json').read_text()))
    visual=json.loads((base/'vision-cell-development-v1.json').read_text())['rows']
    records={(r['id'],r['row'],r['column']):r for r in json.loads((run/'source-readings.json').read_text())}
    candidates=[]; expected=[]; paths={}
    for s in truth:
        sid=s['id']; values={(i,j):v for i,row in enumerate(s['rows']) for j,v in enumerate(row[1:]) if parse_number(v) is not None}
        faults={}
        for i,j in ((0,0),(3,1),(6,2)):
            key=next(((i,(j+k)%3) for k in range(3) if (i,(j+k)%3) in values),None)
            if key is None:raise ValueError('Fault schedule infeasible')
            faults[key]=str(parse_number(values[key])+1000)
        for variant in ('clean','corrupt'):
            for (i,j),v in values.items():
                r=records[sid,i,j]; p=Path(r['path'])
                if sha(p)!=r['crop_sha256']:raise ValueError('Source crop changed')
                crop=SourceCrop(sid+'-'+variant,s['page'],f'{i}/{j}',tuple(r['crop_bbox']),p.read_bytes())
                paths[crop.digest]=p
                target=faults.get((i,j),v) if variant=='corrupt' else v
                candidates.append(NumericCandidate(crop,visual[sid][i][j],target))
                if variant=='corrupt' and (i,j) in faults:expected.append((crop.document,crop.page,crop.cell))
    return candidates,expected,paths


def prepare(base,out):
    candidates,_,paths=inputs(base)
    selected=sorted({c.crop.digest for c in candidates if parse_number(c.first_value) is not None and parse_number(c.sheet_value) is not None and parse_number(c.first_value)!=parse_number(c.sheet_value)})
    random.Random(20261122).shuffle(selected)
    out.mkdir(exist_ok=False)
    mapping={f'R{i+1:02}':h for i,h in enumerate(selected)}
    for start in range(0,len(mapping),12):
        subset=list(mapping.items())[start:start+12]
        sheet=Image.new('RGB',(900,((len(subset)+2)//3)*150),'white'); draw=ImageDraw.Draw(sheet)
        for i,(token,h) in enumerate(subset):
            im=ImageOps.contain(Image.open(paths[h]).convert('RGB'),(280,112))
            x=(i%3)*300;y=(i//3)*150
            draw.text((x+8,y+5),token,fill='black');sheet.paste(im,(x+8,y+27));draw.rectangle((x,y,x+299,y+149),outline='#b0b0b0')
        sheet.save(out/f'packet-{start//12+1}.png')
    (out/'evaluator-mapping.json').write_text(json.dumps(mapping,indent=2))
    print('Unique source crops:',len(mapping))


def score(base,out):
    candidates,expected,_=inputs(base)
    mapping=json.loads((out/'evaluator-mapping.json').read_text())
    reads=json.loads((out/'visual-reread.json').read_text())['reads']
    if set(reads)!=set(mapping) or len(set(mapping.values()))!=len(mapping):raise ValueError('Incomplete or duplicate reread packet')
    by_hash={h:VisualReading(reads[token],h) for token,h in mapping.items()}
    decisions=confirm_visual(candidates,lambda crop:by_hash.get(crop.digest))
    result={'status':'DEVELOPMENT_ONLY_SAME_ASSISTANT_PRIOR_EXPOSURE','numeric_inputs':len(candidates),'unique_rereads':len(mapping),'faults':len(expected),'scores':score_numeric(expected,decisions),'mapping_sha256':sha(out/'evaluator-mapping.json'),'reread_sha256':sha(out/'visual-reread.json'),'packets':{p.name:sha(p) for p in sorted(out.glob('packet-*.png'))},'business':'HOLD'}
    with (out/'results.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    {'prepare':prepare,'score':score}[sys.argv[1]](*(Path(a).resolve() for a in sys.argv[2:]))
