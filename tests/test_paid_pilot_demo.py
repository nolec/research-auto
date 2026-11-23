from src.paid_pilot_demo import repair_demo, spreadsheet_demo


def test_mock_workflow_accounts_for_every_input():
    result = repair_demo()
    assert result["input_count"] == result["accounted_count"] == 5
    assert len(result["after"]) == 2
    assert {r["reason"] for r in result["exceptions"]} == {"repeat", "invalid_quantity", "conflict"}


def test_mock_spreadsheet_preserves_conflicting_source_rows():
    result = spreadsheet_demo()
    assert result["counts"] == {"accepted": 3, "duplicates": 1, "unresolved_source_rows": 2}
    assert result["accepted_total_only"] == "20.50"
    assert {r["amount"] for r in result["unresolved"][0]["source_rows"]} == {"8.00", "9.00"}
