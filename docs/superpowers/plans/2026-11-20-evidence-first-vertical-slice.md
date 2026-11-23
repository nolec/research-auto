# Evidence-First Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-subagent-driven-development (recommended) or superpowers-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a real, bounded document-processing problem sample into a traceable, human-reviewable opportunity candidate and measure whether focused collection improves direct evidence yield.

**Architecture:** Preserve validated extraction; introduce an independently reviewed candidate-membership decision, bounded broad/focused manifests, conservative evidence accounting, and a local review packet. Do not promote a candidate through the fixture-oriented card builder.

**Tech Stack:** Python, pytest, existing extraction contracts, JSON, standard-library CLI and static HTML.

**Spec:** [Existing V1 PRD](../../prd.md), [V1 specification](../../v1-spec.md). The proposed scope amendment and slice contract below require approval before execution; the existing PRD remains authoritative.

## Scope amendment and motivation

The exploratory 80-document comparison suggested that separate-session LLM extraction can recover substantially more problems than the current rule baseline; it was not a human-gold or production-provider evaluation. Grouping 30 positives produced broad themes, not qualified opportunities. The small pandas pilot found 1/8 relevant broad cases versus 4/8 focused cases, but neither arm established willingness to pay, and sample selection/date limitations prevent generalization. Adjacent purchases or hiring budgets cannot establish payment for the exact candidate.

| Existing design | Decision in this slice |
|---|---|
| Public documents and exact source quotations | Keep; validate and preserve immutable source snapshots |
| Rule extraction and gated inference/calibration | Keep as baseline and production control; consume separately reviewed structured LLM output for the pilot only |
| Exact problem-key fixture grouping | Do not use as semantic clustering; propose one candidate and explicitly review membership |
| Broad collection | Keep as discovery and comparison arm; add bounded focused follow-up with explicit source/query approval |
| Evidence, actionability, review value as separate layers | Keep; expose missing inputs; never infer a passing decision from hit counts |
| PRD final thresholds and human audit | Keep unchanged; no ranking or promotion in this slice |

## Global Constraints

- First slice: one candidate in benign document conversion or documentation checking. No general-purpose research agent, autonomous network collection, or new connectors. Scope excludes security exploit research, sensitive/private sources and harmful domains.
- Use explicitly approved public records, locally imported snapshots and separately generated structured annotations. No production provider invocation, credential discovery, inference-gate bypass or claim of unattended execution.
- Broad/focused arms: at most 20 documents each; lock sampling method, source, date window, query and cap before reviewing outcomes, then hash the completed manifest before membership review. Equal reviewed denominators, report overlap separately. Compare only if matched; otherwise label descriptive only.
- Freeze `as_of` (timezone-aware) and manifest hash. A missing/invalid/future publication date cannot count toward the preceding 90 days. Do not fabricate author, source, source date or independent group identity.
- Existing quote validation and source metadata adapter stay intact. A human verifies source identity and quote meaning; candidate membership requires same relevant actor/task/failure, not just shared vocabulary.
- Deduplicate across arms; count unknown independence conservatively. Adjacent spend, salary, seller pricing, price complaints and loss alone do not count as direct willingness to pay, actual spending or paid substitute behavior for the candidate.
- No modifications to existing extraction calibration, card schema, PRD or dirty user files. Separate review artifact, always `HOLD`, never an official Opportunity Card or TOP 20 entry. Unknown actionability/growth remain unknown. The packet is local, readable and reproducible.
- Keep tests offline and deterministic; use explicit UTC test dates. Use existing project Python environment and installed dependencies; stop if missing. Scoped commits only when git write permission is actually available; report permission failure without bypassing it.

## Review Focus

