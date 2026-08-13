# Demand Intelligence V1 Roadmap

> Updated: 2026-08-13
> Status: Task 1 complete, Task 2 in progress

This roadmap tracks implementation progress. Product goals and decision policy remain authoritative in [`prd.md`](prd.md); machine-readable contracts remain authoritative in `schemas/`.

## Four-week objective

Freeze the model, prompts, policy, and thresholds before the final evaluation. V1 succeeds when the frozen run's TOP 20 contains at least five unique opportunities that remain both `EVIDENCE_BACKED` and `ACTIONABLE` after a human audit, with at least 80% automatic positive precision and a median audit time of five minutes or less.

## Current milestone

### Task 1 — Opportunity Card contract · Complete

- [x] Evidence and Opportunity Card JSON schemas
- [x] Evidence Status, Actionability Status, and Review Value policy
- [x] Evidence independence and counter-evidence rules
- [x] Human audit and four-week success criteria
- [x] Contract validation tests

### Task 2 — Source Spike · In progress

Goal: evaluate five structurally different public sources with at least 100 normalized records per source, then select three V1 sources using measured evidence quality rather than intuition.

Primary progress metric: **200 / 500 valid real observations**

| Source | Valid real observations | Target |
|---|---:|---:|
| GitHub | 100 | 100 |
| Stack Exchange | 100 | 100 |
| Steam | 0 | 100 |
| YouTube | 0 | 100 |
| Reddit | 0 | 100 |
| **Total** | **200** | **500** |

Smoke collections are reported separately and do not increase this table unless they follow the frozen analysis manifest and strata.

Completed foundation:

- [x] Source Spike manifest and compliance contracts
- [x] Source evaluation metrics and selection-gate logic
- [x] Common privacy-safe `RawSourceItem` contract
- [x] Observation-unit selection, normalization, deduplication, and author hashing rules
- [x] Deterministic 20-item screening sample per source
- [x] Development/holdout split of 10/10 per source
- [x] Five double-review assignments per source
- [x] Human-label schema and labeling guide
- [x] Minimal source adapter and collection-result contracts
- [x] Per-source runner failure isolation and provenance validation
- [x] Frozen GitHub 10-record smoke manifest and validation contract
- [x] Privacy-safe GitHub Issue fixture parser and rejection reasons
- [x] Run-scoped incremental deduplication and author-limit state
- [x] Immutable GitHub fixture transport page and protocol contracts
- [x] Valid-count fixture collection loop with repository quotas and run budgets
- [x] Source-neutral segment results, termination reasons, and provenance hashes
- [x] GitHub fixture smoke qualification: 10/10 with 5/5 records per repository

### M2-A — GitHub First Real Data

The adapter layer stays deliberately small. Every adapter returns normalized `RawSourceItem` values and expresses `success`, `partial`, or `failed` in its result instead of terminating the run. Deterministic fixture tests are separated from the real network smoke command.

Definition of done:

- [x] Freeze the GitHub compliance decision from current official sources
- [x] Define the minimal adapter interface and isolated failure result
- [x] Freeze repository quotas, selection limits, and run-level request budgets
- [x] Add fixture-based GitHub Issue parsing and unknown-author policy tests
- [x] Add run-scoped cross-page deduplication and author-limit primitives
- [x] Define the immutable fixture transport page and request protocol
- [x] Add valid-count pagination, repository quota, and request/page budget tests
- [x] Preserve parser and selector rejection order with fetched/processed metrics
- [x] Complete fixture smoke with 10 valid records and 5/5 repository quotas
- [x] Add the real HTTP transport with retry and rate-limit handling
- [x] Complete a separate real GitHub API smoke collection
- [x] Produce at least 10 valid real GitHub `RawSourceItem` records
- [x] Verify source URL, publication time, collection run, manifest, and adapter provenance
- [x] Verify PII minimization and raw-retention behavior on real responses

M2-A fixture status: **10 / 10 valid fixture records — qualified**

M2-A real smoke status: **10 / 10 valid real GitHub records — qualified**

