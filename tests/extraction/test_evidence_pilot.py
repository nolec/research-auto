from copy import deepcopy
from hashlib import sha256
import json

import pytest

from src.extraction.development_slice import ExtractionValidationError
from src.extraction.evidence_pilot import review_membership, summarize_pilot, validate_manifest, validate_row
from test_development_slice import _valid_output


def make_row(document_id="github:one", **document_fields):
    document = {
        "document_id": document_id,
        "source": "github",
        "title": "Document conversion fixture",
        "text": "Export drops footnotes. The editor restores them manually.",
        "published_at": "2026-11-01T00:00:00Z",
        "source_url": f"https://example.com/{document_id}",
        **document_fields,
    }
    return {
        "document": document,
        "extraction": _valid_output(document),
        "source_metadata": {
            "document_id": document_id,
            "author_hash": "author-one",
            "community": "conversion-project",
        },
        "source_verified": False,
        "thread_id": None,
        "event_id": None,
    }


def seal(manifest):
    content = {key: value for key, value in manifest.items() if key != "protocol_hash"}
    manifest["protocol_hash"] = sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return manifest


def make_manifest(broad=None, focused=None):
    return seal({
        "run_id": "fixture-run",
        "as_of": "2026-11-20T00:00:00Z",
        "candidate_id": "footnote-export",
        "source": "github",
        "window_start": "2026-08-22T00:00:00Z",
        "window_end": "2026-11-20T00:00:00Z",
        "arms": {
            "broad": {"query": "convert", "sampling_method": "chronological", "cap": 20,
                      "rows": [make_row()] if broad is None else broad},
            "focused": {"query": "footnotes", "sampling_method": "chronological", "cap": 20,
                        "rows": [make_row("github:two")] if focused is None else focused},
        },
    })


def test_row_delegates_to_observation_adapter_and_preserves_metadata():
    row = make_row()
    original = deepcopy(row)
    result = validate_row(row)
    assert result["status"] == "OBSERVATION"
    assert result["observation"]["source_metadata"]["author_hash"] == "author-one"
    assert row == original
    assert row["source_verified"] is False


def test_rejects_altered_quote():
    row = make_row()
    row["extraction"]["evidence_quote"] = "X" + row["extraction"]["evidence_quote"][1:]
    with pytest.raises(ExtractionValidationError, match="span does not match"):
        validate_row(row)


def test_manifest_snapshot_is_a_deep_copy_and_hash_bound():
    manifest = make_manifest()
    snapshot = validate_manifest(manifest)
    assert snapshot == manifest
    manifest["arms"]["broad"]["rows"][0]["source_verified"] = True
    assert snapshot["arms"]["broad"]["rows"][0]["source_verified"] is False
    with pytest.raises(ValueError, match="hash"):
        validate_manifest(manifest)


@pytest.mark.parametrize("cap", [21, 0, True, 1.5, -1])
def test_rejects_invalid_caps(cap):
    manifest = make_manifest()
    manifest["arms"]["broad"]["cap"] = cap
    with pytest.raises(ValueError):
        validate_manifest(seal(manifest))


def test_rejects_more_rows_than_cap_even_when_hash_valid():
    manifest = make_manifest(broad=[make_row(), make_row("github:three")])
    manifest["arms"]["broad"]["cap"] = 1
    with pytest.raises(ValueError):
        validate_manifest(seal(manifest))


@pytest.mark.parametrize("rows", [["github:dangling"], [make_row(), make_row()]])
def test_rejects_dangling_or_duplicate_rows_within_arm(rows):
    with pytest.raises(ValueError):
        validate_manifest(make_manifest(broad=rows))


def test_cross_arm_overlap_must_have_identical_rows():
    row = make_row()
    assert validate_manifest(make_manifest(broad=[row], focused=[deepcopy(row)]))
    conflicting = deepcopy(row)
    conflicting["event_id"] = "different"
    with pytest.raises(ValueError):
        validate_manifest(make_manifest(broad=[row], focused=[conflicting]))


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///local", "https://", "https://example.com/a b"])
def test_rejects_non_http_public_urls(url):
    with pytest.raises(ValueError):
        validate_row(make_row(source_url=url))


