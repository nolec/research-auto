import csv
import importlib.util
import json
import subprocess
import sys

import pytest

from src.spreadsheet_pilot import reconcile, export_review_package


def build(paths, **overrides):
    assert importlib.util.find_spec('src.periodic_report') is not None, 'report module missing'
    from src.periodic_report import build_report
    options = dict(key='id', date_field='day', category_field='group', quantity_field='qty', frequency='monthly')
    return build_report(paths, **(options | overrides))


def write_csv(tmp_path, name, rows, headers=('id','day','group','qty')):
    path = tmp_path / name
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f); w.writerow(headers); w.writerows(rows)
    return path


@pytest.fixture
def inputs(tmp_path):
    return [write_csv(tmp_path,'a.csv',[
        ('001','2026-09-01','A','4'),('002','2026-09-02','B','7'),('003','2026-09-03','A','3'),('conflict','2026-09-05','X','99')]),
        write_csv(tmp_path,'b.csv',[
        ('004','2026-10-01','A','8'),('005','2026-10-02','B','5'),('006','2026-10-03','A','4'),('001','2026-09-01','A','4'),
        ('conflict','2026-10-05','X','100'),('','2026-10-06','X','55'),('bad-date','2026-02-30','X','55'),
        ('bad-qty','2026-10-07','X','unknown'),('bad-cat','2026-10-08','','55')])]


def test_final_dispositions_match_monthly_totals(inputs):
    r = build(inputs)
    assert [len(r[k]) for k in ('accepted','duplicates','exceptions')] == [6,1,6]
    assert r['input_count'] == 13
    assert r['summary'] == {'2026-09':{'total':14,'rows':3,'categories':{'A':7,'B':7}}, '2026-10':{'total':17,'rows':3,'categories':{'A':12,'B':5}}}
    assert {(e['source'],e['line_end'],e['reason']) for e in r['exceptions']} == {(1,5,'conflicting_key'),(2,6,'conflicting_key'),(2,7,'missing_key'),(2,8,'invalid_date'),(2,9,'invalid_quantity'),(2,10,'missing_category')}
    assert [len(reconcile(inputs,'id')[k]) for k in ('accepted','duplicates','exceptions')] == [9,1,3]


def test_week_boundary_and_zero(tmp_path):
    p=write_csv(tmp_path,'a.csv',[('001','2026-09-06',' A ','0'),('002','2026-09-07','A','2')])
    assert build([p],frequency='weekly')['summary'] == {'2026-08-31':{'total':0,'rows':1,'categories':{'A':0}},'2026-09-07':{'total':2,'rows':1,'categories':{'A':2}}}


def test_all_held_and_conflict_precedence(tmp_path):
    p=write_csv(tmp_path,'a.csv',[('001','bad','A','1'),('001','2026-09-01','A','1'),('002','2026-09-01','A','-1')])
    r=build([p]); assert r['summary']=={}; assert not r['accepted']
    assert [e['reason'] for e in r['exceptions']]==['conflicting_key','conflicting_key','invalid_quantity']


@pytest.mark.parametrize('options',[{'quantity_field':'missing'},{'quantity_field':'day'},{'frequency':'daily'}])
def test_reject_bad_configuration(inputs, options):
    with pytest.raises(ValueError): build(inputs,**options)


def test_reject_16_columns(tmp_path):
    h=['id','day','group','qty']+[f'extra{i}' for i in range(12)]
    p=write_csv(tmp_path,'a.csv',[('001','2026-09-01','A','1',*['x']*12)],h)
    with pytest.raises(ValueError): build([p])


@pytest.mark.parametrize('quantities',[['1000000000000000'],['999999999999999','1']])
def test_reject_unsafe_excel_integer(tmp_path, quantities):
    p=write_csv(tmp_path,'a.csv',[(str(i),'2026-09-01','A',q) for i,q in enumerate(quantities)])
    with pytest.raises(ValueError): build([p])


