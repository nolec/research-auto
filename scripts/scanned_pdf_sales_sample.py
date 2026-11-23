"""Package the archived Idaho pilot as a clearly labeled sales demonstration."""
import base64
import html
import io
import json
from pathlib import Path
import time

from PIL import Image
from scripts.scanned_pdf_extraction_economics import extraction_gate
from scripts.scanned_pdf_image_input_evaluate import load_truth
from src.scanned_pdf_experiment.holdout_review import sha
from src.scanned_pdf_experiment.numeric_reread import parse_number

ROOT=Path(__file__).resolve().parents[1]
PACKET=ROOT/'artifacts/scanned-pdf-experiment/assisted-independent-intake-20261122'
OUT=ROOT/'outputs/scanned-pdf-sales-sample'
LABELS=['Horses and colts','Mules and mule colts','Cattle and calves','Hogs and pigs','Sheep and lambs','Goats and kids','Poultry, total value','Chickens']


def png_url(im):
    b=io.BytesIO();im.save(b,format='PNG');return 'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()


def build():
    start=time.perf_counter(); p=PACKET
    m=json.loads((p/'reviewer/manifest.json').read_text()); s=m['scopes'][0]
    result=json.loads((p/'cross-reader-v1/results.json').read_text()); truth_path=p/'adjudication-v2/truth-adjudicated.csv'; visual_path=p/'candidate-images/context-reads-v1.json'; ocr_path=p/'cross-reader-v1/ocr-reads.json'
    for key,path in [('truth_sha256',truth_path),('primary_sha256',visual_path),('ocr_sha256',ocr_path)]:
        if sha(path)!=result[key]:raise ValueError('Archived input changed')
    truth=load_truth(truth_path,m); visual=json.loads(visual_path.read_text())['reads']; ocr={r['id']:r for r in json.loads(ocr_path.read_text())}
    assert set(truth)==set(visual)==set(ocr)
    source=p/'candidate-images'/s['context_image'];assert sha(source)==s['context_sha256'];im=Image.open(source).convert('RGB')
    records=[]
    for c in s['cells']:
        k=c['id'];r=ocr[k]; a=parse_number(visual[k]); b=parse_number(truth[k]);assert a is not None and b is not None
        queued=not extraction_gate(visual[k],[r['scaled'],r['native']]);x0,y0,x1,y1=r['box'];assert 0<=x0<x1<=im.width and 0<=y0<y1<=im.height
        crop=im.crop((x0,y0,x1,y1));records.append({'id':k,'row':c['row']+1,'column':c['column']+1,'item':LABELS[c['row']],'year':int(s['headers'][c['column']]),'page':s['page'],'initial':int(a),'final':int(b),'queue':queued,'changed':a!=b,'crop':png_url(crop),'box':r['box']})
    assert len(records)==24 and sum(r['queue'] for r in records)==13 and sum(r['changed'] for r in records)==1
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'sample-data.json').write_text(json.dumps({'source':m['source_url'],'records':records},indent=2))
    esc=html.escape; rows=[]
    for r in records:
        label='Corrected' if r['changed'] else 'Matched';status='Review requested' if r['queue'] else 'Readers agreed'
        rows.append(f'<tr><td><b>{esc(r["item"])}</b><br><small>{r["year"]} · R{r["row"]}C{r["column"]} · p. {r["page"]}</small></td><td><img class="crop" src="{r["crop"]}" alt="Original number crop"></td><td class="num">{r["initial"]:,}</td><td class="num">{r["final"]:,}</td><td><span class="{"changed" if r["changed"] else "neutral"}">{label}</span><br><small>{status}</small></td></tr>')
    page=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Scanned table QA sample</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f7;color:#142538;font:16px/1.5 system-ui,sans-serif}}main{{max-width:1080px;margin:auto;padding:30px 20px 60px}}header{{border-bottom:1px solid #d8e0e9;padding-bottom:25px}}h1{{font-size:36px;line-height:1.13;margin:8px 0}}h2{{font-size:20px}}small{{color:#576679}}.eyebrow{{font-size:12px;letter-spacing:.12em;font-weight:700;color:#345b7a}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:24px 0}}.stat,section{{background:white;border:1px solid #d8e0e9;border-radius:10px;padding:20px}}.stat strong{{display:block;font-size:32px;color:#153e61}}section{{margin:20px 0}}.source{{display:block;width:100%;height:auto;border:1px solid #d8e0e9}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:680px}}th{{background:#24455f;color:white;text-align:left;padding:10px}}td{{padding:12px 10px;border-bottom:1px solid #e4e9ef}}.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}.crop{{width:160px;height:44px;object-fit:contain;background:#fff}}.changed{{color:#98490c;background:#fff0d8;padding:4px 8px;border-radius:4px;font-weight:650}}.neutral{{color:#245f53}}a{{color:#245d98}}@media(max-width:600px){{.stats{{grid-template-columns:1fr}}h1{{font-size:29px}}}}
</style><main><header><div class="eyebrow">PUBLIC-DATA DEMONSTRATION</div><h1>Scanned table to structured data</h1><p>Source-linked numeric extraction and quality review. Idaho agricultural census, State Table 18, selected rows and years.</p><small>Repackaged from a prior human-reviewed research pilot. This is not a customer project, independent benchmark, or accuracy guarantee.</small></header><div class="stats"><div class="stat"><strong>24</strong>Selected numeric cells</div><div class="stat"><strong>13</strong>Initial review flags</div><div class="stat"><strong>1</strong>Changed value after review</div></div><section><h2>Original source</h2><p><a href="{esc(m['source_url'])}">U.S. Census Bureau, 1940 Agriculture, Volume II, Idaho</a> · PDF page {s['page']} · selected 1940, 1935 and 1920 columns (dollars).</p><img class="source" src="{png_url(im)}" alt="Source table with selected row and column markers"></section><section><h2>Cell-level source record</h2><p>Final values use the archived human-verified transcription. Reader agreement is a triage signal; even matching readers require human review for customer work. Crop boundaries are approximate; use the full table for context.</p><div class="scroll"><table><thead><tr><th>Source location</th><th>Original crop</th><th>Initial read</th><th>Final value</th><th>Review outcome</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section><p><small>Only the selected 24 cells are represented. No guarantee is made about other rows, columns, or pages.</small></p></main></html>'''
    (OUT/'source-linked-sample.html').write_text(page)
    print(f'Packaged {len(records)} cells in {time.perf_counter()-start:.3f} s (packaging only; excludes prior extraction and human review)')


if __name__=='__main__':build()
