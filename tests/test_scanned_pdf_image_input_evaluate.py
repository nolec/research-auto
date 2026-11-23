import csv
import json

import pytest

from scripts.scanned_pdf_image_input_evaluate import load_truth, evaluate
from src.scanned_pdf_experiment.holdout_review import manifest_digest, sha


def fixture(tmp_path):
    (tmp_path/'reviewer').mkdir();(tmp_path/'candidate-images').mkdir()
    cells=[];truth={}
    for i in range(8):
        for j in range(3):
            token=f'{i}-{j}';p=tmp_path/'candidate-images'/f'{token}.png';p.write_bytes(token.encode())
            cells.append({'id':token,'row':i,'column':j,'crop_sha256':sha(p)});truth[token]=str(100+i*10+j)
    manifest={'scopes':[{'id':'N01','cells':cells}]};manifest['manifest_sha256']=manifest_digest(manifest)
    (tmp_path/'reviewer/manifest.json').write_text(json.dumps(manifest))
    csv_path=tmp_path/'truth.csv'
    with csv_path.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['manifest_sha256','id','human_value','human_status']);w.writerows([manifest['manifest_sha256'],k,v,'VERIFIED'] for k,v in truth.items())
    read=tmp_path/'reads.json';read.write_text(json.dumps({'reads':truth}))
    return manifest,csv_path,read


def test_perfect_image_reads(tmp_path):
    manifest,truth,reads=fixture(tmp_path);result=evaluate(tmp_path,truth,reads)
    assert (result['tp'],result['fp'],result['fn'],result['exact'])==(3,0,0,24)
    assert result['thresholds_met']


def test_incomplete_truth_rejected(tmp_path):
    manifest,truth,reads=fixture(tmp_path);lines=truth.read_text().splitlines();truth.write_text('\n'.join(lines[:-1]))
    with pytest.raises(ValueError,match='Incomplete truth'):load_truth(truth,manifest)


def test_changed_candidate_crop_rejected(tmp_path):
    manifest,truth,reads=fixture(tmp_path);(tmp_path/'candidate-images/0-0.png').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Candidate image changed'):evaluate(tmp_path,truth,reads)


def test_context_packet_integrity(tmp_path):
    manifest,truth,reads=fixture(tmp_path)
    image=tmp_path/'candidate-images/context.png';image.write_bytes(b'context')
    old=manifest['manifest_sha256'];manifest['stratum']='CONTEXT_PAGE_HOLDOUT_SHARED_SOURCE_PDFS'
    manifest['scopes'][0].update(context_image=image.name,context_sha256=sha(image))
    manifest['manifest_sha256']=manifest_digest(manifest)
    (tmp_path/'reviewer/manifest.json').write_text(json.dumps(manifest))
    truth.write_text(truth.read_text().replace(old,manifest['manifest_sha256']))
    assert evaluate(tmp_path,truth,reads)['tp']==3
    image.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Candidate context image changed'):evaluate(tmp_path,truth,reads)
