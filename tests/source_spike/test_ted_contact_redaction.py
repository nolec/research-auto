from src.source_spike.ted_contact_redaction import redact_contacts, residual_contact_count, select_language


def test_language_selection_is_english_first_and_order_independent() -> None:
    assert select_language({"fra": "bonjour", "eng": "hello"}) == "hello"
    assert select_language({"zho": "z", "deu": "d"}) == "d"
    assert select_language({"deu": "d", "zho": "z"}) == "d"


def test_redactor_removes_email_and_phone_before_residual_scan() -> None:
    source = "Contact jane@example.com, +44 20 7946 0958, 01012345678 or (02) 1234-5678. CPV 48000000."
    result = redact_contacts(source)
    assert result.count == 4
    assert "jane@example.com" not in result.text
    assert "01012345678" not in result.text
    assert "48000000" in result.text
    assert residual_contact_count(result.text) == 0


def test_publication_number_and_date_are_not_redacted() -> None:
    result = redact_contacts("Notice 566482-2026 was published on 20260816 for CPV 48000000.")
    assert result.count == 0
