import csv

import pytest

from src.scanned_pdf_experiment.holdout_review import load_verified, manifest_digest


def test_verified_truth_requires_all_cells_and_integrity(tmp_path):
    scope = {'id': 'H01', 'page': 1, 'columns': ['Row', 'A', 'B'],
             'rows': [[str(i), '2', '3'] for i in range(8)]}
    manifest = {'scopes': [scope]}
    manifest['manifest_sha256'] = manifest_digest(manifest)
    records = [[manifest['manifest_sha256'], 'H01', '1', str(i), c, v, 'VERIFIED']
               for i, row in enumerate(scope['rows']) for c, v in zip(scope['columns'], row)]
    path = tmp_path / 'truth.csv'

    def write(rows):
        with path.open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['manifest_sha256', 'id', 'page', 'row_index', 'column', 'human_value', 'human_status'])
            writer.writerows(rows)

    write(records)
    assert load_verified(path, manifest) == [scope]
    write(records[:-1])
    with pytest.raises(ValueError, match='Missing'):
        load_verified(path, manifest)
    write(records + records[:1])
    with pytest.raises(ValueError, match='Unverified'):
        load_verified(path, manifest)
    write(records)
    manifest['scopes'][0]['page'] = 2
    with pytest.raises(ValueError, match='integrity'):
        load_verified(path, manifest)
