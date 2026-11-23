import pytest

from scripts.scanned_pdf_assisted_review import evaluate


KEY = {'packet':'abc','answers':{'a':{'actual_error':True,'source_value':'100'},'b':{'actual_error':False,'source_value':'200'}},'total_faults':2,'total_positions':20}


def test_assisted_score_counts_unqueued_fault():
    result = evaluate(KEY, {'packet':'abc','responses':{'a':{'decision':'error','value':'100','ms':1500},'b':{'decision':'match','value':'','ms':500}}})
    assert (result['tp'],result['fp'],result['fn']) == (1,0,1)
    assert result['active_seconds'] == 2
    assert result['corrected_fault_values'] == 1


def test_unknown_is_not_correct_detection():
    result = evaluate(KEY, {'packet':'abc','responses':{'a':{'decision':'unknown','value':'','ms':100},'b':{'decision':'error','value':'250','ms':200}}})
    assert (result['tp'],result['fp'],result['fn'],result['unresolved']) == (0,1,2,1)


@pytest.mark.parametrize('packet,responses', [('wrong',{}),('abc',{}),('abc',{'a':{},'b':{},'c':{}})])
def test_rejects_wrong_or_incomplete_packet(packet,responses):
    with pytest.raises(ValueError):
        evaluate(KEY, {'packet':packet,'responses':responses})


@pytest.mark.parametrize('value', ['1,100', '1100.00', '+01100', 'not a number'])
def test_v2_rejects_same_or_invalid_correction(value):
    key = {'packet':'v2','answers':{'a':{'actual_error':True,'source_value':'100','sheet_value':'1100'}},'total_faults':1,'total_positions':2}
    with pytest.raises(ValueError, match='Correction'):
        evaluate(key, {'packet':'v2','responses':{'a':{'decision':'error','value':value,'ms':100}}})


def test_v2_accepts_distinct_correction():
    key = {'packet':'v2','answers':{'a':{'actual_error':True,'source_value':'100','sheet_value':'1100'}},'total_faults':1,'total_positions':2}
    result = evaluate(key, {'packet':'v2','responses':{'a':{'decision':'error','value':'100','ms':100}}})
    assert result['corrected_fault_values'] == 1
