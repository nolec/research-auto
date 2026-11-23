"""Source-only Tesseract cross-reader for contextual page development data."""
import json
from pathlib import Path

from PIL import Image,ImageOps
from scripts.scanned_pdf_context_page_holdout import BASE,SPECS
from scripts.scanned_pdf_image_input_review import align_row
from scripts.scanned_pdf_holdout_numeric_read import recognize,MODEL,RUNNER
from src.scanned_pdf_experiment.holdout_review import sha


def read():
    packet=BASE/'context-new-page-v2';source=packet/'candidate-images';index=json.loads((source/'packet-index.json').read_text());byid={r['id']:r for r in index['records']}
    out=packet/'cross-reader-v1';out.mkdir(exist_ok=False);records=[]
    freeze={'status':'RETROSPECTIVE_DEVELOPMENT_ONLY','model_sha256':sha(MODEL),'runner_sha256':sha(RUNNER),'script_sha256':sha(Path(__file__)),'context_hashes':{r['id']:r['sha256'] for r in index['records']},'preprocessing':'image-only row alignment, column interior, 12-pixel preview row window, 2x resize with white padding, SINGLE_LINE; second fixed grayscale variant with no resize','policy':'require valid numeric OCR with confidence >=80 and agreement of both Tesseract preprocessing variants plus primary visual read before confirming discrepancy'}
    (out/'freeze.json').write_text(json.dumps(freeze,indent=2))
    for sid,n,scope,columns,centers,headers,overview in SPECS:
        rec=byid[sid];original=source/rec['image'];assert sha(original)==rec['sha256'];im=Image.open(original).convert('L')
        # Context raster includes 80 left / 50 top external marker margins.
        # Scale is derived from the frozen crop width/height and original geometry.
        x0,y0,x1,y1=overview;sx=(im.width-80)/(x1-x0);sy=(im.height-50)/(y1-y0)
        preview=im.crop((80,50,im.width,im.height)).resize((x1-x0,y1-y0))
        paths1=[];paths2=[];pending=[];folder=out/sid;folder.mkdir()
        for i,y in enumerate(centers):
            for j,(l,h) in enumerate(columns):
                center=align_row(preview,l-x0,h-x0,y-y0)+y0
                box=(round((l+2-x0)*sx)+80,round((center-6-y0)*sy)+50,round((h-2-x0)*sx)+80,round((center+6-y0)*sy)+50)
                raw=im.crop(box);token=rec['ids'][i][j];a=folder/f'{token}-scaled.png';b=folder/f'{token}-native.png'
                # Both variants are OCR on the same source, not independent engines.
                ImageOps.expand(ImageOps.autocontrast(raw).resize((raw.width*2,raw.height*2)),border=18,fill=255).save(a)
                ImageOps.expand(raw,border=10,fill=255).save(b)
                paths1.append(a.resolve());paths2.append(b.resolve());pending.append({'id':token,'scope':sid,'row':i,'column':j,'context_sha256':rec['sha256'],'box':box,'scaled_sha256':sha(a),'native_sha256':sha(b)})
        a=recognize(paths1,'--single-line');b=recognize(paths2,'--single-line')
        records.extend({**r,'scaled':x,'native':y} for r,x,y in zip(pending,a,b,strict=True));print(sid,len(pending),flush=True)
    (out/'ocr-reads.json').write_text(json.dumps(records,indent=2))


if __name__=='__main__':read()