@pytest.mark.parametrize("url", [
    "http://localhost/record",
    "http://LOCALHOST./record",
    "http://project.localhost/record",
    "http://project.local/record",
    "http://project.internal/record",
    "http://intranet/record",
    "http://127.0.0.1/record",
    "http://10.0.0.1/record",
    "http://169.254.169.254/record",
    "http://100.64.0.1/record",
    "http://[::1]/record",
    "http://[fc00::1]/record",
    "http://[::ffff:127.0.0.1]/record",
    "https://user:secret@example.com/record",
    "https://user@example.com/record",
    "http://127.1/record",
    "http://2130706433/record",
    "http://0x7f000001/record",
    "http://%31%32%37.0.0.1/record",
])
def test_rejects_local_non_global_and_credentialed_urls(url):
    with pytest.raises(ValueError):
        validate_row(make_row(source_url=url))


@pytest.mark.parametrize("url", [
    "https://github.com/project/converter/issues/42",
    "https://api.github.com/repos/project/converter/issues/42",
    "https://8.8.8.8/record",
    "https://[2606:4700:4700::1111]/record",
])
def test_accepts_public_url_shape_without_verifying_source(url):
    row = make_row(source_url=url)
    assert validate_row(row)["observation"]["source_metadata"]["source_url"] == url
    assert row["source_verified"] is False


@pytest.mark.parametrize("field", ["as_of", "window_start", "window_end"])
@pytest.mark.parametrize("value", ["2026-11-20T00:00:00", None, "invalid"])
def test_rejects_non_aware_manifest_dates(field, value):
    manifest = make_manifest()
    manifest[field] = value
    with pytest.raises(ValueError):
        validate_manifest(seal(manifest))


def test_rejects_inverted_window():
    manifest = make_manifest()
    manifest["window_start"] = "2026-11-21T00:00:00Z"
    with pytest.raises(ValueError):
        validate_manifest(seal(manifest))


def test_does_not_reject_unknown_or_unmatched_source_dates():
    row = make_row("other:one", source="stackexchange", published_at=None)
    assert validate_manifest(make_manifest(broad=[row]))
    row["document"]["published_at"] = "not a date"
    assert validate_manifest(make_manifest(broad=[row]))


@pytest.mark.parametrize("field,value", [("source_verified", 1), ("source_verified", None),
                                        ("thread_id", 1), ("event_id", " "), ("source_metadata", {})])
def test_rejects_invalid_metadata_types(field, value):
    row = make_row()
    row[field] = value
    with pytest.raises(ValueError):
        validate_row(row)


def test_keeps_missing_source_metadata_unknown():
    row = make_row(published_at=None)
    row["source_metadata"] = None
    result = validate_row(row)
    assert result["observation"]["source_metadata"]["published_at"] is None
    assert "author_hash" not in result["observation"]["source_metadata"]


@pytest.mark.parametrize("field,value", [("document_id", 10), ("source", " "), ("title", None),
                                        ("text", []), ("published_at", 2026)])
def test_rejects_invalid_document_types(field, value):
    row = make_row()
    row["document"][field] = value
    with pytest.raises(ValueError):
        validate_row(row)


def test_rejects_unexpected_fields():
    row = make_row()
    row["extra"] = None
    with pytest.raises(ValueError):
        validate_row(row)
    manifest = make_manifest()
    manifest["arms"]["broad"]["extra"] = None
    with pytest.raises(ValueError):
        validate_manifest(seal(manifest))


def quote_ref(row):
    extraction = row["extraction"]
    return {"quote": extraction["evidence_quote"], "start": extraction["evidence_start"],
            "end": extraction["evidence_end"]}


def decision(row, **changes):
    return {
        "membership": "DIRECT", "reason": "Same actor, task and failure",
        "quote_meaning_verified": True, "membership_quote": quote_ref(row),
        "loss_direct": False, "loss_quote": None, "economic_kind": "UNKNOWN",
        "economic_reason": "No payment evidence reviewed", "economic_quote": None,
        "counter_signal": False, "counter_quote": None, "counter_assessment": "NOT_ASSESSED",
        "counter_rationale": "Counter review pending", **changes,
    }


def make_review(manifest, decisions=None, **changes):
    return {
        "protocol_hash": manifest["protocol_hash"], "candidate_id": manifest["candidate_id"],
        "actor": "Document editor", "task": "Export documents preserving footnotes",
        "failure": "Footnotes are dropped on export", "reviewer": "Fixture human reviewer",
        "review_kind": "HUMAN", "decisions": {} if decisions is None else decisions,
        **changes,
    }


