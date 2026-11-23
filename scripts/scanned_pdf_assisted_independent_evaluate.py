"""One-document image-only-input diagnostic, freezing readings before truth access."""
import json
from pathlib import Path
import shutil

from PIL import Image, ImageOps
from scripts.scanned_pdf_assisted_independent_intake import BASE, ROWS, COLS, OVERVIEW
from scripts.scanned_pdf_context_cross_evaluate import score
from scripts.scanned_pdf_image_input_review import align_row
from scripts.scanned_pdf_holdout_numeric_read import recognize, MODEL, RUNNER
from scripts.scanned_pdf_image_input_evaluate import load_truth
from src.scanned_pdf_experiment.holdout_review import sha
from src.scanned_pdf_experiment.numeric_reread import parse_number

PACKET=BASE.parent/'assisted-independent-intake-20261122'
# Visual transcription of the source context image only, before opening the CSV.
VISUAL=[['9568881','11915470','24368376'],['313741','449632','810787'],['28987675','14238076','36382229'],['2194534','1040549','3567413'],['8861267','10270441','29249086'],['16587','9715','14808'],['1059911','987989','1489053'],['1001019','851428','1360514']]


def freeze_reads(packet):
    src=packet/'candidate-images'; rec=json.loads((src/'packet-index.json').read_text())['records'][0]
    path=src/rec['image']; assert sha(path)==rec['sha256']; im=Image.open(path).convert('L')
    primary={k:VISUAL[i][j] for i,row in enumerate(rec['ids']) for j,k in enumerate(row)}
    p=src/'context-reads-v1.json'
    with p.open('x') as f: json.dump({'reads':primary,'provenance':'context image visual transcription; no human CSV opened'},f,indent=2)
    out=packet/'cross-reader-v1';out.mkdir(exist_ok=False); folder=out/rec['id'];folder.mkdir()
    freeze={'status':'NEW_DOCUMENT_SMALL_SAMPLE','context_sha256':rec['sha256'],'primary_sha256':sha(p),'model_sha256':sha(MODEL),'runner_sha256':sha(RUNNER),'script_sha256':sha(Path(__file__)),'policy':'same two OCR preprocessing views and 80 confidence gate as contextual development'}
    (out/'freeze.json').write_text(json.dumps(freeze,indent=2))
    x0,y0,x1,y1=OVERVIEW;sx=(im.width-80)/(x1-x0);sy=(im.height-50)/(y1-y0)
    preview=im.crop((80,50,im.width,im.height)).resize((x1-x0,y1-y0));a=[];b=[];records=[]
    for i,y in enumerate(ROWS):
        for j,(l,h) in enumerate(COLS):
            center=align_row(preview,l-x0,h-x0,y-y0)+y0
            box=(round((l+2-x0)*sx)+80,round((center-6-y0)*sy)+50,round((h-2-x0)*sx)+80,round((center+6-y0)*sy)+50)
            raw=im.crop(box);k=rec['ids'][i][j];pa=folder/f'{k}-scaled.png';pb=folder/f'{k}-native.png'
            ImageOps.expand(ImageOps.autocontrast(raw).resize((raw.width*2,raw.height*2)),border=18,fill=255).save(pa)
            ImageOps.expand(raw,border=10,fill=255).save(pb)
            a.append(pa.resolve());b.append(pb.resolve());records.append({'id':k,'scope':rec['id'],'row':i,'column':j,'box':box,'context_sha256':rec['sha256'],'scaled_sha256':sha(pa),'native_sha256':sha(pb)})
    ra=recognize(a,'--single-line');rb=recognize(b,'--single-line')
    with (out/'ocr-reads.json').open('x') as f:json.dump([{**r,'scaled':x,'native':y} for r,x,y in zip(records,ra,rb,strict=True)],f,indent=2)


def evaluate(packet, submission):
    out=packet/'cross-reader-v1'; manifest=json.loads((packet/'reviewer/manifest.json').read_text());p=packet/'candidate-images/context-reads-v1.json';op=out/'ocr-reads.json'
    freeze=json.loads((out/'freeze.json').read_text());assert freeze['primary_sha256']==sha(p)
    primary=json.loads(p.read_text())['reads'];ocr={r['id']:r for r in json.loads(op.read_text())}
    truth=load_truth(submission,manifest);assert set(truth)==set(primary)==set(ocr)
    dest=packet/'adjudication-v2';dest.mkdir(exist_ok=False);truthpath=dest/'truth-adjudicated.csv';shutil.copyfile(submission,truthpath)
    eligible={k:parse_number(v) for k,v in truth.items() if parse_number(v) is not None}
    scores={'strict_two_ocr_views':score(manifest,truth,primary,ocr,('scaled','native'))}
    s=scores['strict_two_ocr_views'];actual=s['tp']+s['fn'];queue_actual=s['tp']+s['uncertain_actual_errors']
    result={'status':'NEW_DOCUMENT_IMAGE_INPUT_SMALL_SAMPLE','truth_sha256':sha(truthpath),'primary_sha256':sha(p),'ocr_sha256':sha(op),'freeze_sha256':sha(out/'freeze.json'),'scores':scores,'visual_exact':sum(parse_number(primary[k])==v for k,v in eligible.items()),'eligible':len(eligible),'queue_fault_coverage':queue_actual/actual,'queue_share':s['review_queue']/(2*len(eligible)),'differences':[{'id':k,'human':str(v),'visual':primary[k]} for k,v in eligible.items() if parse_number(primary[k])!=v],'business':'HOLD'}
    with (out/'results.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    freeze_reads(PACKET)
    evaluate(PACKET,Path.home()/'Downloads/assisted-independent-human-verified.csv')
