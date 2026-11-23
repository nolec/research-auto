import pytest

from src.source_spike import companies_house_card_intake as intake


HEADER = 'Department Family,Entity,Date,Expense Type,Expense Area,Supplier,Amount in sterling\n'


def test_projection_keeps_only_safe_fields_and_exact_decimal():
    raw = HEADER + 'Companies House,CH,08/03/2025,Software as a Service,Private area,Private supplier,"£2,478.48"\n'
    result = intake.parse_csv(raw.encode(), '2025-03')
    assert result['records'] == [{'month': '2025-03', 'row': 1, 'date': '2025-03-08',
        'expense_type': 'Software as a Service', 'amount': '2478.48', 'currency': 'GBP'}]
    assert 'Private' not in str(result)


def test_excludes_out_of_month_nonpositive_duplicate_and_unknown_category():
    row = 'Companies House,CH,08/03/2025,Stationery,x,y,£500.01\n'
    raw = HEADER + row + row + 'Companies House,CH,28/02/2025,Stationery,x,y,£700\n' + 'Companies House,CH,09/03/2025,Stationery,x,y,-£20\n' + 'Companies House,CH,10/03/2025,Recruitment Expenses,x,y,£700\n'
    result = intake.parse_csv(raw.encode(), '2025-03')
    assert len(result['records']) == 1
    assert result['counts'] == {'rows': 5, 'retained': 1, 'duplicate': 1, 'out_of_month': 1, 'nonpositive': 1, 'category_excluded': 1}


@pytest.mark.parametrize('raw', ['Date,Amount\n1,2\n', HEADER+'Companies House,CH,08/03/2025,Stationery,x,y,garbage\n', HEADER+'Companies House,CH,08/03/2025,Stationery,x,y,£100,extra\n'])
def test_malformed_file_stops_without_partial_result(raw):
    with pytest.raises(ValueError):
        intake.parse_csv(raw.encode(), '2025-03')


def test_row_cap_enforced():
    raw = HEADER + 'Companies House,CH,08/03/2025,Stationery,x,y,£500\n'*101
    with pytest.raises(ValueError):
        intake.parse_csv(raw.encode(), '2025-03')


def test_batch_stops_on_failure_and_does_not_publish_partial_as_complete(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url)
        if len(calls) == 2:
            raise OSError('unavailable')
        return (HEADER + 'Companies House,CH,08/01/2025,Stationery,x,y,£500\n').encode()
    r = intake.run(tmp_path / 'run', fetch)
    assert r['status'] == 'INCOMPLETE'
    assert len(calls) == 2
    assert len(r['records']) == 1
    assert r['records'][0]['source_url'] == calls[0]
    with pytest.raises(FileExistsError):
        intake.run(tmp_path / 'run', fetch)
