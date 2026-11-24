from src.extraction import cluster_diagnostic as diagnostic


def row(key, text, title="Weekly invoice export"):
    return dict(document_id=key, text=text, title=title, source="github")


def test_conflicts_excluded_and_exact_copies_share_one_representative():
    rows = [row("b", "Cannot export weekly invoices."), row("a", "Cannot export weekly invoices."),
            row("c", "Missing rows."), row("c", "Missing totals.")]
    docs, conflicts = diagnostic.corpus(reversed(rows))
    assert list(docs) == ["a"]
    assert docs["a"]["ids"] == ["a", "b"]
    assert conflicts == ["c"]


def test_related_reports_group_but_shared_topic_alone_is_insufficient():
    rows = [row("a", "Cannot export weekly invoice totals to CSV. See screenshot."),
            row("b", "Cannot export weekly invoice totals to CSV. Reproduced yesterday."),
            row("c", "Cannot print monthly invoice labels on paper.")]
    docs, _ = diagnostic.corpus(rows)
    assert diagnostic.clusters(docs) == [["a", "b"], ["c"]]


def test_review_rejects_changed_sources():
    import pytest
    docs, _ = diagnostic.corpus([row("a", "Cannot export weekly invoices.")])
    with pytest.raises(ValueError, match="digest"):
        diagnostic.review_item(docs, "a", "changed")


def test_reporter_selects_actual_behavior_verbatim_before_system_info():
    symptom = "the update button moves to the right just before the click"
    text = ("Menu Type: <b>Bug</b> Expected behaviour * editor updates "
            f"Actual behaviour * {symptom} * unrelated detail "
            "VS Code version: Code 1.2 |Process Argv|--crash-reporter-id 123")
    docs, _ = diagnostic.corpus([row("a", text)])
    assert docs["a"]["quote"] == symptom


def test_reporter_uses_authored_description_or_abstains_on_empty_body():
    symptom = "the confirmation dialog disappears instantly"
    footer = "<details> <summary>System Info</summary> |Process Argv|--crash-reporter-id 123"
    rows = [row("a", f"Dialog Type: <b>Bug</b> {symptom} {footer}"),
            row("b", f"Dialog Type: <b>Bug</b> {footer}")]
    docs, _ = diagnostic.corpus(rows)
    assert docs["a"]["quote"] == symptom
    assert docs["b"]["quote"] == ""
    assert diagnostic.clusters(docs) == [["a"], ["b"]]


def test_steam_praise_alone_is_excluded_but_original_review_remains_available():
    rows = [dict(row("a", "I cannot recommend Wallpaper Engine highly enough.", "Wallpaper Engine"),
                 source="steam")]
    docs, _ = diagnostic.corpus(rows)
    assert not docs
    review, _ = diagnostic.corpus(rows, include_excluded=True)
    assert diagnostic.review_item(review, "a", diagnostic.digest(rows[0]["text"]))["evidence"] == rows[0]["text"]


def test_steam_keeps_complaint_alongside_praise_and_literal_negative_recommendation():
    rows = [dict(row("a", "Can't recommend it enough! It freezes on startup."), source="steam"),
            dict(row("b", "I cannot recommend this until cloud saves work."), source="steam"),
            dict(row("c", "I cannot export a save. I cannot recommend it enough."), source="steam")]
    docs, _ = diagnostic.corpus(rows)
    assert docs["a"]["quote"] == "It freezes on startup."
    assert docs["b"]["quote"] == rows[1]["text"]
    assert docs["c"]["quote"] == "I cannot export a save."
