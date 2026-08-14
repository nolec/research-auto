import json

import pytest

from src.source_spike.review_handoff import build_offline_review_html, write_offline_review


def packet():
    return [{"assignment_id": "opaque-123", "source": "stackexchange", "title": "A <problem>", "normalized_text": "Concrete failure", "canonical_url": "https://example.com/q", "hidden_split": "holdout"}]


def test_offline_review_embeds_only_blind_fields():
    value = build_offline_review_html(packet(), title="Blind review")
    assert "opaque-123" in value
    assert "A <problem>" in value
    assert "const escapeHtml=" in value
    assert "hidden_split" not in value
    assert "secondary-submission.jsonl" in value
    assert "reviewer_independence_asserted:independent" in value
    assert "사업성을 평가하는 일이 아닙니다" in value
    assert "수작업이나 불편만으로 돈 신호를 추측하지 마세요" in value
    assert "localStorage.setItem" in value
    assert "완료 0 / 1" in value


def test_primary_review_does_not_require_secondary_independence():
    value = build_offline_review_html(packet(), title="Primary", review_role="primary")
    assert "primary-submission.jsonl" in value
    assert 'const reviewRole="primary"' in value
    assert 'id="independent"' not in value
    assert "Primary와 다른 Reviewer ID가 필요합니다." in value


def test_review_rejects_unknown_role():
    with pytest.raises(ValueError, match="primary or secondary"):
        build_offline_review_html(packet(), title="Blind review", review_role="observer")


def test_offline_review_rejects_empty_or_malformed_packet():
    with pytest.raises(ValueError, match="must not be empty"):
        build_offline_review_html([], title="Blind review")
    with pytest.raises(ValueError, match="malformed"):
        build_offline_review_html([{}], title="Blind review")


def test_write_offline_review(tmp_path):
    source = tmp_path / "packet.json"
    destination = tmp_path / "review.html"
    source.write_text(json.dumps(packet()))
    write_offline_review(source, destination, title="Blind review")
    assert destination.read_text().startswith("<!doctype html>")


def test_write_offline_review_is_idempotent(tmp_path):
    source = tmp_path / "packet.json"
    destination = tmp_path / "review.html"
    source.write_text(json.dumps(packet()))
    write_offline_review(source, destination, title="Blind review")
    before = destination.stat().st_mtime_ns
    write_offline_review(source, destination, title="Blind review")
    assert destination.stat().st_mtime_ns == before
