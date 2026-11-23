"""Prepare a distinct text-layer-source / image-input numerical evaluation cohort.

Embedded OCR is evaluator-side draft only. Candidate packets contain images and
opaque identifiers; no text layer, ground truth, or draft values are exported.
"""
import csv
import hashlib
import html
import io
import json
import base64
from pathlib import Path
import random
import re
import subprocess
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageOps
from src.scanned_pdf_experiment.holdout_review import sha, manifest_digest

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'artifacts/scanned-pdf-experiment/prospective-holdout-20261122'
POPPLER=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler'
# Geometry in the visually inspected 150 dpi previews. Row centers are numeric
# baselines/centers, not OCR text values. Three selected numeric columns.
SPECS=[
 ('N01',4,'Rhode Island — State Table 1: farms, color and tenure',[(603,692),(698,785),(790,879)],[279,305,318,344,357,370,382,395],['1940','1935','1930'],(78,196,887,405)),
 ('N02',8,'Utah — State Table 8: cooperative selling and expenditures',[(701,801),(807,910),(915,1019)],[1313,1326,1339,1352,1365,1378,1419,1432],['1939','1929','1924'],(138,1223,1020,1444)),
 ('N03',10,'Vermont — State Table 10: age of farm operators',[(574,634),(640,698),(704,760)],[287,300,313,325,338,351,364,377],['Total','All owners','Full owners'],(110,174,765,388)),
 ('N04',12,'Washington — State Table 12: farm acreage and value',[(793,895),(901,1002),(1009,1111)],[239,253,266,278,291,304,317,330],['1940','1930','1920'],(120,165,1114,343)),
 ('N05',8,'South Carolina — Table 5: county population, selected rows',[(358,418),(478,540),(545,606)],[390,402,427,439,477,489,501,514],['1950 total','1940','1930'],(90,176,609,524)),
 ('N06',10,'North Carolina — Table 6: Alamance county and civil divisions',[(327,376),(380,427),(431,484)],[257,281,294,306,319,331,343,356],['1950','1940','1930'],(126,197,486,367)),
 ('N07',12,'Texas — Table 5: county population, Robertson to San Patricio',[(381,437),(501,562),(567,630)],[324,337,349,362,375,400,413,426],['1950 total','1940','1930'],(114,164,634,437)),
 ('N08',12,'United States — Table E: urban/rural population by definition',[(246,319),(324,388),(394,459)],[455,480,505,530,554,566,590,614],['Total','Urban total','Incorporated urban places'],(72,258,465,625)),
]


def draft_value(words, box):
    x0,y0,x1,y1=box
    chosen=sorted((x,t) for x,y,t in words if x0<=x<=x1 and y0<=y<=y1)
    val=''.join(t for x,t in chosen).strip()
    if re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?',val):return val
    if re.fullmatch(r'[-—–.]+',val):return '—'
    if re.fullmatch(r'\(\d+\)',val):return val
    return 'UNREADABLE'


def image_url(im):
    buf=io.BytesIO();im.save(buf,format='PNG');return 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode('ascii')


def align_row(preview, left, right, nominal):
    """Image-only baseline adjustment: maximize foreground in a local window."""
    region=preview.crop((left+3,nominal-12,right-3,nominal+12)).convert('L')
    weights=[sum(v<145 for v in region.crop((0,y,region.width,y+1)).getdata()) for y in range(region.height)]
    best=max(range(-4,5),key=lambda offset:(sum(weights[12+offset-5:12+offset+5]),-abs(offset)))
    return nominal+best