1. Fabricated or mismatched provenance/quote → Task 1 rejects bad hashes, missing records and altered spans.
2. Over-merging superficially similar problems → Task 2 excludes adjacent and unreviewed observations.
3. Inflated recurrence or payment from duplicates, stale records or unrelated spend → Task 3 counts conservative independent cases and direct signals only.
4. Biased broad/focused comparison → Task 3 masks comparative claims on unmatched protocols or unequal denominators.
5. False promotion or unusable output → Task 4 checks HOLD, explicit gaps and HTML/source traceability, then produces an actual pilot receipt.

---

### Task 1: Immutable input and extraction validation

**Files:** Create `src/extraction/evidence_pilot.py`, `tests/extraction/test_evidence_pilot.py`.

**Contract:** `validate_manifest(manifest: dict) -> dict` returns a validated snapshot; `validate_row(row: dict) -> dict` returns the existing observation adapter result. Manifest keys: `run_id`, `as_of`, `candidate_id`, `source`, `window_start`, `window_end`, `arms` (`broad`/`focused`, each with `query`, `sampling_method`, `cap`, `rows`), `protocol_hash` (canonical SHA-256 over manifest without hash). Row keys: `document`, `extraction`, `source_metadata`, `source_verified`, `thread_id`, `event_id`; null allowed for unknown metadata. `document` and `extraction` use existing exact contracts, `source_metadata` uses existing adapter shape. Verified means a human compared source metadata against the preserved public record; never automatically true.

- [x] Write failing tests using a valid extraction fixture from `tests/extraction/test_development_slice.py` and a small manifest helper: `assert validate_row(row)["status"] == "OBSERVATION"`; alter one quoted character and assert `pytest.raises(ExtractionValidationError)`; alter a hashed manifest row and assert `pytest.raises(ValueError)`; also reject cap >20, dangling/duplicate row IDs within an arm, invalid public URLs and non-timezone-aware manifest timestamps.
- [x] Run `python -m pytest tests/extraction/test_evidence_pilot.py -q`; expect import failure before implementation.
- [x] Implement canonical hash validation, structural checks, explicit caps, source verification flag and existing `extraction_to_observation` delegation. No inference calls. Keep metadata unknown rather than inventing values; do not count unverified sources later.
- [x] Run the new tests plus `python -m pytest tests/extraction/test_development_slice.py tests/extraction/test_observation_adapter.py -q`; expect green.
- [ ] Commit only the two task files: `git add src/extraction/evidence_pilot.py tests/extraction/test_evidence_pilot.py && git commit -m "feat: validate bounded evidence pilot inputs"` (when permitted).

### Task 2: Candidate membership and human review

**Files:** Modify `src/extraction/evidence_pilot.py`, `tests/extraction/test_evidence_pilot.py`; create `docs/evidence-pilot-review-guide.md`.

**Contract:** `review_membership(manifest: dict, review: dict) -> list[dict]`. Review binds `protocol_hash`, `candidate_id`, `actor`, `task`, `failure`, `reviewer`, and per-document decisions keyed by document ID. Decisions include `membership` (`DIRECT`, `ADJACENT`, `REJECT`, `UNREVIEWED`), `reason`, `quote_meaning_verified`, `loss_direct`, `economic_kind` (`DIRECT_WTP`, `DIRECT_SPEND`, `DIRECT_PAID_SUBSTITUTE`, `ADJACENT`, `NONE`, `UNKNOWN`), `economic_reason`, `counter_signal`; explicit `counter_assessment` (`NOT_ASSESSED`, `NONE_CRITICAL`, `CRITICAL`, `UNCERTAIN`) and rationale. Each affirmative signal must point to validated quote spans; when one extraction quote cannot substantiate both, use a separate reviewed row/document or do not count the additional signal. Counter assessment is human-owned.

