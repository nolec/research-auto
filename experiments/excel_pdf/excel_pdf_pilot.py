"""Fixed synthetic conversion diagnostic; not a customer-file ingestion tool."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ET.register_namespace('', NS)
ET.register_namespace('r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')


def q(tag):
    return f'{{{NS}}}{tag}'


SPECS = {
    '01-monthly': [('Report', 'portrait', 'A1:D24')],
    '02-weekly': [('Report', 'landscape', 'A1:I17')],
    '03-detail': [('Report', 'portrait', 'A1:D24'), ('Detail', 'portrait', 'A1:C61')],
}

EXPECTED_VALUES = {'01-monthly': [80,110,95,140], '02-weekly': [12,21,18,29], '03-detail': [31,48,22,55]}


def check_result(result):
    """Require exact fixture-specific output, not just presence of PDF files."""
    assert result['source_hashes_unchanged']
    assert {f['name'] for f in result['files']} == set(SPECS)
    for f in result['files']:
        name = f['name']
        pages = f['pages']
        assert len(pages) == (3 if name == '03-detail' else 1), name
        for i, page in enumerate(pages, 1):
            assert page['a4'] and page['orientation'] == SPECS[name][0][1], (name, i)
            assert f'DEMO REPORT - {"Report" if i == 1 else "Detail"}' in page['text'], (name, i)
            assert f'Page {i} of {len(pages)}' in page['text'], (name, i)
        first = pages[0]['text']
        values = EXPECTED_VALUES[name]
        assert re.findall(r'^P([1-4]) (\d+)$', first, re.M) == [(str(i), str(v)) for i,v in enumerate(values, 1)], name
        assert f'Total {sum(values)}' in first.splitlines(), name
        assert pages[0]['chart_title'], name
        if name == '03-detail':
            assert all(p['detail_header'] for p in pages[1:]), name
            detail = '\n'.join(p['text'] for p in pages[1:])
            assert re.findall(r'^ITEM-(\d{3}) (\d+) Zone (\d)$', detail, re.M) == [(f'{i:03d}', str(i+9), str((i-1)%3+1)) for i in range(1,61)], name


def prepare(src, dst, specs):
    # Only print metadata is missing from the fixture authoring API. Preserve all
    # other archive entries, including native chart data and drawings, byte-for-byte.
    with ZipFile(src) as zi, ZipFile(dst, 'x') as zo:
        for item in zi.infolist():
            data = zi.read(item.filename)
            if item.filename == 'xl/workbook.xml':
                root = ET.fromstring(data)
                names = ET.SubElement(root, q('definedNames'))
                for i, (sheet, _, area) in enumerate(specs):
                    start, end = area.split(':')
                    absolute = lambda c: f'${c[0]}${c[1:]}'
                    ET.SubElement(names, q('definedName'), name='_xlnm.Print_Area', localSheetId=str(i)).text = f"'{sheet}'!{absolute(start)}:{absolute(end)}"
                    if sheet == 'Detail':
                        ET.SubElement(names, q('definedName'), name='_xlnm.Print_Titles', localSheetId=str(i)).text = "'Detail'!$1:$1"
                data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            for i, (sheet, orient, _) in enumerate(specs, 1):
                if item.filename != f'xl/worksheets/sheet{i}.xml':
                    continue
                root = ET.fromstring(data)
                props = ET.Element(q('sheetPr'))
                ET.SubElement(props, q('pageSetUpPr'), fitToPage='1')
                root.insert(0, props)
                margins = root.find(q('pageMargins'))
                margins.attrib.update(left='0.5', right='0.5', top='0.75', bottom='0.75', header='0.3', footer='0.3')
                k = list(root).index(margins) + 1
                root.insert(k, ET.Element(q('pageSetup'), paperSize='9', orientation=orient, fitToWidth='1', fitToHeight='0' if sheet == 'Detail' else '1'))
                hf = ET.Element(q('headerFooter'))
                ET.SubElement(hf, q('oddHeader')).text = f'&LDEMO REPORT - {sheet}'
                ET.SubElement(hf, q('oddFooter')).text = '&RPage &P of &N'
                root.insert(k+1, hf)
                data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            zo.writestr(item, data)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(raw, out, native):
    from pypdf import PdfReader
    start = time.perf_counter()
    inp = out / 'input'
    pdf = out / 'pdf'
    inp.mkdir(parents=True, exist_ok=False)
    pdf.mkdir()
    expected = {name: specs for name, specs in SPECS.items()}
    for name, specs in expected.items():
        prepare(raw / f'{name}.xlsx', inp / f'{name}.xlsx', specs)
    sources = sorted(inp.glob('*.xlsx'))
    before = {p.name: digest(p) for p in sources}
    soffice = native / 'libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/MacOS/soffice'
    with tempfile.TemporaryDirectory(prefix='excel-pdf-profile-') as profile:
        t = time.perf_counter()
        run = subprocess.run([str(soffice), f'-env:UserInstallation={Path(profile).as_uri()}', '--headless', '--convert-to', 'pdf:calc_pdf_Export', '--outdir', str(pdf), *map(str,sources)], capture_output=True, text=True, timeout=90, check=True)
        conversion = time.perf_counter() - t
    verify_start = time.perf_counter()
    assert sorted(p.stem for p in pdf.glob('*.pdf')) == sorted(expected), run.stdout + run.stderr
    assert before == {p.name: digest(p) for p in sources}, 'source changed'
    checks = []
    for name, specs in expected.items():
        result = PdfReader(pdf / f'{name}.pdf')
        pages = []
        all_text = []
        for i, page in enumerate(result.pages):
            content = page.extract_text()
            all_text.append(content)
            w, h = map(float, (page.mediabox.width, page.mediabox.height))
            page_size = sorted((w,h))
            pages.append({'size_pt': [w,h], 'a4': abs(page_size[0]-595.28)<2 and abs(page_size[1]-841.89)<2, 'orientation': 'landscape' if w>h else 'portrait', 'header': 'DEMO REPORT' in content, 'footer': 'Page' in content, 'chart_title': 'Units by period' in content, 'detail_header': 'Item' in content and 'Quantity' in content, 'text': content})
        full = '\n'.join(all_text)
        checks.append({'name': name, 'pages': pages, 'expected_pages': 3 if name == '03-detail' else 1, 'expected_orientation': specs[0][1], 'expected_total_found': str({'01-monthly':425,'02-weekly':80,'03-detail':156}[name]) in all_text[0], 'detail_rows_found': sum(f'ITEM-{i:03d}' in full for i in range(1,61)) if name=='03-detail' else None})
    return {'conversion_seconds': conversion, 'automated_qa_seconds': time.perf_counter()-verify_start, 'prepare_and_conversion_and_qa_seconds': time.perf_counter()-start, 'source_hashes_unchanged': True, 'sources': before, 'files': checks, 'stdout': run.stdout, 'stderr': run.stderr}


if __name__ == '__main__':
    raw, out, native = map(lambda p: Path(p).resolve(), sys.argv[1:])
    result = execute(raw, out, native)
    check_result(result)
    (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
