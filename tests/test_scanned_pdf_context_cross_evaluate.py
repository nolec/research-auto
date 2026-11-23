import pytest

from scripts.scanned_pdf_context_cross_evaluate import decide


def read(value,confidence=95):return {'text':value,'confidence':confidence}


def test_two_reads_confirm_actual_numeric_mismatch():
    assert decide('1,200','1300',[read('1200'),read('1,200.0')])=='DETECTED'


@pytest.mark.parametrize('observations', [[],[read('1200',79)],[read('1300')],[read('1200'),read('1300')],[read('1200',float('nan'))],[read('—')]])
def test_disagreement_or_missing_evidence_stays_uncertain(observations):
    assert decide('1200','1300',observations)=='UNCERTAIN'


def test_matching_primary_does_not_claim_cross_confirmation():
    assert decide('1,200','1200',[read('1300')])=='NO_ALERT'


def test_invalid_primary_is_not_silently_dismissed():
    assert decide('UNREADABLE','1200',[read('1200')])=='UNCERTAIN'
