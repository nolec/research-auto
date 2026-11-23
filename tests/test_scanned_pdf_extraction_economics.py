from scripts.scanned_pdf_extraction_economics import extraction_gate, cost


def test_extraction_gate_requires_agreement_and_confidence():
    assert extraction_gate('1,000',[{'text':'1000','confidence':80},{'text':'1000.0','confidence':99}])
    assert not extraction_gate('1000',[{'text':'1000','confidence':79}])
    assert not extraction_gate('1000',[{'text':'1001','confidence':99}])
    assert not extraction_gate('1000',[])
    assert not extraction_gate('unreadable',[{'text':'1000','confidence':99}])


def test_cost_includes_all_cells_and_overhead():
    assert cost(19,100,15)['net_contribution']==5.15
    assert cost(19,500,15)['net_contribution']<0
