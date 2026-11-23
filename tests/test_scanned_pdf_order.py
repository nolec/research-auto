import pytest
from src.scanned_pdf_experiment.order import grid_cells, validated_rows


def test_grid_geometry_and_limit():
    manifest = {'pages': [{'page': 4, 'width': 500, 'height': 400}]}
    cells = grid_cells(manifest, [{'page': 4, 'xs': [10, 20, 30], 'ys': [40, 50, 60]}])
    assert len(cells) == 4 and cells[-1]['box'] == [20, 50, 30, 60]
    assert cells[-1]['id'] == 'P4R2C2'
    for bad in ([0, 0], [-1, 10], [1, 501], [1, 2.5]):
        with pytest.raises(ValueError):
            grid_cells(manifest, [{'page': 4, 'xs': bad, 'ys': [0, 2]}])
    with pytest.raises(ValueError):
        grid_cells(manifest, [{'page': 4, 'xs': list(range(12)), 'ys': list(range(12))}])


def test_review_requires_all_cells_and_bound_packet():
    packet = {'cells': [{'id': 'a'}, {'id': 'b'}]}
    response = {'packet': 'hash', 'responses': {'a': {'status': 'confirmed', 'value': '1,234'}, 'b': {'status': 'unreadable', 'value': ''}}}
    rows = validated_rows(packet, response, 'hash')
    assert rows[0]['final'] == 1234 and rows[1]['final'] is None
    with pytest.raises(ValueError):
        validated_rows(packet, response, 'other')
    response['responses']['a']['value'] = '=1+1'
    with pytest.raises(ValueError):
        validated_rows(packet, response, 'hash')
    response['responses'].pop('a')
    with pytest.raises(ValueError):
        validated_rows(packet, response, 'hash')


def test_unreadable_cannot_silently_contain_number():
    with pytest.raises(ValueError):
        validated_rows({'cells': [{'id': 'a'}]}, {'packet': 'x', 'responses': {'a': {'status': 'unreadable', 'value': '100'}}}, 'x')
