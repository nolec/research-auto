# Demand Intelligence V1 Roadmap

> Updated: 2026-08-12
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

Primary progress metric: **0 / 500 valid real observations**

| Source | Valid real observations | Target |
|---|---:|---:|
| GitHub | 0 | 100 |
| Stack Exchange | 0 | 100 |
| Steam | 0 | 100 |
| YouTube | 0 | 100 |
| Reddit | 0 | 100 |
| **Total** | **0** | **500** |

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

### M2-A — GitHub First Real Data

The adapter layer stays deliberately small. Every adapter returns normalized `RawSourceItem` values and expresses `success`, `partial`, or `failed` in its result instead of terminating the run. Deterministic fixture tests are separated from the real network smoke command.

Definition of done:

- [x] Freeze the GitHub compliance decision from current official sources
- [x] Define the minimal adapter interface and isolated failure result
- [x] Freeze repository quotas, selection limits, and run-level request budgets
- [x] Add fixture-based GitHub Issue parsing and unknown-author policy tests
- [ ] Add run-scoped pagination, deduplication, author-limit, and rate-limit tests
- [ ] Complete a separate real GitHub API smoke collection
- [ ] Produce at least 10 valid real GitHub `RawSourceItem` records
- [ ] Verify source URL, publication time, collection run, manifest, and adapter provenance
- [ ] Verify PII minimization and raw-retention behavior on real responses

M2-A smoke status: **0 / 10 valid real GitHub records**

Current next action: implement run-scoped pagination and incremental selection so
cross-page duplicates and author limits are enforced until 10 valid items are reached.

Adapter implementation sequence:

`fixture parsing → pagination/deduplication test → real 5–10 item smoke → 100 valid items`

Do not wait for all five adapters to be complete before the first real smoke test. The main unknown is real source behavior, not the interface architecture.

### M2-B — 500 Raw Observations

- [ ] Freeze compliance decisions for the remaining four candidate sources
- [ ] Implement five source adapters with fixtures
- [ ] Add a rerunnable collection CLI and raw-fixture persistence
- [ ] Collect at least 100 valid records from each source
- [ ] Continue remaining sources when one source returns `partial` or `failed`

### M2-C — Source Quality Decision

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
