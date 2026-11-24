"""The fixed synthetic PDF diagnostic lives outside delivery services."""
import copy
import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = 'experiments.excel_pdf.excel_pdf_pilot'


def _result():
    files = []
    for name, orientation, values, total, count in [
        ('01-monthly','portrait',[80,110,95,140],425,1),
        ('02-weekly','landscape',[12,21,18,29],80,1),
        ('03-detail','portrait',[31,48,22,55],156,3),
    ]:
        first = 'DEMO REPORT - Report\nPage 1 of '+str(count)+'\n' + '\n'.join(f'P{i} {v}' for i,v in enumerate(values,1)) + f'\nTotal {total}'
        pages = [{'a4':True,'orientation':orientation,'text':first,'chart_title':True}]
        if count == 3:
            for number,start,end in [(2,1,35),(3,36,60)]:
                text = f'DEMO REPORT - Detail\nPage {number} of 3\n' + '\n'.join(f'ITEM-{i:03d} {i+9} Zone {(i-1)%3+1}' for i in range(start,end+1))
                pages.append({'a4':True,'orientation':orientation,'text':text,'detail_header':True})
        files.append({'name':name,'pages':pages})
    return {'source_hashes_unchanged':True,'files':files}


def test_fixed_synthetic_diagnostic_accepts_exact_result():
    importlib.import_module(MODULE).check_result(_result())


@pytest.mark.parametrize('corruption', ['wrong_row','missing_pdf','orientation'])
def test_fixed_synthetic_diagnostic_rejects_corruption(corruption):
    check = importlib.import_module(MODULE).check_result
    data = copy.deepcopy(_result())
    if corruption == 'wrong_row':
        data['files'][2]['pages'][2]['text'] = data['files'][2]['pages'][2]['text'].replace('ITEM-060 69 Zone 3','ITEM-060 70 Zone 3')
    elif corruption == 'missing_pdf':
        data['files'].pop(1)
    else:
        data['files'][1]['pages'][0]['orientation'] = 'portrait'
    with pytest.raises(AssertionError):
        check(data)


def test_experiment_import_does_not_write_output(tmp_path):
    result = subprocess.run([sys.executable,'-c',f'import {MODULE}'], cwd=tmp_path,
                            env={**os.environ,'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'},
                            capture_output=True, text=True, check=True)
    assert result.stdout == result.stderr == ''
    assert list(tmp_path.iterdir()) == []
