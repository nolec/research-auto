"""Freeze new-page context inputs from previously acquired public scan sources.

The candidate directory contains only source raster context and row/column IDs.
The embedded text draft is confined to reviewer-side files.
"""
import hashlib
import html
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from PIL import Image,ImageDraw,ImageFont
from scripts.scanned_pdf_image_input_review import BASE,POPPLER,draft_value,image_url,align_row
from src.scanned_pdf_experiment.holdout_review import sha,manifest_digest

# Selected from new-page visual geometry, before candidate reads or truth.
# Coordinates at 150 dpi. Retain intervening rows and all relevant headers.
SPECS=[
 ('N01',6,'Rhode Island: crops, corn',[(610,700),(801,892),(897,988)],[212,224,237,249,262,275,288,300],['1939','1929','1924'],(72,145,993,316)),
 ('N02',11,'Utah: automobile model years',[(508,582),(588,653),(658,725)],[375,388,401,414,427,440,453,466],['Total','All owners','Full owners'],(88,172,728,481)),
 ('N03',13,'Vermont: annual legumes and dry field beans',[(595,710),(716,818),(823,927)],[673,687,700,713,725,854,866,879],['1939','1934','1929'],(145,581,930,894)),
 ('N04',15,'Washington: small fruits',[(545,662),(775,880),(992,1091)],[286,299,313,365,377,390,403,416],['1939','1929','1919'],(95,197,1095,431)),
 ('N05',10,'South Carolina: Chesterfield County',[(297,350),(355,405),(409,468)],[217,241,253,265,278,290,302,316],['1950','1940','1930'],(92,152,470,331)),
 ('N06',13,'North Carolina: Haywood County',[(326,376),(380,430),(434,489)],[228,253,265,290,303,315,328,341],['1950','1940','1930'],(124,164,491,356)),
 ('N07',15,'Texas: Coke County',[(287,337),(341,388),(393,449)],[224,248,261,273,286,299,310,323],['1950','1940','1930'],(86,158,451,338)),
 ('N08',25,'United States: types and sizes of places',[(954,1011),(1015,1090),(1094,1154)],[955,981,994,1007,1020,1033,1057,1069],['Incorporated number','Incorporated population','Unincorporated number'],(704,835,1240,1086)),
]


