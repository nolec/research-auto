"""Build an offline review form for the public PDF ground-truth transcription."""
import base64
import html
import io
import json
from pathlib import Path

from PIL import Image

from scanned_pdf_synthetic_pilot import ROOT


BASE = ROOT / 'artifacts/scanned-pdf-experiment/public-pilot-20261122'
BOXES = [
    (120, 1220, 840, 1690), (60, 910, 790, 1510),
    (70, 210, 1100, 1240), (145, 1250, 1020, 1750),
    (150, 1390, 1040, 1940), (140, 575, 1550, 1050),
    (160, 365, 1575, 980), (60, 1540, 1090, 2115),
    (145, 205, 1570, 875), (120, 1060, 890, 2050),
]


def image_url(path, box=None):
    image = Image.open(path)
    if box:
        image = image.crop(box)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def main():
    review = BASE / 'llm-ten-review'
    data = json.loads((review / 'transcription-reviewed.json').read_text())
    sections = []
    for index, (table, box) in enumerate(zip(data['tables'], BOXES, strict=True)):
        pdf = table['pdf']
        page = table['page']
        path = BASE / 'page-preflight' / f'{Path(pdf).stem}-page-{page}.png'
        rows = []
        for row_id, row in enumerate(table['rows']):
            fields = ''.join(f'<td><input aria-label="{html.escape(col)}" data-column="{html.escape(col)}" value="{html.escape(value)}" required></td>' for col, value in zip(table['columns'], row, strict=True))
            rows.append(f'<tr data-row="{row_id}">{fields}</tr>')
        headings = ''.join(f'<th>{html.escape(c)}</th>' for c in table['columns'])
        sections.append(f'''<section data-index="{index}" data-pdf="{pdf}" data-page="{page}" data-table="{table['table']}" hidden>
<div class="title"><h2>{index+1}. 표 {table['table']} · {pdf}, p.{page}</h2><p>{html.escape(table['scope'])}</p></div>
<div class="grid"><div class="source"><h3>원본 스캔</h3><img src="{image_url(path,box)}" alt="표 원본"><details><summary>전체 페이지 보기</summary><img loading="lazy" src="{image_url(path)}" alt="전체 원본"></details></div>
<div><h3>추출값 대조</h3><p>오류가 있으면 입력값을 수정하세요. NA와 —는 원본에 표시된 결측 값입니다.</p><div class="table-scroll"><table><thead><tr>{headings}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<label class="confirm"><input class="verified" type="checkbox"> 원본과 32개 셀을 모두 대조했고 현재 값이 정확합니다.</label></div></div>
</section>''')
    destination = review / 'review.html'
    template = '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>공개 스캔 PDF 정답 검증</title>
<style>body{font:15px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;color:#182534;background:#f4f6f8;margin:0}main{max-width:1540px;margin:auto;padding:28px}header,section{background:white;border:1px solid #d9dfe5;border-radius:12px;padding:22px;margin-bottom:18px}header{position:sticky;top:0;z-index:2}h1{font-size:23px;margin:0}h2{font-size:20px}h3{font-size:16px}.grid{display:grid;grid-template-columns:1.15fr 1fr;gap:22px}.source{min-width:0}.source img{width:100%;border:1px solid #ddd;display:block}.table-scroll{overflow:auto}table{border-collapse:collapse;width:100%}th,td{padding:6px;border-bottom:1px solid #e1e5e9;text-align:left}th{font-size:12px}td:first-child input{min-width:160px}td input{box-sizing:border-box;width:100%;min-width:80px;padding:8px;border:1px solid #bac7d4;border-radius:4px;font:inherit}.confirm{display:block;background:#edf4ff;padding:12px;margin-top:16px}button{padding:10px 15px;border:1px solid #bac7d4;background:white;border-radius:7px;font:inherit;cursor:pointer}button.primary{background:#185bd1;color:white;border:0}button:disabled{opacity:.45;cursor:default}nav{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.muted{color:#526478}details{margin-top:12px}[hidden]{display:none!important}@media(max-width:960px){.grid{grid-template-columns:1fr}header{position:static}main{padding:12px}}</style></head><body><main>
<header><h1>공개 스캔 PDF 정답 검증</h1><p class="muted">10개 표 · 320개 셀 · 사람의 원본 대조가 완료되어야 정확도 평가를 시작할 수 있습니다.</p><nav><button id="prev">이전</button><span id="progress"></span><button id="next">다음</button><button id="export" class="primary" disabled>검증 결과 CSV 저장</button></nav><p class="muted">입력 내용은 이 페이지에서만 유지됩니다. 중간 저장을 위해 CSV를 내보낼 수 있습니다.</p></header>
SECTIONS
</main><script>
const sections=[...document.querySelectorAll('section')];let current=0;
const progress=document.querySelector('#progress'),save=document.querySelector('#export');
function update(){sections.forEach((s,i)=>s.hidden=i!==current);const confirmed=sections.filter(s=>s.querySelector('.verified').checked).length;progress.textContent=`표 ${current+1}/${sections.length} · 검증 완료 ${confirmed}/${sections.length}`;document.querySelector('#prev').disabled=current===0;document.querySelector('#next').disabled=current===sections.length-1;save.disabled=false;}
document.querySelector('#prev').onclick=()=>{current--;update()};document.querySelector('#next').onclick=()=>{current++;update()};
sections.forEach(s=>{s.querySelector('.verified').onchange=()=>{if([...s.querySelectorAll('td input')].some(x=>!x.value.trim()))s.querySelector('.verified').checked=false;update()};s.querySelectorAll('td input').forEach(x=>x.oninput=()=>{s.querySelector('.verified').checked=false;update()})});
save.onclick=()=>{const rows=[['pdf','page','table','row_index','column','human_corrected_value','human_status']];sections.forEach(s=>s.querySelectorAll('tbody tr').forEach(tr=>tr.querySelectorAll('input').forEach(input=>rows.push([s.dataset.pdf,s.dataset.page,s.dataset.table,tr.dataset.row,input.dataset.column,input.value,s.querySelector('.verified').checked?'VERIFIED':'PENDING']))));const csv=rows.map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\\r\\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='scanned-pdf-human-verified.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};update();</script></body></html>'''
    with destination.open('x') as file:
        file.write(template.replace('SECTIONS', '\n'.join(sections)))
    print(destination)


if __name__ == '__main__':
    main()