def test_shared_words_but_different_task_is_adjacent_and_missing_is_unreviewed():
    row = make_row(text="Export footnotes to a bibliography, not a document.")
    row["source_verified"] = True
    manifest = make_manifest(broad=[row])
    review = make_review(manifest, {row["document"]["document_id"]: decision(
        row, membership="ADJACENT", membership_quote=None,
        reason="Bibliography export is a different task despite shared words")})
    results = review_membership(manifest, review)
    assert [r["membership"] for r in results] == ["ADJACENT", "UNREVIEWED"]
    assert results[0]["reviewed"] is True
    assert results[1]["reviewed"] is False
    assert not any(r["eligible"] for r in results)


@pytest.mark.parametrize("changes", [{"protocol_hash": "bad"}, {"candidate_id": "other"},
                                    {"decisions": {"unknown": {}}}])
def test_review_must_bind_manifest_candidate_and_known_document_ids(changes):
    manifest = make_manifest()
    with pytest.raises(ValueError):
        review_membership(manifest, make_review(manifest, **changes))


@pytest.mark.parametrize("changes", [
    {"membership_quote": None}, {"loss_direct": True},
    {"economic_kind": "DIRECT_WTP"}, {"economic_kind": "ADJACENT"},
    {"counter_signal": True}, {"counter_assessment": "CRITICAL"},
    {"membership_quote": {"quote": "Export", "start": 0, "end": 6}},
    {"membership_quote": {"quote": "Export drops footnote", "start": 0, "end": 20}},
])
def test_affirmative_signal_requires_exact_extraction_quote(changes):
    row = make_row()
    manifest = make_manifest(broad=[row])
    review = make_review(manifest, {row["document"]["document_id"]: decision(row, **changes)})
    with pytest.raises(ValueError):
        review_membership(manifest, review)


@pytest.mark.parametrize("changes", [{"usable_evidence": False}, {"problem_signal": False}])
def test_direct_requires_usable_extracted_problem(changes):
    row = make_row()
    row["extraction"].update(changes)
    manifest = make_manifest(broad=[row])
    with pytest.raises(ValueError):
        review_membership(manifest, make_review(manifest, {row["document"]["document_id"]: decision(row)}))


def test_abstention_cannot_be_direct():
    row = make_row()
    row["extraction"] = {key: None for key in row["extraction"]}
    row["extraction"].update(document_id=row["document"]["document_id"], abstention_reason="No signal")
    manifest = make_manifest(broad=[row])
    with pytest.raises(ValueError):
        review_membership(manifest, make_review(manifest, {row["document"]["document_id"]: decision(row)}))


@pytest.mark.parametrize("source_verified,meaning_verified,eligible", [
    (True, True, True), (True, False, False), (False, True, False), (False, False, False),
])
def test_eligibility_requires_both_independent_verification_flags(source_verified, meaning_verified, eligible):
    row = make_row()
    row["source_verified"] = source_verified
    manifest = make_manifest(broad=[row])
    review = make_review(manifest, {row["document"]["document_id"]: decision(
        row, quote_meaning_verified=meaning_verified)})
    result = review_membership(manifest, review)[0]
    assert result["eligible"] is eligible
    assert result["reviewed"] is True
    assert result["source_verified"] is source_verified
    assert result["quote_meaning_verified"] is meaning_verified


def test_ai_proposal_is_retained_but_not_human_reviewed_or_counted():
    row = make_row()
    manifest = make_manifest(broad=[row])
    review = make_review(manifest, {row["document"]["document_id"]: decision(
        row, quote_meaning_verified=False)}, review_kind="AI_PROPOSAL", reviewer="AI preliminary proposal")
    result = review_membership(manifest, review)[0]
    assert result["membership"] == "DIRECT"
    assert result["reviewed"] is result["eligible"] is False
    assert result["review_kind"] == "AI_PROPOSAL"


def test_ai_proposal_cannot_assert_human_quote_or_counter_verification():
    row = make_row()
    manifest = make_manifest(broad=[row])
    for changes in ({}, {"quote_meaning_verified": False, "counter_assessment": "NONE_CRITICAL"}):
        review = make_review(manifest, {row["document"]["document_id"]: decision(row, **changes)},
                             review_kind="AI_PROPOSAL")
        with pytest.raises(ValueError):
            review_membership(manifest, review)


