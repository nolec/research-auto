import csv
import pytest

from src.spreadsheet_pilot import reconcile, export_review_package


def test_every_source_row_accounted_for(tmp_path):
    a, b = tmp_path/'a.csv', tmp_path/'b.csv'
    a.write_text('id,quantity\n001,4\n002,5\n003,0\n', encoding='utf-8')
    b.write_text('id,quantity\n001,4\n002,8\n,7\n004,9\n', encoding='utf-8')
    r = reconcile([a, b], 'id')
    assert r['input_count'] == 7
    assert [e['values'] for e in r['accepted']] == [['001','4'], ['003','0'], ['004','9']]
    assert len(r['duplicates']) == 1
    assert len(r['exceptions']) == 3
    assert {e['reason'] for e in r['exceptions']} == {'missing_key', 'conflicting_key'}
    assert r['status'] == 'REQUIRES_HUMAN_REVIEW'


@pytest.mark.parametrize('content', ['id,qty\n1,=2+2\n','id,qty\n1,2,3\n','id,id\n1,2\n'])
def test_reject_out_of_scope(tmp_path, content):
    p = tmp_path/'a.csv'
    p.write_text(content, encoding='utf-8')
    with pytest.raises(ValueError):
        reconcile([p], 'id')


def test_mismatched_schema(tmp_path):
    a, b = tmp_path/'a.csv', tmp_path/'b.csv'
    a.write_text('id,qty\n1,2\n')
    b.write_text('qty,id\n2,1\n')
    with pytest.raises(ValueError):
        reconcile([a,b], 'id')


def test_bounded_thousand_row_case(tmp_path):
    a, b = tmp_path/'a.csv', tmp_path/'b.csv'
    a.write_text('id,qty\n' + ''.join(f'{i:04d},2\n' for i in range(900)))
    b.write_text('id,qty\n' + ''.join(f'{i:04d},2\n' for i in range(50))
                 + ''.join(f'{i:04d},3\n' for i in range(50,100)))
    r = reconcile([a,b], 'id')
    assert r['input_count'] == 1000
    assert (len(r['accepted']), len(r['duplicates']), len(r['exceptions'])) == (850,50,100)
    out = tmp_path/'result'
    export_review_package(r, out)
    for filename, expected in [('clean-draft.csv',850), ('duplicates.csv',50), ('unresolved.csv',100)]:
        with (out/filename).open(encoding='utf-8-sig', newline='') as f:
            assert len(list(csv.reader(f))) == expected+1
    with (out/'clean-draft.csv').open(encoding='utf-8-sig', newline='') as f:
        assert list(csv.reader(f))[1] == ['0000','2']
    with pytest.raises(FileExistsError):
        export_review_package(r, out)


def test_simple_xlsx_input_and_generic_output(tmp_path):
    xl = pytest.importorskip('openpyxl')
    paths = []
    for name, rows in [('a', [('0001', 2), ('0002', 3), ('0003', 0)]),
                       ('b', [('0001', 2), ('0002', 4), (None, 9)])]:
        w = xl.Workbook(); s = w.active; s.title = 'stock'
        s.append(['code','qty'])
        for row in rows: s.append(row)
        p = tmp_path/f'{name}.xlsx'; w.save(p); paths.append(p)
    r = reconcile(paths, 'code')
    assert [len(r[k]) for k in ('accepted','duplicates','exceptions')] == [2,1,3]
    out = tmp_path/'order'; export_review_package(r, out, xlsx=True)
    w = xl.load_workbook(out/'delivery-draft.xlsx', data_only=True)
    assert list(w['정리 결과'].values) == [('code','qty'), ('0001',2), ('0003',0)]
    assert list(w['중복 기록'].values)[1] == (2,2,'exact_duplicate','0001',2)
    assert set(list(w['확인 필요'].values)[1:]) == {(1,3,'conflicting_key','0002',3),(2,3,'conflicting_key','0002',4),(2,4,'missing_key',None,9)}
    assert len(list(w['원본 행 기록'].values)) == 7
    assert w['정리 결과']['A2'].data_type == 's'