def build():
    intake=json.loads((BASE/'intake.json').read_text());byid={r['id']:r for r in intake['records']};old=json.loads((BASE/'image-input-review-v2/reviewer/manifest.json').read_text());old_pages={(s['id'],s['page']) for s in old['scopes']}
    out=BASE/'context-new-page-v2';out.mkdir(exist_ok=False);reader=out/'candidate-images';reader.mkdir();reviewer=out/'reviewer';reviewer.mkdir()
    font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',24);scopes=[];packets=[];sections=[]
    for sid,n,scope,columns,centers,headers,overview in SPECS:
        if (sid,n) in old_pages:raise ValueError('Previously evaluated page')
        r=byid[sid];pdf=BASE/'source'/r['file'];assert sha(pdf)==r['sha256']
        prefix=reviewer/f'{sid}-page-{n}';subprocess.run([str(POPPLER/'bin/pdftoppm'),'-f',str(n),'-l',str(n),'-r','300','-png','-singlefile',str(pdf),str(prefix)],check=True)
        page=prefix.with_suffix('.png');im=Image.open(page).convert('RGB');preview=Image.open(BASE/'context-new-page-preview'/f'{sid}-page-{n}.png');sx,sy=im.width/preview.width,im.height/preview.height
        box=tuple(round(v*s) for v,s in zip(overview,(sx,sy,sx,sy)));crop=im.crop(box);canvas=Image.new('RGB',(crop.width+80,crop.height+50),'white');canvas.paste(crop,(80,50));d=ImageDraw.Draw(canvas)
        for i,y in enumerate(centers):
            py=round(y*sy)-box[1]+50;d.text((4,py-13),f'R{i+1}',font=font,fill='#164e86');d.line((43,py,76,py),fill='#164e86',width=2)
        for j,(l,h) in enumerate(columns):
            px=round((l+h)*sx/2)-box[0]+80;d.text((px-13,5),f'C{j+1}',font=font,fill='#164e86')
        image=reader/f'{sid}-context.png';canvas.save(image);context_hash=sha(image)
        # Extract embedded text only after source context is built, never expose
        # its contents to the candidate. This is an unverified reviewer draft.
        root=ET.fromstring(subprocess.check_output([str(POPPLER/'poppler/bin/pdftotext'),'-f',str(n),'-l',str(n),'-bbox',str(pdf),'-']));xp=next(root.iter('{http://www.w3.org/1999/xhtml}page'));wx=preview.width/float(xp.attrib['width']);wy=preview.height/float(xp.attrib['height']);words=[]
        for w in xp.iter('{http://www.w3.org/1999/xhtml}word'):
            a=w.attrib;words.append(((float(a['xMin'])+float(a['xMax']))/2*wx,(float(a['yMin'])+float(a['yMax']))/2*wy,w.text or ''))
        cells=[];rows=[];ids=[]
        for i,y in enumerate(centers):
            fields=[];rowids=[]
            for j,(l,h) in enumerate(columns):
                center=align_row(preview,l,h,y);val=draft_value(words,(l,center-6,h,center+6));token=hashlib.sha256(f'context-new-page-v1/{sid}/{n}/{i}/{j}'.encode()).hexdigest()[:16];cells.append({'id':token,'row':i,'column':j,'draft':val});rowids.append(token);fields.append(f'<td><input data-token="{token}" value="{html.escape(val)}" aria-label="R{i+1} C{j+1}"></td>')
            ids.append(rowids);rows.append(f'<tr><th>R{i+1}</th>'+''.join(fields)+'</tr>')
        scopes.append({'id':sid,'page':n,'scope':scope,'source_sha256':r['sha256'],'render_sha256':sha(page),'context_image':image.name,'context_sha256':context_hash,'headers':headers,'cells':cells});packets.append({'id':sid,'image':image.name,'sha256':context_hash,'ids':ids})
        sections.append(f'<section hidden><h2>{sid} · {html.escape(scope)}</h2><p>PDF {n}페이지. R/C 표시가 가리키는 행과 열의 교차 값을 직접 확인하세요. 숫자가 아닌 기호는 원문 그대로 입력합니다.</p><img style="width:100%;max-height:none" src="{image_url(canvas)}"><table><thead><tr><th>행</th>'+''.join(f'<th>C{i+1}: {html.escape(h)}</th>' for i,h in enumerate(headers))+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table><label><input type="checkbox" class="verified"> 24개 셀을 원본 표에서 대조했습니다.</label></section>')
    manifest={'status':'HUMAN_TRUTH_PENDING','stratum':'CONTEXT_PAGE_HOLDOUT_SHARED_SOURCE_PDFS','numeric_scope_only':True,'scopes':scopes,'fault_schedule':'3 numeric mutations per table on rows 0/3/6; cyclic numeric-column fallback; +1000','thresholds':{'precision':.95,'recall':.90},'source_only_candidate_input':True};manifest['manifest_sha256']=manifest_digest(manifest);(reviewer/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (reader/'packet-index.json').write_text(json.dumps({'records':packets},indent=2));template=Path(__file__).with_name('scanned_pdf_image_input_review.html').read_text();(reviewer/'review.html').write_text(template.replace('__HASH__',manifest['manifest_sha256']).replace('<!--SECTIONS-->','\n'.join(sections)).replace('image-input-human-verified.csv','context-new-page-human-verified.csv'))
    print('scopes',len(scopes),'cells',sum(len(s['cells']) for s in scopes),'unreadable drafts',sum(c['draft']=='UNREADABLE' for s in scopes for c in s['cells']),'manifest',manifest['manifest_sha256'])


if __name__=='__main__':build()
