from __future__ import annotations

from src.source_spike.stackexchange_html import html_body_to_text, html_title_to_text


def test_title_decodes_entities_and_removes_markup() -> None:
    assert html_title_to_text("How to use &lt;dict&gt; &amp; <b>list</b>?") == "How to use <dict> & list?"


def test_body_preserves_blocks_code_and_anchor_text_but_not_targets_or_scripts() -> None:
    value = html_body_to_text(
        "<p>First &amp; second</p><script>SECRET</script><blockquote>Quoted</blockquote>"
        "<pre><code>x &lt; y</code></pre><p>Read <a href='https://secret.test'>the docs</a>.</p>"
    )
    assert "First & second" in value
    assert "Quoted" in value
    assert "x < y" in value
    assert "the docs" in value
    assert "SECRET" not in value
    assert "https://secret.test" not in value
    assert "\n" in value