@pytest.mark.parametrize('kind',['formula','multiple_sheets','merged','formatted_numeric_id'])
def test_reject_unsupported_xlsx(tmp_path, kind):
    xl = pytest.importorskip('openpyxl')
    w=xl.Workbook(); s=w.active; s.append(['code','qty']); s.append(['0001',2])
    if kind=='formula': s['B2']='=1+1'
    if kind=='multiple_sheets': w.create_sheet('another')
    if kind=='merged': s.merge_cells('A2:B2')
    if kind=='formatted_numeric_id': s['A2']=1; s['A2'].number_format='0000'
    p=tmp_path/'bad.xlsx'; w.save(p)
    with pytest.raises(ValueError): reconcile([p],'code')


def test_generic_csv_xlsx_export_keeps_zero_padded_text(tmp_path):
    xl=pytest.importorskip('openpyxl')
    p=tmp_path/'a.csv'; p.write_text('SKU,name,quantity\n0001,clip,0\n0002,pen,4\n')
    r=reconcile([p],'SKU'); out=tmp_path/'out'; export_review_package(r,out,xlsx=True)
    w=xl.load_workbook(out/'delivery-draft.xlsx'); assert list(w['정리 결과'].values)==[('SKU','name','quantity'),('0001','clip','0'),('0002','pen','4')]


def test_export_rejects_excel_cell_overflow_before_creating_package(tmp_path):
    pytest.importorskip('openpyxl')
    p=tmp_path/'a.csv'; p.write_text('id,note\n1,'+'x'*32768+'\n')
    r=reconcile([p],'id'); out=tmp_path/'out'
    with pytest.raises(ValueError, match='cell length'):
        export_review_package(r,out,xlsx=True)
    assert not out.exists()


def test_full_scope_three_xlsx_files_1000_rows_20_columns(tmp_path):
    xl=pytest.importorskip('openpyxl')
    import subprocess, sys
    paths=[]
    header=['id', *[f'field{i}' for i in range(1,20)]]
    cases=[[(i,2) for i in range(600)],[(i,2) for i in range(600,900)],
           [(i,2) for i in range(50)]+[(i,3) for i in range(50,100)]]
    for idx, records in enumerate(cases):
        book=xl.Workbook(); s=book.active; s.append(header)
        for i,v in records: s.append([f'{i:04d}', v, *['내용']*18])
        p=tmp_path/f'{idx}.xlsx'; book.save(p); paths.append(p)
    out=tmp_path/'order'
    result=subprocess.run([sys.executable,'-m','src.spreadsheet_pilot','--key','id','--xlsx','--output',str(out),*map(str,paths)],capture_output=True,text=True,check=True)
    assert '850' in result.stdout
    w=xl.load_workbook(out/'delivery-draft.xlsx',data_only=True)
    assert [w[s].max_row-1 for s in ('정리 결과','중복 기록','확인 필요','원본 행 기록')]==[850,50,100,1000]
    assert list(w['정리 결과'].values)[1]==('0000',2,*['내용']*18)
    assert w['정리 결과'].max_column==20
    assert {r[3] for r in list(w['확인 필요'].values)[1:]}=={f'{i:04d}' for i in range(50,100)}
    # Independent fixture oracle: every original value, coordinate and category.
    expected=[]
    for source, records in enumerate(cases,1):
        for row,(i,v) in enumerate(records,2):
            reason='conflicting_key' if 50<=i<100 else 'exact_duplicate' if source==3 else 'accepted'
            expected.append((source,row,reason,f'{i:04d}',v,*['내용']*18))
    assert list(w['원본 행 기록'].values)[1:]==expected
    assert list(w['정리 결과'].values)[1:]==[r[3:] for r in expected if r[2]=='accepted']
    for name, reason in [('중복 기록','exact_duplicate'),('확인 필요','conflicting_key')]:
        assert set(list(w[name].values)[1:])=={r for r in expected if r[2]==reason}