def test_rejected_row_is_preserved_and_counter_evidence_can_be_reviewed():
    row = make_row(text="A built-in free option now preserves every footnote.")
    row["source_verified"] = True
    manifest = make_manifest(broad=[row])
    review = make_review(manifest, {row["document"]["document_id"]: decision(
        row, membership="REJECT", membership_quote=None, reason="Already solved for this actor",
        counter_signal=True, counter_quote=quote_ref(row), counter_assessment="CRITICAL",
        counter_rationale="Fixture critical negative evidence")})
    result = review_membership(manifest, review)[0]
    assert result["membership"] == "REJECT" and result["counter_eligible"] is True
    assert result["eligible"] is False
    assert result["document"] == row["document"]


def test_verified_direct_signals_are_retained_with_exact_refs():
    row = make_row(text="Export drops footnotes. We paid a service $20 to restore them.")
    row["source_verified"] = True
    row["extraction"].update(evidence_quote=row["document"]["text"], evidence_end=len(row["document"]["text"]))
    manifest = make_manifest(broad=[row])
    review = make_review(manifest, {row["document"]["document_id"]: decision(
        row, loss_direct=True, loss_quote=quote_ref(row), economic_kind="DIRECT_PAID_SUBSTITUTE",
        economic_quote=quote_ref(row), economic_reason="Payment to restore missing footnotes")})
    original = deepcopy(review)
    result = review_membership(manifest, review)[0]
    assert result["loss_eligible"] is result["economic_eligible"] is True
    assert review == original


def known_row(i, **fields):
    row = make_row(f"github:{i}", **{"text": f"Report {i} about malformed conversion.", **fields})
    row["source_verified"] = True
    row["source_metadata"].update(author_hash=f"author-{i}", community=f"community-{i}")
    row["thread_id"] = f"thread-{i}"
    return row


def all_direct(manifest):
    return make_review(manifest, {
        row["document"]["document_id"]: decision(row)
        for arm in manifest["arms"].values() for row in arm["rows"]
    })


def test_summary_deduplicates_dates_and_groups_and_preserves_unknowns():
    first = known_row(1)
    second = known_row(2, published_at="2026-08-01T00:00:00Z")
    second["source_metadata"]["author_hash"] = first["source_metadata"]["author_hash"]
    third = known_row(3, published_at="2026-11-21T00:00:00Z")
    third["thread_id"] = second["thread_id"]
    unknown = known_row(4, published_at=None)
    unknown["source_metadata"] = None
    date_only = known_row(5, published_at="2026-10-01")
    alias = deepcopy(first)
    alias["document"].update(document_id="alias", source_url=first["document"]["source_url"] + "#reply")
    alias["source_metadata"]["document_id"] = "alias"
    alias["extraction"]["document_id"] = "alias"
    manifest = make_manifest([first, second, unknown], [first, third, date_only, alias])
    result = summarize_pilot(manifest, all_direct(manifest))
    assert result["combined_unique_cases"] == 5
    assert result["recent_case_count"] == 1
    assert result["known_group_count"] == 1
    assert result["overlap"]["count"] == 1
    assert result["unknown_counts"]["author"] == 1
    assert result["unknown_counts"]["publication_timestamp"] == 2
    assert result["comparison_valid"] is False
    assert result["counter_status"] == "NOT_ASSESSED"


def test_economic_and_loss_count_each_known_group_at_most_once():
    rows = [known_row(i, text=text) for i, text in enumerate([
        "Export loses footnotes. We would pay to restore them.",
        "The dropped notes cost hours; we would pay for correction.",
        "We would pay for missing footnote restoration after wasted days.",
        "I paid for bibliography export.", "Our hiring budget is $200.",
        "Could pay to recover these notes but identity unknown.",
    ])]
    rows[1]["thread_id"] = rows[0]["thread_id"]
    rows[5]["source_metadata"] = None
    manifest = make_manifest(rows[:3], rows[3:])
    review = all_direct(manifest)
    for i, row in enumerate(rows):
        review["decisions"][row["document"]["document_id"]] = decision(
            row, economic_kind="DIRECT_WTP" if i in {0,1,2,5} else "ADJACENT",
            economic_quote=quote_ref(row), loss_direct=i in {0,1,2,5},
            loss_quote=quote_ref(row) if i in {0,1,2,5} else None,
        )
    result = summarize_pilot(manifest, review)
    assert result["direct_economic_count"] == result["loss_count"] == 2