def test_export_matches_final_report(inputs, tmp_path):
    xl=pytest.importorskip('openpyxl')
    import src.periodic_report as module
    assert hasattr(module,'export_report_package'), 'integrated export missing'
    out=tmp_path/'report'; module.export_report_package(build(inputs),out)
    with (out/'review.json').open() as f:
        r=json.load(f)
    assert [len(r[k]) for k in ('accepted','duplicates','exceptions')]==[6,1,6]
    with (out/'unresolved.csv').open(encoding='utf-8-sig') as f:
        assert len(list(csv.reader(f)))==7
    with (out/'clean-draft.csv').open(encoding='utf-8-sig') as f:
        assert len(list(csv.reader(f)))==7
    w=xl.load_workbook(out/'delivery-draft.xlsx',data_only=True)
    try:
        assert w.sheetnames[0]=='기간별 실적'
        assert list(w['기간별 실적'].values)==[('집계 주기','monthly',None,None,None),('검수 상태','사람 확인 필요',None,None,None),('기간','구분','분류','반영 행 수','수량'),('2026-09','합계',None,3,14),('2026-09','분류','A',None,7),('2026-09','분류','B',None,7),('2026-10','합계',None,3,17),('2026-10','분류','A',None,12),('2026-10','분류','B',None,5)]
        assert [w[s].max_row-1 for s in ('정리 결과','중복 기록','확인 필요','원본 행 기록')]==[6,1,6,13]
        assert {(row[0],row[1],row[2]) for row in list(w['확인 필요'].values)[1:]}=={(1,5,'conflicting_key'),(2,6,'conflicting_key'),(2,7,'missing_key'),(2,8,'invalid_date'),(2,9,'invalid_quantity'),(2,10,'missing_category')}
    finally: w.close()
    with pytest.raises(FileExistsError): module.export_report_package(build(inputs),out)
    generic=tmp_path/'generic';export_review_package(reconcile(inputs,'id'),generic,xlsx=True)
    w=xl.load_workbook(generic/'delivery-draft.xlsx',data_only=True)
    try: assert '기간별 실적' not in w.sheetnames
    finally: w.close()


def test_all_held_export_explicit_no_data(tmp_path):
    xl=pytest.importorskip('openpyxl')
    import src.periodic_report as module
    assert hasattr(module,'export_report_package')
    p=write_csv(tmp_path,'a.csv',[('001','bad','A','1')]); out=tmp_path/'result'
    module.export_report_package(build([p]),out)
    w=xl.load_workbook(out/'delivery-draft.xlsx',data_only=True)
    try: assert list(w['기간별 실적'].values)[3:]==[('반영 가능한 데이터 없음',None,None,None,None)]
    finally: w.close()


def test_cli_rejects_bad_mapping_without_output(inputs,tmp_path):
    out=tmp_path/'result'
    args=[sys.executable,'-m','src.periodic_report','--key','id','--date-field','day','--category-field','group','--quantity-field','absent','--frequency','monthly','--output',str(out),*map(str,inputs)]
    r=subprocess.run(args,capture_output=True,text=True)
    assert r.returncode!=0 and 'Report requires mapped fields' in r.stderr
    assert not out.exists()


def test_cli_creates_integrated_export(inputs,tmp_path):
    pytest.importorskip('openpyxl')
    out=tmp_path/'result'
    args=[sys.executable,'-m','src.periodic_report','--key','id','--date-field','day','--category-field','group','--quantity-field','qty','--frequency','monthly','--output',str(out),*map(str,inputs)]
    r=subprocess.run(args,capture_output=True,text=True,check=True)
    assert json.loads(r.stdout)=={'accepted':6,'duplicates':1,'exceptions':6}
    assert (out/'delivery-draft.xlsx').is_file()


def test_real_category_named_total_distinct_from_subtotal(tmp_path):
    xl=pytest.importorskip('openpyxl')
    from src.periodic_report import export_report_package
    p=write_csv(tmp_path,'a.csv',[('001','2026-09-01','전체','5'),('002','2026-09-02','합계','3')])
    out=tmp_path/'result'; export_report_package(build([p]),out)
    w=xl.load_workbook(out/'delivery-draft.xlsx',data_only=True)
    try: assert list(w['기간별 실적'].values)[3:]==[('2026-09','합계',None,2,8),('2026-09','분류','전체',None,5),('2026-09','분류','합계',None,3)]
    finally: w.close()