- [x] Add failing tests for vocabulary-overlap-but-different-task rejection fixture; assert `review_membership(...)[0]["membership"] == "ADJACENT"`; assert a missing decision defaults to `UNREVIEWED`; mismatched hash, unknown review ID or an affirmative signal with no validated supporting quotation raises `ValueError`. Test abstention cannot be DIRECT and reviewed but unverified source/meaning is not eligible for counts.
- [x] Run targeted pytest; expect missing function/assertion failures.
- [x] Implement review binding and explicit eligibility; document reviewer rubric with examples of direct buyer spending vs adjacent spend, and requirements for counter review. Preserve rejected rows for audit, do not silently delete.
- [x] Run targeted pytest; expect green.
- [ ] Scoped commit: `git add src/extraction/evidence_pilot.py tests/extraction/test_evidence_pilot.py docs/evidence-pilot-review-guide.md && git commit -m "feat: bind candidate membership to reviewed evidence"`.

### Task 3: Recurrence, economic evidence and comparison

**Files:** Modify `src/extraction/evidence_pilot.py`, `tests/extraction/test_evidence_pilot.py`.

**Contract:** `summarize_pilot(manifest: dict, review: dict) -> dict` returns per-arm reviewed denominator/direct eligible cases, overlap, combined unique cases, verified authors, conservative known groups, recent cases, loss count, direct economic count, source links, counter status, gate deficits, `comparison_valid`, `comparison_reason`. Group same author within source, thread, shared event, highly similar text or concentrated same-community window conservatively (transitive union; exact normalized text at minimum; uncertain similarity/group independence is not counted as independent). Report unknown counts. Inputs missing independence metadata are excluded from independent group counts. Count economic/loss observations at most once per conservative known group. Recent cases unique by document/canonical source, only verified eligible records with actual publication timestamps in window.

- [x] Add failing tests using fixed `as_of=2026-11-20T00:00:00Z`: old, future and null dates excluded; same author/thread repeated in both arms counts once globally; unknown metadata cannot increase independent counts; adjacent paid export or hiring budget cannot increase `direct_economic_count`; direct WTP in two known independent groups counts twice; counter `NOT_ASSESSED` remains explicit. Assert mismatched source/window, unequal reviewed denominators, or overlapping arms set `comparison_valid` false. Assert matched disjoint 1/8 and 4/8 returns counts without claiming statistical superiority.
- [x] Run targeted pytest; expect missing function/assertion failures.
- [x] Implement attributable accounting and deficits against the exact PRD minima: authors 5, groups 3, recent cases 10, losses 2, direct economic observations 2, representative links 3, assessed no critical counter-evidence. Missing and conflicting evidence visible separately. Do not output automated EVIDENCE_BACKED or ACTIONABLE. Comparison is descriptive even when protocol matches; no significance or causal claim.
- [x] Run targeted pytest and `python -m pytest tests/extraction/test_opportunity_slice.py -q`; expect green without changing the existing fixture path.
- [ ] Scoped commit: `git add src/extraction/evidence_pilot.py tests/extraction/test_evidence_pilot.py && git commit -m "feat: account for independent evidence and pilot yield"`.

### Task 4: Actual local research run and review packet

**Files:** Create `src/evidence_pilot_cli.py`, `tests/test_evidence_pilot_cli.py`, `docs/evidence-pilot-runbook.md`; produce real run files under `artifacts/evidence-pilot/<run_id>/` (`manifest.json`, `review.json`, `packet.json`, `index.html`, `receipt.json`). Do not modify existing console or experiment artifacts.

**Contract:** `python -m src.evidence_pilot_cli --manifest PATH --review PATH --out-dir PATH`. Validate before writing, refuse overwrite of a prior run, generate escaped static HTML with source links, source/quote and reasons, comparable arm counts, uncertainty, counter evidence, actionability `UNKNOWN`, growth `UNKNOWN`, decision `HOLD`, exact unmet gates, and explicit `PILOT_REVIEW_ONLY` label; no score or rank. Receipt records protocol/review hashes, artifact hashes, extraction mode, actual input counts, audit duration, and reviewer findings (null duration/findings until measured).