def build():
    intake=json.loads((BASE/'intake.json').read_text()); records={r['id']:r for r in intake['records']}
    out=BASE/'image-input-review-v2';out.mkdir(exist_ok=False)
    reader=out/'candidate-images';reader.mkdir();review=out/'reviewer';review.mkdir()
    scopes=[];all_cells=[];sections=[]
    for sid,n,scope,columns,centers,headers,overview in SPECS:
        rec=records[sid];pdf=BASE/'source'/rec['file']
        if sha(pdf)!=rec['sha256']:raise ValueError('Changed source')
        prefix=review/f'{sid}-page-{n}';subprocess.run([str(POPPLER/'bin/pdftoppm'),'-f',str(n),'-l',str(n),'-r','300','-png','-singlefile',str(pdf),str(prefix)],check=True)
        page=prefix.with_suffix('.png'); im=Image.open(page).convert('RGB')
        preview=Image.open(BASE/'image-input-preview'/f'{sid}-page-{n}.png');sx,sy=im.width/preview.width,im.height/preview.height
        xml=subprocess.check_output([str(POPPLER/'poppler/bin/pdftotext'),'-f',str(n),'-l',str(n),'-bbox',str(pdf),'-']);root=ET.fromstring(xml); xp=next(root.iter('{http://www.w3.org/1999/xhtml}page')); wx=preview.width/float(xp.attrib['width']); wy=preview.height/float(xp.attrib['height']);words=[]
        for w in xp.iter('{http://www.w3.org/1999/xhtml}word'):
            a=w.attrib;words.append(((float(a['xMin'])+float(a['xMax']))/2*wx,(float(a['yMin'])+float(a['yMax']))/2*wy,w.text or ''))
        scale=lambda box:tuple(round(v*s) for v,s in zip(box,(sx,sy,sx,sy)))
        over=im.crop(scale(overview));over_path=review/f'{sid}-overview.png';over.save(over_path)
        cells=[]; rows=[]
        for i,y in enumerate(centers):
            fields=[]
            for j,(left,right) in enumerate(columns):
                # Fixed 12-pixel-tall crops in the preview, doubled at 300 dpi.
                center=align_row(preview,left,right,y)
                box=(left,center-6,right,center+6); raw=im.crop(scale(box)); token=hashlib.sha256(f'20261122/{sid}/{i}/{j}'.encode()).hexdigest()[:16]
                path=reader/f'{token}.png';raw.save(path)
                val=draft_value(words,box);entry={'id':token,'row':i,'column':j,'bbox':scale(box),'crop_sha256':sha(path),'draft':val};cells.append(entry);all_cells.append(entry)
                enlarged=ImageOps.contain(raw,(240,50));fields.append(f'<td><img src="{image_url(enlarged)}" alt="원본 숫자"><input data-token="{token}" value="{html.escape(val)}" aria-label="{i+1}행 {html.escape(headers[j])}"></td>')
            rows.append(f'<tr><th>{i+1}</th>'+''.join(fields)+'</tr>')
        scopes.append({'id':sid,'page':n,'scope':scope,'source_sha256':rec['sha256'],'render_sha256':sha(page),'overview_sha256':sha(over_path),'headers':headers,'cells':cells})
        sections.append(f'<section hidden><h2>{sid} · {html.escape(scope)}</h2><p>PDF {n}페이지. 숫자 셀만 대조하세요. 원본 값이 숫자가 아니면 기호를 그대로 입력하세요.</p><img class="overview" src="{image_url(over)}"><table><thead><tr><th>행</th>'+''.join(f'<th>{html.escape(h)}</th>' for h in headers)+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table><label><input type="checkbox" class="verified"> 24개 숫자 셀을 이미지와 대조했습니다.</label></section>')
    manifest={'status':'HUMAN_TRUTH_PENDING','stratum':'SCANNED_WITH_TEXT_LAYER_IMAGE_ONLY_CANDIDATE_INPUT','scopes':scopes,'numeric_scope_only':True,'fault_schedule':'3 numeric mutations per table on rows 0/3/6; cyclic numeric-column fallback; +1000','thresholds':{'precision':0.95,'recall':0.90},'source_only_candidate_input':True}
    manifest['manifest_sha256']=manifest_digest(manifest);(review/'manifest.json').write_text(json.dumps(manifest,indent=2))
    # Source-only packet mapping is opaque; no draft data exported.
    tokens=[c['id'] for c in all_cells];random.Random(20261122).shuffle(tokens);(reader/'order.json').write_text(json.dumps(tokens))
    for start in range(0,len(tokens),12):
        ids=tokens[start:start+12];sheet=Image.new('RGB',(900,600),'white');d=ImageDraw.Draw(sheet)
        for i,token in enumerate(ids):
            x=i%3*300;y=i//3*150; crop=ImageOps.contain(Image.open(reader/f'{token}.png'),(280,112));d.text((x+5,y+5),token,fill='black');sheet.paste(crop,(x+5,y+25));d.rectangle((x,y,x+299,y+149),outline='#bbb')
        sheet.save(reader/f'packet-{start//12+1:02}.png')
    template=Path(__file__).with_name('scanned_pdf_image_input_review.html').read_text();(review/'review.html').write_text(template.replace('__HASH__',manifest['manifest_sha256']).replace('<!--SECTIONS-->','\n'.join(sections)))
    print('scopes',len(scopes),'cells',len(all_cells),'draft missing',sum(c['draft']=='UNREADABLE' for c in all_cells),'manifest',manifest['manifest_sha256'])


if __name__=='__main__':build()