Latest qualification verification: **210 tests passed**, collection-result schema and
TDD gate passed, and the sanitized artifacts retained no raw identity, token, or full
API payload. The project-local author-hash secret is explicitly initialized, Git-ignored,
stored with mode `0600`, and rejected if it becomes a symlink or non-regular file.

Current real-data progress:

- GitHub smoke qualification: **10 / 10**
- GitHub analysis-ready observations: **100 / 100 — qualified**
- Source Spike analysis-ready observations: **200 / 500**
- GitHub blind primary packet: **20 / 20 — frozen**
- GitHub blind secondary packet: **5 / 5 — frozen**
- GitHub primary human labels: **20 / 20 — confirmed**
- GitHub secondary human labels: **0 / 5**
- Stack Exchange real smoke: **10 / 10 — qualified**
- Stack Exchange analysis-ready observations: **100 / 100 — qualified**
- Stack Exchange blind primary packet: **20 / 20 — frozen**
- Stack Exchange blind secondary packet: **5 / 5 — frozen**
- Stack Exchange label ingestion and development report CLI: **ready**
- Stack Exchange human labels: **0 / 20 primary, 0 / 5 secondary**

GitHub analysis qualification uses a frozen `published_before` boundary and four
repository archetypes at 25 records each. The local-only run bundle contains a
dataset hash, privacy qualification, and a deterministic 20-item labeling sample
with 10 development, 10 holdout, and five double-review assignments.

The local-only blind review bundle is hash-frozen against the qualified GitHub
dataset. Development and holdout identities remain in the internal map only; the
holdout labels will be physically sealed at ingestion. Ingestion revalidates the
frozen packet and assignment-map hashes, preserves assignment-level context-use audit
metadata, and rejects incomplete or non-independent reviews. Development reporting
accepts only schema-valid development labels with 10 unique primary records and five
independent secondary pairs. Current next actions are to complete the independent
GitHub secondary review, obtain Stack Exchange primary and secondary human labels
from its frozen blind packet, and freeze compliance for the third source. Qualified
datasets and confirmed labels must not be retuned or silently replaced.

### M2-B2 — Stack Exchange First Real Data

Stack Exchange uses questions as the observation unit and treats four sites as smoke
transport-coverage strata rather than source-quality samples. The official API,
conditional compliance decision, immutable safe custom filter, 90-day window, and
quota/backoff budgets are hash-frozen before collection.

- [x] Freeze the official API compliance and attribution decision
- [x] Create and independently re-read an immutable safe custom filter
- [x] Freeze the four-site `3/3/2/2` smoke manifest and 90-day window
- [x] Add deterministic HTML-to-text normalization and privacy-safe question parsing
- [x] Add valid-count collection with deduplication and author limits
- [x] Enforce method-global backoff, `Retry-After`, request/attempt/deadline budgets,
  and quota reserve termination
- [x] Complete real API smoke with **10 / 10** valid questions
- [x] Verify content-license completeness, attribution, privacy, and provenance
- [x] Pass the final review and full **251-test** regression suite

M2-B2 real smoke status: **10 / 10 — qualified**

Qualification result: `stackoverflow 3/3`, `superuser 3/3`, `serverfault 2/2`,
`softwareengineering 2/2`; four requests, no retries or backoffs, final API quota
remaining 294, content-license completeness PASS, privacy PASS. Smoke records do not
increase analysis progress.

M2-B2 analysis status: **100 / 100 — qualified**. A hash-bound capacity probe
required `ceil(25 × 1.5) = 38` valid candidates per site and passed at `38/38/38/38`
without retaining probe records. The qualified balanced sample contains 25 questions
from each site, license and privacy qualification PASS, and a separate blind packet
with 20 primary and five secondary assignments. This equal-weight sample must not be
interpreted as Stack Exchange-wide prevalence; official eligibility remains deferred
until human labels and site-level results are available. The Stack Exchange labeling
CLI now supports packet generation, strict human-label ingestion, and development-only
density/agreement reporting. It rejects stale qualified provenance, non-Stack Exchange
packets, malformed authority files, incomplete reviews, and non-independent secondary
reviews while keeping holdout labels physically sealed.

Adapter implementation sequence:

`fixture parsing ✓ → pagination/deduplication test ✓ → real 10-item smoke ✓ → capacity receipt ✓ → 100 valid items ✓ → blind packet ✓`

Do not wait for all five adapters to be complete before the first real smoke test. The main unknown is real source behavior, not the interface architecture.

### M2-B — 500 Raw Observations

- [x] Freeze the GitHub 100-record analysis manifest and time boundary
- [x] Collect 100 valid GitHub records across four 25-record archetype strata
- [x] Produce a privacy-qualified, hash-addressed local run bundle
- [x] Produce the stratified 20-item GitHub labeling assignment
- [ ] Freeze compliance decisions for the remaining three candidate sources
- [x] Freeze Stack Exchange compliance and complete its real 10-record smoke
- [x] Collect and qualify the balanced Stack Exchange 100-record analysis sample
- [ ] Implement the remaining three source adapters with fixtures
- [ ] Add a rerunnable collection CLI and raw-fixture persistence
- [ ] Collect at least 100 valid records from each source
- [ ] Continue remaining sources when one source returns `partial` or `failed`

### M2-C — Source Quality Decision

- [x] Generate a blind, hash-frozen GitHub review packet for 20 primary and five secondary reviews
- [x] Add strict blind-label ingestion with physical development/holdout separation
- [x] Revalidate packet integrity at ingestion and preserve hash-addressed review audit metadata
- [x] Add development-only Wilson density and descriptive agreement reporting
- [x] Reject holdout, duplicate, incomplete, and non-independent development report inputs
- [x] Connect Stack Exchange packet, ingestion, and development-report CLI surfaces
- [x] Gate holdout unsealing on an explicit freeze receipt
- [ ] Produce accessibility, freshness, identity, continuity, cost, and compliance observations
- [ ] Complete primary labels for at least 20 records per source and secondary labels for five
- [ ] Calculate problem, money, usable-evidence, and noise densities with agreement statistics
- [ ] Apply the preregistered selection gate and document the three selected V1 sources

Task 2 is complete only when the result table, labeled dataset, source decision, and reproducible collection artifacts all exist. A failed source must not stop the other source experiments.

From M2-A onward, test count is a safety signal rather than the progress metric. Every implementation update must report smoke records separately from analysis-ready observations by source and the total out of 500.

## Following milestones

### Task 3 — Problem and evidence extraction

- [ ] Define structured extraction output and prompt versioning
- [ ] Build extraction for the three selected sources
- [ ] Evaluate against the Task 2 development set without opening the holdout
- [ ] Freeze an extractor candidate and report holdout precision/error classes

### Task 4 — Problem clustering and evidence independence

- [ ] Normalize problem statements and generate candidate clusters
- [ ] Implement conservative author, thread, time-window, text, and event grouping
- [ ] Measure merge errors on a human-audited sample
- [ ] Block scoring if audited merge error exceeds 10%

### Task 5 — Evidence and actionability decisions

- [ ] Implement the provisional EVIDENCE-BACKED gate
- [ ] Implement ACTIONABLE, NOT_ACTIONABLE, and UNKNOWN decisions
- [ ] Preserve counter-evidence, blockers, and uncertainty
- [ ] Add policy-versioned decision fixtures and boundary tests

### Task 6 — Ranking and Opportunity Card output

- [ ] Implement Review Value and penalties after eligibility gates
- [ ] Generate evidence-linked JSON and Markdown Opportunity Cards
- [ ] Produce TOP 20, five boundary candidates, and five stratified random candidates
- [ ] Verify unsupported claims cannot affect scoring

### Task 7 — Frozen four-week evaluation

- [ ] Freeze source set, model, prompts, policy, and thresholds
- [ ] Run the final evaluation without tuning on audit results
- [ ] Audit each card in five minutes or less
- [ ] Report yield, positive precision, boundary error, merge error, and audit time
- [ ] Decide whether to proceed, recalibrate the system, or revise source selection

## Explicitly deferred

Dashboard work, external SaaS features, interview-dependent validation, deep research, automatic MVP design, country-gap analysis, unsupported market sizing, and automatic investment decisions remain outside V1.
