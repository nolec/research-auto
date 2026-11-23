import pytest

from src.scanned_pdf_experiment.numeric_reread import (
    NumericCandidate, Reading, SourceCrop, confirm_numeric, parse_number,
)
from src.scanned_pdf_experiment.numeric_evaluation import score_numeric


@pytest.fixture
def crop():
    return SourceCrop("doc-01", 1, "row//amount", (1, 2, 3, 4), b"crop")


def test_confirm_agreement_and_cache(crop):
    seen = []

    def reader(source):
        seen.append(source)
        return Reading("1,200.00", 92, source.digest)

    result = confirm_numeric([NumericCandidate(crop, "1200", "1201"), NumericCandidate(crop, "1200", "1300")], reader)
    assert seen == [crop]
    assert [x.status for x in result] == ["DETECTED", "DETECTED"]


@pytest.mark.parametrize("text,confidence,reason", [
    ("100", 99, "READS_DISAGREE"),
    ("300", 99, "READS_DISAGREE"),
    ("200", 79.9, "LOW_OR_INVALID_CONFIDENCE"),
    ("200", float("nan"), "LOW_OR_INVALID_CONFIDENCE"),
    ("2O0", 99, "INVALID_REREAD"),
])
def test_uncertainty_is_explicit(crop, text, confidence, reason):
    item = NumericCandidate(crop, "200", "100")
    result, = confirm_numeric([item], lambda c: Reading(text, confidence, c.digest))
    assert result.status == "UNCERTAIN"
    assert result.reason == reason
    assert result.candidate == item


def test_missing_read_and_wrong_crop(crop):
    item = NumericCandidate(crop, "200", "100")

    def unavailable(_):
        raise TimeoutError

    assert confirm_numeric([item], unavailable)[0].reason == "REREAD_UNAVAILABLE"
    assert confirm_numeric([item], lambda _: Reading("200", 99, "wrong"))[0].reason == "CROP_BINDING_MISMATCH"


def test_no_discrepancy_no_reread(crop):
    def forbidden(_):
        pytest.fail("No reread needed")

    result, = confirm_numeric([NumericCandidate(crop, "1,000", "1000.0")], forbidden)
    assert result.status == "NO_ALERT"


@pytest.mark.parametrize("value", ["1,2", "1e3", "NaN", "Infinity", "1 00", "", "12%"])
def test_invalid_numeric_not_guessed(value):
    assert parse_number(value) is None


def test_uncertain_actual_error_counts_as_missed(crop):
    decisions = confirm_numeric([NumericCandidate(crop, "200", "100")], lambda c: Reading("100", 99, c.digest))
    assert score_numeric([(crop.document, crop.page, crop.cell)], decisions) == {
        "tp": 0, "fp": 0, "fn": 1, "uncertain": 1, "precision": None, "recall": 0.0,
    }


def test_duplicate_detection_is_false_positive(crop):
    candidates = [NumericCandidate(crop, "200", "100")] * 2
    decisions = confirm_numeric(candidates, lambda c: Reading("200", 99, c.digest))
    assert score_numeric([(crop.document, crop.page, crop.cell)], decisions)["fp"] == 1


def test_same_cell_in_another_document_is_not_true_positive(crop):
    decisions = confirm_numeric([NumericCandidate(crop, "200", "100")], lambda c: Reading("200", 99, c.digest))
    score = score_numeric([("another-doc", crop.page, crop.cell)], decisions)
    assert (score["tp"], score["fp"], score["fn"]) == (0, 1, 1)
