"""Prepare isolated, human-verifiable truth review packets (no candidate OCR)."""

import base64
import csv
import hashlib
import html
import io
import json
from pathlib import Path
import subprocess
import shutil

from PIL import Image


def sha(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def validate_scope(scope: dict) -> None:
    columns, rows = scope['columns'], scope['rows']
    if not 3 <= len(columns) <= 6 or not 8 <= len(rows) <= 20 or len(columns) * len(rows) > 120:
        raise ValueError('Invalid table dimensions')
    if len(set(columns)) != len(columns) or len({r[0] for r in rows}) != len(rows):
        raise ValueError('Non-unique semantic keys')
    if any(len(r) != len(columns) for r in rows):
        raise ValueError('Non-rectangular table')
    if any(not isinstance(v, str) or not v.strip() for r in rows for v in r):
        raise ValueError('Draft values must be nonempty; use UNREADABLE if unclear')


def manifest_digest(manifest: dict) -> str:
    payload = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def load_verified(path: Path, manifest: dict) -> list[dict]:
    """Evaluator-side only; never provide this output to a candidate reader."""
    if manifest.get('manifest_sha256') != manifest_digest(manifest):
        raise ValueError('Manifest integrity check failed')
    expected = {(s['id'], str(s['page']), str(i), c) for s in manifest['scopes'] for i in range(len(s['rows'])) for c in s['columns']}
    actual = {}
    with path.open(newline='', encoding='utf-8-sig') as stream:
        for record in csv.DictReader(stream):
            key = tuple(record[k] for k in ('id', 'page', 'row_index', 'column'))
            value = record['human_value'].strip()
            if (key not in expected or key in actual or record['manifest_sha256'] != manifest['manifest_sha256']
                    or record['human_status'] != 'VERIFIED' or not value or value == 'UNREADABLE'):
                raise ValueError(f'Unverified or invalid truth cell: {key}')
            actual[key] = value
    if actual.keys() != expected:
        raise ValueError('Missing verified truth cells')
    result = []
    for s in manifest['scopes']:
        rows = [[actual[(s['id'], str(s['page']), str(i), c)] for c in s['columns']] for i in range(len(s['rows']))]
        verified = {**s, 'rows': rows}
        validate_scope(verified)
        result.append(verified)
    return result


def _image_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def build_packet(base: Path, draft: dict, pdftoppm: Path, out: Path, previous: Path | None = None) -> dict:
    scopes = draft['scopes']
    if len(scopes) != 10 or len({s['id'] for s in scopes}) != 10:
        raise ValueError('Exactly ten distinct scopes required')
    for s in scopes:
        validate_scope(s)
        if sha(base / 'source' / f"{s['id']}.pdf") != s['pdf_sha256']:
            raise ValueError(f"Changed source {s['id']}")
    prior = {}
    if previous is not None:
        old = json.loads((previous / 'manifest.json').read_text())
        if old.get('manifest_sha256') != manifest_digest(old):
            raise ValueError('Previous manifest integrity check failed')
        prior = {s['id']: s for s in old['scopes']}
    out.mkdir(exist_ok=False)
    sections, records = [], []
    for index, s in enumerate(scopes):
        prefix = out / f"{s['id']}-page-{s['page']}"
        page_path = prefix.with_suffix('.png')
        if previous is None:
            subprocess.run([str(pdftoppm), '-f', str(s['page']), '-l', str(s['page']), '-r', '300', '-png', '-singlefile', str(base / 'source' / f"{s['id']}.pdf"), str(prefix)], check=True, timeout=60)
        else:
            old_scope = prior[s['id']]
            original = previous / page_path.name
            if old_scope['pdf_sha256'] != s['pdf_sha256'] or old_scope['page'] != s['page'] or sha(original) != old_scope['render_sha256']:
                raise ValueError('Previous render provenance mismatch')
            shutil.copyfile(original, page_path)
        with Image.open(page_path) as im:
            crops = []
            for j, box in enumerate(s['boxes']):
                ow, oh = s['reference_size']
                x0, y0, x1, y1 = box
                if not (0 <= x0 < x1 <= ow and 0 <= y0 < y1 <= oh):
                    raise ValueError('Crop outside reference image')
                scaled = tuple(round(v * scale) for v, scale in zip(box, [im.width / ow, im.height / oh] * 2))
                crop = im.crop(scaled)
                crop_path = out / f"{s['id']}-crop-{j}.png"
                crop.save(crop_path)
                crops.append({'box': scaled, 'sha256': sha(crop_path), 'path': crop_path.name, 'url': _image_url(crop)})
            record = {**s, 'render_sha256': sha(page_path), 'render_size': list(im.size), 'crops': [{k: v for k, v in c.items() if k != 'url'} for c in crops]}
        records.append(record)
        headers = ''.join(f'<th>{html.escape(c)}</th>' for c in s['columns'])
        rows = ''.join('<tr data-row="%d">%s</tr>' % (i, ''.join(f'<td><input aria-label="{html.escape(c)}" data-column="{html.escape(c)}" value="{html.escape(v)}"></td>' for c,v in zip(s['columns'],row))) for i,row in enumerate(s['rows']))
        images = ''.join(f'<img src="{c["url"]}" alt="원본 표 영역 {i+1}">' for i,c in enumerate(crops))
        sections.append(f'<section hidden data-id="{s["id"]}" data-page="{s["page"]}"><h2>{index+1}. {s["id"]} · PDF {s["page"]}p</h2><p>{html.escape(s["scope"])}</p><div class="grid"><div class="source"><h3>원본 표</h3>{images}<a href="{page_path.name}" target="_blank">전체 고해상도 페이지 열기</a></div><div><h3>초안 검토</h3><p>초안은 정답이 아닙니다. 원본과 각 셀을 직접 대조해 잘못된 값과 행 이름을 수정하세요. 원문 대시는 `—`로 입력합니다.</p><div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div><label><input type="checkbox" class="verified"> 이 표 {len(s["rows"])*len(s["columns"])}개 셀을 원본과 모두 대조했습니다.</label></div></div></section>')
    manifest = {'status':'DRAFT_HUMAN_REVIEW_PENDING','scopes':records}
    manifest['manifest_sha256'] = manifest_digest(manifest)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    count = sum(len(s['rows'])*len(s['columns']) for s in scopes)
    template = Path(__file__).with_name('holdout_review.html').read_text()
    (out / 'review.html').write_text(template.replace('<!--SECTIONS-->', '\n'.join(sections)).replace('__MANIFEST_SHA__', manifest['manifest_sha256']).replace('__COUNT__', str(count)))
    return manifest