def test_counter_status_never_treats_uncertain_or_unverified_critical_as_clear():
    rows = [known_row(1), known_row(2), known_row(3, text="Free built-in fix preserves all notes.")]
    rows[2]["source_verified"] = False
    manifest = make_manifest(rows, [])
    review = all_direct(manifest)
    review["decisions"]["github:1"]["counter_assessment"] = "NONE_CRITICAL"
    review["decisions"]["github:2"]["counter_assessment"] = "UNCERTAIN"
    review["decisions"]["github:3"] = decision(rows[2], membership="REJECT", membership_quote=None,
        counter_signal=True, counter_quote=quote_ref(rows[2]), counter_assessment="CRITICAL")
    assert summarize_pilot(manifest, review)["counter_status"] == "UNCERTAIN"
    rows[2]["source_verified"] = True
    manifest = make_manifest(rows, [])
    review["protocol_hash"] = manifest["protocol_hash"]
    result = summarize_pilot(manifest, review)
    assert result["counter_status"] == "CRITICAL"
    assert {"gate": "counter_status", "required": "NONE_CRITICAL", "actual": "CRITICAL"} in result["gate_deficits"]


@pytest.mark.parametrize("mismatch", [None, "source", "window", "denominator", "overlap", "cap", "method", "date_only"])
def test_comparison_descriptive_and_requires_matched_disjoint_reviewed_arms(mismatch):
    broad = [known_row(i) for i in range(8)]
    focused = [known_row(i) for i in range(8,16)]
    if mismatch == "source": focused[0]["document"]["source"] = "different"
    if mismatch == "window": focused[0]["document"]["published_at"] = "2026-08-01T00:00:00Z"
    if mismatch == "date_only": focused[0]["document"]["published_at"] = "2026-11-01"
    if mismatch == "overlap": focused[0] = deepcopy(broad[0])
    manifest = make_manifest(broad, focused)
    if mismatch == "cap": manifest["arms"]["focused"]["cap"] = 8
    if mismatch == "method": manifest["arms"]["focused"]["sampling_method"] = "other"
    seal(manifest)
    review = all_direct(manifest)
    for row in broad[1:] + focused[4:]:
        review["decisions"][row["document"]["document_id"]].update(membership="REJECT", membership_quote=None)
    if mismatch == "denominator": review["decisions"].pop("github:15")
    result = summarize_pilot(manifest, review)
    assert result["comparison_valid"] is (mismatch is None)
    if mismatch is None:
        assert result["arms"]["broad"]["reviewed_denominator"] == 8
        assert result["arms"]["broad"]["direct_eligible_count"] == 1
        assert result["arms"]["focused"]["direct_eligible_count"] == 4
        assert "descriptive" in result["comparison_reason"].lower()


def test_comparison_rejects_equal_nonzero_but_selectively_reviewed_arms():
    broad = [known_row(i) for i in range(8)]
    focused = [known_row(i) for i in range(8, 16)]
    manifest = make_manifest(broad, focused)
    review = make_review(manifest, {
        row["document"]["document_id"]: decision(row) for row in (broad[0], focused[0])
    })
    result = summarize_pilot(manifest, review)
    assert result["arms"]["broad"]["reviewed_denominator"] == 1
    assert result["arms"]["focused"]["reviewed_denominator"] == 1
    assert result["comparison_valid"] is False
    assert "complete" in result["comparison_reason"].lower()


def test_summary_keeps_ai_proposals_separate_from_reviewed_denominator():
    manifest = make_manifest([known_row(1, published_at="2026-11-01")], [])
    review = all_direct(manifest)
    review["review_kind"] = "AI_PROPOSAL"
    review["decisions"]["github:1"]["quote_meaning_verified"] = False
    summary = summarize_pilot(manifest, review)
    assert summary["arms"]["broad"]["reviewed_denominator"] == 0
    assert summary["arms"]["broad"]["proposal_count"] == 1
    assert summary["arms"]["broad"]["proposed_direct_count"] == 1
    assert summary["combined_unique_cases"] == 1
    assert summary["eligible_unique_cases"] == 0
    assert summary["publication_precision_counts"]["DATE_ONLY"] == 1
    assert summary["publication_records"][0]["published_at"] == "2026-11-01"
    assert "date_only" in summary["unknown_counts_scope"]["review_eligible_unique_cases"]


