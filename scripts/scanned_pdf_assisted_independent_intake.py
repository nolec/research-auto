"""Freeze a new-document image-input pilot without reading PDF text values."""
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont
from scripts.scanned_pdf_image_input_review import BASE, POPPLER, image_url
from src.scanned_pdf_experiment.holdout_review import sha, manifest_digest

NAME = '1940-census-agriculture-vol-2-idaho.pdf'
URL = 'https://www2.census.gov/library/publications/decennial/1940/agriculture/' + NAME
PAGE = 4
# Frozen from the 150 dpi page geometry: six livestock rows and two poultry rows.
ROWS = [371,384,397,410,423,436,461,474]
COLS = [(553,660),(667,776),(1011,1118)]
HEADERS = ['1940','1935','1920']
OVERVIEW = (138,185,1238,488)


def build():
    source = Path.home()/'Downloads'/NAME
    parent = BASE.parent
    h = sha(source)
    if h in {sha(p) for p in parent.rglob('*.pdf')}:
        raise ValueError('Source already present in historical experiment')
    out = parent/'assisted-independent-intake-20261122'
    out.mkdir(exist_ok=False)
    src = out/'source'; src.mkdir(); dest = src/NAME; shutil.copyfile(source,dest)
    if sha(dest)!=h: raise ValueError('Copy mismatch')
    reviewer = out/'reviewer'; reviewer.mkdir(); candidate = out/'candidate-images'; candidate.mkdir()
    prefix = reviewer/'I01-page-4'
    subprocess.run([str(POPPLER/'bin/pdftoppm'),'-f','4','-l','4','-r','300','-png','-singlefile',str(dest),str(prefix)],check=True)
    page = prefix.with_suffix('.png'); full = Image.open(page).convert('RGB')
    sx,sy = full.width/1304,full.height/1738
    def scale(box):return tuple(round(v*s) for v,s in zip(box,(sx,sy,sx,sy)))
    x0,y0,x1,y1=scale(OVERVIEW); crop=full.crop((x0,y0,x1,y1)); canvas=Image.new('RGB',(crop.width+80,crop.height+50),'white');canvas.paste(crop,(80,50))
    draw=ImageDraw.Draw(canvas); font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',24)
    for i,y in enumerate(ROWS):
        py=round(y*sy)-y0+50;draw.text((4,py-13),f'R{i+1}',font=font,fill='#164e86');draw.line((43,py,76,py),fill='#164e86',width=2)
    for j,(l,r) in enumerate(COLS):
        px=round((l+r)*sx/2)-x0+80;draw.text((px-13,5),f'C{j+1}',font=font,fill='#164e86')
    context=candidate/'I01-context.png';canvas.save(context)
    cells=[]; rows=[]; ids=[]
    for i,y in enumerate(ROWS):
        fields=[]; rowids=[]
        for j,(l,r) in enumerate(COLS):
            token=hashlib.sha256(f'independent-v1/{h}/{PAGE}/{i}/{j}'.encode()).hexdigest()[:16]
            box=scale((l,y-6,r,y+6)); raw=full.crop(box)
            fields.append(f'<td><img src="{image_url(raw)}" alt="원본 숫자"><input data-token="{token}" value="" aria-label="R{i+1} C{j+1}"></td>')
            rowids.append(token);cells.append({'id':token,'row':i,'column':j,'bbox':box})
        ids.append(rowids);rows.append(f'<tr><th>R{i+1}</th>'+''.join(fields)+'</tr>')
    scope={'id':'I01','scope':'Idaho: State Table 18 — livestock value','page':PAGE,'source_sha256':h,'render_sha256':sha(page),'context_image':context.name,'context_sha256':sha(context),'headers':HEADERS,'cells':cells}
    manifest={'status':'HUMAN_TRUTH_PENDING','stratum':'NEW_DOCUMENT_IMAGE_INPUT_PILOT','scopes':[scope],'source_url':URL,'numeric_scope_only':True,'source_only_candidate_input':True,'fault_schedule':'row indices 0/3/6, columns 0/1/2; cyclic numeric fallback; +1000','thresholds':{'precision':.95,'recall':.90},'note':'One new document, not sufficient for product qualification. Text layer not used.'}
    manifest['manifest_sha256']=manifest_digest(manifest)
    (reviewer/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (candidate/'packet-index.json').write_text(json.dumps({'records':[{'id':'I01','image':context.name,'sha256':sha(context),'ids':ids}]},indent=2))
    section=f'<section hidden><h2>Idaho · PDF 4페이지</h2><p>원본 R/C 및 확대 이미지를 확인해 각 숫자를 입력하세요.</p><img style="width:100%" src="{image_url(canvas)}"><table><thead><tr><th>행</th>'+''.join(f'<th>C{i+1}: {html.escape(v)}</th>' for i,v in enumerate(HEADERS))+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table><label><input type="checkbox" class="verified"> 24개 숫자를 원본과 대조했습니다.</label></section>'
    template=Path(__file__).with_name('scanned_pdf_image_input_review.html').read_text()
    (reviewer/'review.html').write_text(template.replace('__HASH__',manifest['manifest_sha256']).replace('<!--SECTIONS-->',section).replace('8개 표 · 숫자 192개. 기존 PDF 텍스트는 입력 초안에만 사용했으며 정답이 아닙니다. 셀 이미지와 대조해 수정해주세요.','새 문서 1개 · 숫자 24개. 원본 이미지에서 숫자를 직접 확인해 입력해주세요.').replace('image-input-human-verified.csv','assisted-independent-human-verified.csv'))
    print('New document registered; 24 cells; candidate inference NOT RUN')


if __name__=='__main__':build()
