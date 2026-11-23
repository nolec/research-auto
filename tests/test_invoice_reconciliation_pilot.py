import pytest

from src.invoice_reconciliation_pilot import reconcile


def test_exact_matches_partial_unpaid_overpaid_and_unmatched():
    invoices = 'invoice_id,amount,currency\n0001,10.00,USD\n0002,20.00,USD\n0003,30.00,USD\n0004,40.00,USD\n'
    payments = 'payment_id,invoice_id,amount,currency\nP1,0001,3.00,USD\nP2,0001,7.00,USD\nP3,0002,8.00,USD\nP4,0004,45.00,USD\nP5,0009,12.00,USD\n'
    r = reconcile(invoices, payments)
    assert [(x['invoice_id'], x['state'], x['balance']) for x in r['invoices']] == [
        ('0001', 'matched', '0.00'), ('0002', 'partial', '12.00'), ('0003', 'unpaid', '30.00'), ('0004', 'overpaid', '-5.00')]
    assert r['unmatched_payments'] == [5]
    assert r['counts'] == {'invoice_rows': 4, 'payment_rows': 5, 'allocated_payment_rows': 4, 'unmatched_payment_rows': 1, 'review_payment_rows': 0}


def test_duplicate_ids_block_all_affected_allocations():
    i = 'invoice_id,amount,currency\nA,10,USD\nA,10,USD\nB,20,USD\nC,30,USD\n'
    p = 'payment_id,invoice_id,amount,currency\nD,A,10,USD\nP,B,20,USD\nP,C,30,USD\n'
    r = reconcile(i,p)
    assert all(x['state']=='review' and x['balance'] is None for x in r['invoices'])
    assert r['review_payments'] == [1,2,3]


@pytest.mark.parametrize('bad', ['NaN','-3','0','1.234','1e2'])
def test_rejects_unsupported_amounts(bad):
    with pytest.raises(ValueError):
        reconcile(f'invoice_id,amount,currency\nA,{bad},USD\n','payment_id,invoice_id,amount,currency\n')


def test_currency_mismatch_is_review_not_allocation():
    r = reconcile('invoice_id,amount,currency\nA,10,USD\n','payment_id,invoice_id,amount,currency\nP,A,10,EUR\n')
    assert r['invoices'][0]['state']=='review'
    assert r['review_payments']==[1]


def test_rejects_extra_columns_and_formula_like_identifiers():
    for i in ('invoice_id,amount,currency,name\nA,10,USD,test\n','invoice_id,amount,currency\n=1+1,10,USD\n'):
        with pytest.raises(ValueError):
            reconcile(i,'payment_id,invoice_id,amount,currency\n')