def test_conservative_group_merges_text_and_community_window_transitively():
    rows = [known_row(i, text=text) for i, text in enumerate([
        "A conversion discarded annotations from three chapters.",
        "  A CONVERSION discarded annotations from three chapters. ",
        "Manually edited formulas to reassemble output.",
        "Graphic captions wrapped into the wrong paragraph.",
    ])]
    rows[2]["source_metadata"]["community"] = rows[1]["source_metadata"]["community"]
    rows[2]["document"]["published_at"] = "2026-11-07T00:00:00Z"
    rows[3]["source_metadata"]["community"] = rows[2]["source_metadata"]["community"]
    rows[3]["document"]["published_at"] = "2026-11-13T00:00:00Z"
    manifest = make_manifest(rows[:2], rows[2:])
    assert summarize_pilot(manifest, all_direct(manifest))["known_group_count"] == 1


def test_conflicting_alias_identity_does_not_inflate_evidence():
    first, alias = known_row(1), known_row(2)
    alias["document"]["source_url"] = first["document"]["source_url"] + "?utm_source=search"
    manifest = make_manifest([first], [alias])
    result = summarize_pilot(manifest, all_direct(manifest))
    assert result["combined_unique_cases"] == 1
    assert result["eligible_unique_cases"] == 0
    assert result["conflicted_eligible_case_count"] == 1
    assert result["verified_author_count"] == result["known_group_count"] == result["recent_case_count"] == 0
    assert "author" in result["conflicts"][0]["fields"]
    assert result["comparison_valid"] is False


def test_conflicting_verified_economic_alias_dispositions_are_not_positive_evidence():
    first = known_row(1, text="The conversion ruined footnotes. We would pay for restoration.")
    alias = deepcopy(first)
    alias["document"].update(document_id="alias", source_url=first["document"]["source_url"] + "#reply")
    alias["source_metadata"]["document_id"] = alias["extraction"]["document_id"] = "alias"
    manifest = make_manifest([first], [alias])
    review = all_direct(manifest)
    review["decisions"]["github:1"].update(economic_kind="DIRECT_WTP", economic_quote=quote_ref(first),
                                             economic_reason="WTP for restoration", loss_direct=True, loss_quote=quote_ref(first))
    review["decisions"]["alias"].update(economic_kind="NONE", economic_reason="No economic evidence found")
    result = summarize_pilot(manifest, review)
    assert result["direct_economic_count"] == 0
    assert result["loss_count"] == 0
    assert "economic_kind" in result["conflicts"][0]["fields"]
    assert result["conflicts"][0]["economic_dispositions"] == ["DIRECT_WTP", "NONE"]
    assert result["eligible_unique_cases"] == 0
    for arm in result["arms"].values():
        assert arm["direct_eligible_count"] == 0
        assert arm["direct_eligible_occurrence_count"] == 1
    # UNKNOWN is absence of an economic conclusion, not a conflicting denial.
    review["decisions"]["alias"].update(economic_kind="UNKNOWN", economic_reason="Not established")
    result = summarize_pilot(manifest, review)
    assert result["direct_economic_count"] == 1
    assert result["loss_count"] == 1  # False is not an explicit denial of loss.
    assert not result["conflicts"]


def test_gate_thresholds_and_deficits_are_exact_and_no_promotion():
    manifest = make_manifest([], [])
    result = summarize_pilot(manifest, all_direct(manifest))
    thresholds = {"verified_author_count": 5, "known_group_count": 3, "recent_case_count": 10,
                  "loss_count": 2, "direct_economic_count": 2, "representative_source_link_count": 3,
                  "counter_status": "NONE_CRITICAL"}
    assert result["gate_thresholds"] == thresholds
    assert {entry["gate"]: (entry["required"], entry["actual"]) for entry in result["gate_deficits"]} == {
        gate: (minimum, "NOT_ASSESSED" if gate == "counter_status" else 0) for gate, minimum in thresholds.items()}
    assert "decision" not in result


def test_counter_global_clearance_requires_all_cases_verified_and_assessed():
    a, b = known_row(1), known_row(2)
    manifest = make_manifest([a], [b])
    review = all_direct(manifest)
    review["decisions"]["github:1"]["counter_assessment"] = "NONE_CRITICAL"
    assert summarize_pilot(manifest, review)["counter_status"] == "NOT_ASSESSED"
    review["decisions"]["github:2"]["counter_assessment"] = "NONE_CRITICAL"
    assert summarize_pilot(manifest, review)["counter_status"] == "NONE_CRITICAL"
