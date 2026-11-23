import pytest

from src.scanned_pdf_experiment.numeric_reread import NumericCandidate, SourceCrop
from src.scanned_pdf_experiment.visual_agreement import VisualReading, confirm_visual


def crop(doc='clean'):
    return SourceCrop(doc,1,'0/0',(1,2,3,4),b'pixels')


def test_agreement_reuses_identical_image_across_variants_without_sheet_values():
    seen=[]
    def reader(source):
        seen.append(source)
        return VisualReading('1,200',source.digest)
    result=confirm_visual([NumericCandidate(crop(),'1200','1300'),NumericCandidate(crop('corrupt'),'1200','1400')],reader)
    assert seen==[crop()]
    assert [r.status for r in result]==['DETECTED','DETECTED']


@pytest.mark.parametrize('response,reason',[(None,'REREAD_UNAVAILABLE'),(VisualReading('1200','wrong'),'CROP_BINDING_MISMATCH')])
def test_invalid_read_never_confirms(response,reason):
    result,=confirm_visual([NumericCandidate(crop(),'1200','1300')],lambda _:response)
    assert (result.status,result.reason)==('UNCERTAIN',reason)


def test_second_read_matching_sheet_is_still_uncertain():
    result,=confirm_visual([NumericCandidate(crop(),'1200','1300')],lambda c:VisualReading('1300',c.digest))
    assert (result.status,result.reason)==('UNCERTAIN','READS_DISAGREE')


def test_no_mismatch_no_reread():
    result,=confirm_visual([NumericCandidate(crop(),'1,200','1200')],lambda _:pytest.fail('Unnecessary reread'))
    assert result.status=='NO_ALERT'