- [x] Write failing CLI tests: run against deterministic fixture then `assert packet["decision"] == "HOLD"`, `assert packet["grade"] == "PILOT_REVIEW_ONLY"`, `assert packet["actionability"] == "UNKNOWN"`, `assert "review_value" not in packet`; assert source URL and quote rendered, script-like source text escaped, malformed manifest creates no passing receipt, rerun refuses overwrite.
- [x] Run `python -m pytest tests/test_evidence_pilot_cli.py -q`; expect module missing failure.
- [x] Implement CLI and static output; run tests and full `python -m pytest -q`; report actual pass/fail counts, no claim if blocked.
- [ ] With approved public source selection, freeze one benign candidate and matched broad/focused protocol before sampling. Import actual source records with original links, dates and metadata when verified; obtain separate-session structured extractions and independent human review per rubric. If needed ask user to approve collection or review; do not substitute invented data. Run the CLI against this real input. Record actual reviewed count, direct matches, losses, paid behavior, evidence gaps, elapsed review time, source and extraction mode. If data access is blocked, record blocked and do not mark the pilot complete.
- [ ] Open generated `index.html` locally; confirm it renders, links and quotations are inspectable, and missing gates are easy to understand. Review one real candidate with the user and record actual audit duration; leave null until done. Acceptance is a real reviewable candidate even if HOLD, not a forced positive result.
- [ ] Scoped commit: `git add src/evidence_pilot_cli.py tests/test_evidence_pilot_cli.py docs/evidence-pilot-runbook.md && git commit -m "feat: render auditable pilot review packets"`; commit actual data only if permitted and appropriate under existing source-data retention policy.

## Exit decision and subsequent plans (not authorized by this plan)

**2026-11-21 execution checkpoint:** offline implementation and actual preliminary AI input run completed in the existing checkout with user approval (managed worktree creation failed; git metadata remains read-only). All four task reviews and final whole-change scoped review passed after fixes; full tests 1,187 passed, 1 skipped. `artifacts/evidence-pilot/docling-table-pilot-20261121/` contains the real packet and receipt. Broad retrieval returned no individual issue URLs; focused retrieval yielded eight, seven preliminarily direct, one adjacent/abstained, with seven outside the declared date window and date-only metadata for all eight. No human audit or verified payment evidence; comparison invalid, all seven PRD gate deficits reported, HOLD. Final code reproduces all five run artifacts byte-for-byte. Browser file URL was blocked by policy; HTML was parsed and artifact hashes verified, but visual inspection and human audit remain pending. Commits not attempted. No production provider used. The candidate is not an official Opportunity Card.

- **GO to production integration planning:** real packet is traceable, human reviewer can distinguish direct/adjacent evidence, comparison limitations are honest, and review reveals actionable improvements. No requirement that this candidate pass gates.
- **HOLD:** no eligible recurring problem/payment evidence, missing provenance, unmatched sampling, blocked access, or review not performed. Improve the failed stage before adding sources.
- Subsequent independent plans: approved live model-provider calibration; evaluate semantic clustering on labeled same/different pairs; approved collection integration with bounded resources; official Opportunity Card actionability/growth/scoring and frozen TOP 20 audit; compare against ChatGPT direct research with equal sources/time and blinded human evaluation.
- V1 finish line remains five audited EVIDENCE_BACKED + ACTIONABLE cards in TOP 20, ≥80% positive precision, ≤30% boundary error, ≤10% merge error, median audit ≤5 minutes. Neither a pilot packet nor passing unit tests establish these outcomes.

## Plan self-review

- PRD scope: preserved all gates and final metrics; focused follow-up is explicit proposed amendment; no premature scoring, production model claim or automatic promotion.
- Interfaces: manifest hash binds review; review binds per-document evidence; summary consumes both; CLI consumes summary and preserves source traces.
- Tests: each of the five review failure modes has a named owning task; synthetic tests are separate from the real-input acceptance step.
- Proportion: four tasks, one candidate, one local packet; separate plans handle production inference, general semantic clustering, collection infrastructure and final ranking. Existing work untouched.
