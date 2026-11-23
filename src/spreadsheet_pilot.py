"""Small, local reconciliation pilot for matched CSV or simple XLSX schemas.

No inference, data uploads, formula execution, or automatic conflict resolution.
Customer delivery still requires human review.
"""
import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile


def _read_rows(path, data):
    if path.suffix.lower() == '.csv':
        reader = csv.reader(data.decode('utf-8-sig').splitlines(keepends=True), strict=True)
        columns = next(reader, [])
        return columns, ((reader.line_num, row, row) for row in reader), None
    from openpyxl import load_workbook
    with ZipFile(BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > 100 or sum(x.file_size for x in members) > 20_000_000:
            raise ValueError('XLSX expanded size outside scope')
        if any(x.filename.startswith(('xl/externalLinks/', 'xl/vbaProject')) for x in members):
            raise ValueError('External links or macros outside scope')
    workbook = load_workbook(BytesIO(data), data_only=False, keep_links=False)
    try:
        if len(workbook.worksheets) != 1:
            raise ValueError('Only one worksheet per XLSX is supported')
        sheet = workbook.active
        if sheet.merged_cells.ranges or sheet.max_row > 1001 or sheet.max_column > 20:
            raise ValueError('Merged or oversized XLSX outside scope')
        rows = list(sheet.iter_rows())
        columns = [c.value for c in rows[0]]
        if any(not isinstance(c, str) for c in columns):
            raise ValueError('Headers must be text')
        result = []
        for n, cells in enumerate(rows[1:], 2):
            typed = []
            for c in cells:
                value = c.value
                if c.data_type in ('f', 'e') or type(value) not in (str, int, float, type(None)):
                    raise ValueError('Formula, error or unsupported cell type')
                if type(value) in (int, float) and (c.number_format != 'General' or not math.isfinite(value)):
                    raise ValueError('Formatted numeric values require manual review')
                typed.append(value)
            result.append((n, ['' if v is None else str(v) for v in typed], typed))
        return columns, result, sheet.title
    finally:
        workbook.close()


def reconcile(paths, key):
    if not 1 <= len(paths) <= 3 or len({p.resolve() for p in paths}) != len(paths):
        raise ValueError('Provide 1–3 distinct files')
    headers, records, groups, exceptions, duplicates, accepted, sources = None, [], defaultdict(list), [], [], [], []
    for index, path in enumerate(paths, 1):
        if path.suffix.lower() not in ('.csv', '.xlsx') or path.stat().st_size > 2_000_000:
            raise ValueError('Only CSV or XLSX files up to 2 MB are supported')
        data = path.read_bytes()
        columns, rows, sheet = _read_rows(path, data)
        sources.append({'source': index, 'name': path.name, 'sheet': sheet, 'sha256': hashlib.sha256(data).hexdigest()})
        if (not 1 <= len(columns) <= 20 or len(set(columns)) != len(columns)
                or any(not c.strip() or c.lstrip().startswith(('=', '+', '-', '@')) for c in columns)
                or key not in columns):
            raise ValueError('Invalid headers or missing key')
        if headers is not None and columns != headers:
            raise ValueError('Column order and names must match exactly')
        headers = columns
        key_index = headers.index(key)
        for line, row, typed in rows:
            if len(records) >= 1000 or len(row) != len(headers):
                raise ValueError('Row count or width outside agreed scope')
            # Do not deliver formula-like text into a spreadsheet as executable formula.
            if any(v.lstrip().startswith(('=', '+', '@')) or (v.lstrip().startswith('-') and not v.lstrip()[1:].replace('.', '', 1).isdigit()) for v in row):
                raise ValueError('Formula-like text requires separate manual handling')
            entry = {'source': index, 'line_end': line, 'values': row, 'typed': typed}
            records.append(entry)
            if not row[key_index].strip():
                exceptions.append({**entry, 'reason': 'missing_key'})
            else:
                groups[row[key_index]].append(entry)
    for entries in groups.values():
        if len({tuple((type(v).__name__,v) for v in e['typed']) for e in entries}) != 1:
            exceptions.extend({**e, 'reason': 'conflicting_key'} for e in entries)
        else:
            accepted.append(entries[0])
            duplicates.extend({**e, 'reason': 'exact_duplicate'} for e in entries[1:])
    assert len(records) == len(accepted) + len(exceptions) + len(duplicates)
    return {'headers': headers, 'key': key, 'sources': sources, 'accepted': accepted,
            'duplicates': duplicates, 'exceptions': exceptions, 'input_count': len(records),
            'status': 'REQUIRES_HUMAN_REVIEW'}


def _export_xlsx(result, destination, *, report_summary=False):
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    w = Workbook(); summary = w.active; summary.title = '검수 요약'
    counts = [len(result[k]) for k in ('accepted','duplicates','exceptions')]
    summary.append(['검수 상태','사람 확인 필요']); summary.append(['원본 행',result['input_count']]);
    for v, count in zip(('정리 결과','완전 중복','확인 필요'),counts): summary.append([v,count])
    summary.append(['미분류 행',result['input_count']-sum(counts)])
    header = result['headers']; expected = {}
    metadata = ['audit_source','audit_line_end','audit_reason']
    def add(name, headings, rows):
        s=w.create_sheet(name); expected[name]=[headings,*rows]
        for row in expected[name]:
            s.append(row)
            for c in s[s.max_row]:
                if isinstance(c.value,str): c.data_type='s'; c.number_format='@'
        for c in s[1]: c.fill=PatternFill('solid',fgColor='253B55'); c.font=Font(color='FFFFFF',bold=True)
        s.freeze_panes='A2'; s.auto_filter.ref=s.dimensions
        for i in range(1,len(headings)+1): s.column_dimensions[get_column_letter(i)].width=min(45,max(12,len(str(headings[i-1]))+4))
    add('정리 결과',header,[e['typed'] for e in result['accepted']])
    for name, key in [('중복 기록','duplicates'),('확인 필요','exceptions')]:
        add(name,metadata+header,[[e['source'],e['line_end'],e['reason'],*e['typed']] for e in result[key]])
    all_rows=sorted([(e['source'],e['line_end'],e.get('reason','accepted'),*e['typed']) for k in ('accepted','duplicates','exceptions') for e in result[k]],key=lambda r:r[:2])
    add('원본 행 기록',metadata+header,[list(r) for r in all_rows])
    add('원본 파일',['source','filename','worksheet','sha256'],[[s['source'],s['name'],s['sheet'],s['sha256']] for s in result['sources']])
    summary.column_dimensions['A'].width=24; summary.column_dimensions['B'].width=25
    if report_summary:
        sheet = w.create_sheet('기간별 실적', 0)
        rows = [['집계 주기',result['frequency'],None,None,None], ['검수 상태','사람 확인 필요',None,None,None],
                ['기간','구분','분류','반영 행 수','수량']]
        for period, item in result['summary'].items():
            rows.append([period,'합계',None,item['rows'],item['total']])
            rows.extend([period,'분류',category,None,quantity] for category,quantity in sorted(item['categories'].items()))
        if not result['summary']:
            rows.append(['반영 가능한 데이터 없음',None,None,None,None])
        expected[sheet.title]=rows
        for row in rows:
            sheet.append(row)
            for c in sheet[sheet.max_row]:
                if isinstance(c.value,str): c.data_type='s'; c.number_format='@'
        for c in sheet[3]: c.fill=PatternFill('solid',fgColor='253B55'); c.font=Font(color='FFFFFF',bold=True)
        for i,width in enumerate((28,16,40,16,20),1): sheet.column_dimensions[get_column_letter(i)].width=width
        for row in sheet.iter_rows(min_row=4,min_col=4,max_col=5):
            for cell in row:
                if isinstance(cell.value,int): cell.number_format='#,##0'
        for row in sheet.iter_rows(min_row=4):
            if row[1].value=='합계':
                for cell in row: cell.fill=PatternFill('solid',fgColor='EAF0F5'); cell.font=Font(bold=True,color='253B55')
        sheet.freeze_panes='A4'; w.active=0
    w.save(destination)
    reopened=load_workbook(destination,data_only=True)
    try:
        for name, rows in expected.items():
            normalized=[tuple(None if v=='' else v for v in row) for row in rows]
            if list(reopened[name].values)!=normalized:
                raise ValueError(f'XLSX round-trip mismatch: {name}')
        if len({(r[0],r[1]) for r in all_rows})!=result['input_count']:
            raise ValueError('Duplicate or missing source coordinates')
    finally: reopened.close()


def export_review_package(result, directory, *, xlsx=False, report_summary=False):
    """Provisional CSVs; reviewer must check before customer delivery."""
    if xlsx:
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
        strings = [*result['headers'], *(v for k in ('accepted','duplicates','exceptions') for e in result[k] for v in e['typed'] if isinstance(v,str))]
        if any(len(s)>32767 for s in strings):
            raise ValueError('XLSX cell length outside scope')
        if any(ILLEGAL_CHARACTERS_RE.search(s) for s in strings):
            raise ValueError('XLSX control character outside scope')
    directory.mkdir(exist_ok=False)
    headers = result['headers']
    for name, key in [('clean-draft.csv', 'accepted'), ('duplicates.csv', 'duplicates'), ('unresolved.csv', 'exceptions')]:
        with (directory/name).open('x', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            if key == 'accepted':
                writer.writerow(headers)
                writer.writerows(e['values'] for e in result[key])
            else:
                writer.writerow(['audit_source', 'audit_line_end', 'audit_reason'] + ['data:'+h for h in headers])
                writer.writerows([e['source'], e['line_end'], e['reason'], *e['values']] for e in result[key])
    with (directory/'review.json').open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    if xlsx:
        _export_xlsx(result, directory/'delivery-draft.xlsx', report_summary=report_summary)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--key', required=True)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--xlsx', action='store_true')
    p.add_argument('files', nargs='+', type=Path)
    a = p.parse_args()
    result = reconcile(a.files, a.key)
    export_review_package(result, a.output, xlsx=a.xlsx)
    print(json.dumps({k: len(result[k]) for k in ['accepted', 'duplicates', 'exceptions']}))


if __name__ == '__main__':
    main()
