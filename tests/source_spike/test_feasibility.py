from src.source_spike.feasibility import validate_feasibility_decision


def test_feasibility_validator_rejects_an_empty_decision() -> None:
    errors = validate_feasibility_decision({})

    assert errors
    assert any("required property" in error for error in errors)
