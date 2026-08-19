# Demand Intelligence V1 Roadmap

> Updated: 2026-08-19
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

Primary progress metric: **300 / 500 valid real observations**

| Source | Valid real observations | Target |
|---|---:|---:|
| GitHub | 100 | 100 |
| Stack Exchange | 100 | 100 |
| Steam | 100 | 100 |
| Reddit | 0 | 100 |
| TED | 0 | 100 |
| Naver Blog Search | 0 | blocked |
| **Total** | **300** | **500** |

Smoke collections are reported separately and do not increase this table unless they follow the frozen analysis manifest and strata.

Latest implementation checkpoint: TED official Search API transport, synthetic
wrapper fixture, bounded four-stratum query-syntax validation, aggregate-only
capacity executor primitives, and exact receipt validation are implemented on top
of the frozen capacity contract. The first real syntax-validation run failed closed
on TED's rejection of the frozen two-field sort, and the aggregate FAIL receipt now
preserves the original `http_400` termination. The full regression suite passes
**430 tests**.
Three source datasets are qualified;
source eligibility remains deferred because every independent secondary review is
still incomplete.

| Source | Primary review | Independent secondary | Canonical ingestion | Official eligibility |
|---|---:|---:|---|---|
| GitHub | 20 / 20 | 0 / 5 | blocked | deferred |
| Stack Exchange | 20 / 20 | 0 / 5 | blocked | deferred |
| Steam | 20 / 20 | 0 / 5 | blocked | deferred |
| YouTube | excluded | unavailable | unavailable | `NOT_ELIGIBLE` |
| Reddit | blocked before collection | unavailable | unavailable | `NOT_ELIGIBLE` (authorization unverified) |
| TED | feasibility passed | executor/receipt ready | unavailable | capacity probe required |
| Naver Blog Search | access smoke passed | unavailable | unavailable | blocked for persistent evidence use |

Immediate execution order:

1. Keep GitHub, Stack Exchange, and Steam thresholds, packets, and primary labels frozen.
2. Obtain five blind reviews per qualified source from reviewers who have not seen the
   corresponding primary labels.
3. Replace YouTube with the TED candidate because YouTube's 30-day API Data lifecycle and
   unresolved stable-author policy conflict with the frozen 90-day evidence contract.
4. Keep Reddit collection blocked while access, commercial reuse, automated-processing,
   and deletion clearance are unverified; select a separate fifth source if it stays blocked.
5. Revise and re-freeze the TED sort and syntax-success wrapper contract using the
   observed official API behavior, then rerun bounded four-stratum syntax validation
   without persisting raw queries or response bodies. Only a complete four-stratum
   PASS may route to the non-persistent capacity probe. Only a passing aggregate
   receipt may then route to notice parsing and a 10-record real smoke before its
   100-record run.
6. Keep Naver Blog Search blocked from the persistent Source Spike path after the
   credentialed access smoke. This is not a finding that non-commercial API calls are
   prohibited. The blocker is narrower: the official terms authorize search-result
   presentation but do not expressly authorize this product's separate corpus storage,
   automated extraction, and durable evidence outputs; they prohibit storage and processing
   outside the permitted API purpose. Re-entry requires written scope confirmation or a
   redesigned transient-discovery path that persists no API result content.
7. Run canonical ingestion, agreement, and development-only reports only after each
   source's independent secondary packet is complete.

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
- Source Spike analysis-ready observations: **300 / 500**
- GitHub blind primary packet: **20 / 20 — frozen**
- GitHub blind secondary packet: **5 / 5 — frozen**
- GitHub primary human labels: **20 / 20 — confirmed**
- GitHub secondary human labels: **0 / 5**
- Stack Exchange real smoke: **10 / 10 — qualified**
- Stack Exchange analysis-ready observations: **100 / 100 — qualified**
- Stack Exchange blind primary packet: **20 / 20 — frozen**
- Stack Exchange blind secondary packet: **5 / 5 — frozen**
- Stack Exchange label ingestion and development report CLI: **ready**
- Stack Exchange primary human labels: **20 / 20 — confirmed**
- Stack Exchange independent secondary human labels: **0 / 5**
- Steam compliance: **conditional / high-risk — frozen**
- Steam smoke manifest: **10 records across four product archetypes — frozen**
- Steam fixture smoke: **10 / 10 — qualified**
- Steam real smoke: **10 / 10 — qualified**
- Steam capacity probe: **38 / 38 per application — PASS, retained items 0**
- Steam analysis-ready observations: **100 / 100 — qualified**
- Steam labeling assignments: **20 primary / 5 secondary — frozen**
- Steam blind primary packet: **20 / 20 — frozen**
- Steam blind secondary packet: **5 / 5 — frozen**
- Steam offline primary/secondary review handoffs: **ready**
- Steam primary human labels: **20 / 20 — confirmed submission frozen**
- Steam independent secondary human labels: **0 / 5**
- TED current-collection feasibility: **PASS**
- TED future-commercial-reuse feasibility: **PASS**
- TED machine-readable next action: **`probe_capacity`**
- TED capacity manifest/query contract: **frozen and validated**
- TED probe allocation: **38 candidates × 4 CPV strata = 152 required unique candidates**
- TED probe window: **2026-05-20 inclusive → 2026-08-18 exclusive — frozen**
- TED official Search API transport: **implemented and regression-tested**
- TED synthetic multilingual response fixture: **ready; contains no real notice data**
- TED bounded retry, response-byte, deadline, and malformed-response handling: **ready**
- TED four-stratum query generator and bounded syntax validator: **implemented and regression-tested**
- TED first real query-syntax validation: **FAIL — frozen two-field sort rejected with `http_400`**
- TED observed syntax-success wrapper: **HTTP 200 with nullable `totalNoticeCount`; contract revision required**
- TED partial FAIL receipt: **qualified; original transport error preserved**
- TED aggregate-only capacity executor/receipt: **implemented and regression-tested**
- TED receipt privacy and numeric-boundary validation: **qualified**
- TED capacity probe: **pending**

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
GitHub, Stack Exchange, and Steam secondary reviews and run the non-persistent TED
capacity probe. All three primary reviews are
complete, but canonical ingestion remains blocked on independent secondary reviewers. Qualified
datasets and confirmed labels must not be retuned or silently replaced.

### M2-B3 — Steam First Real Data

Steam uses public English reviews from four product archetypes. The official
Steamworks review endpoint, conditional/high-risk compliance decision, 90-day window,
and unbiased recommendation/purchase filters are hash-frozen. HTML scraping is excluded.

M2-B3 smoke status: **10 / 10 — qualified**. Four requests produced the required
`3/3/2/2` sample without retries or rate-limit events; privacy qualification PASS.

M2-B3 analysis status: **100 / 100 — qualified**. The capacity probe passed at
`38/38/38/38` without retaining review records. The final balanced sample contains
25 reviews per product archetype and a deterministic 20-item assignment with 10
development, 10 holdout, and five secondary reviews. Collection fetched 500 payloads,
processed 328, accepted 100, and rejected 228 (`short_text` 227, `missing_body` 1).
This is an equal-weight experimental sample, not Steam-wide prevalence, and official
eligibility remains deferred. Its hash-bound blind packet is frozen at 20 primary and
five secondary assignments. Separate Korean offline review handoffs are ready; the
primary file does not request a secondary-independence assertion, while the secondary
file requires it. Split, document, author, playtime, and internal stratum metadata are
absent from both public packets.

### M2-B4 — YouTube Feasibility · Not eligible

YouTube was evaluated before adapter implementation and rejected under the conservative
source policy. Non-Authorized API Data must be deleted or refreshed within 30 days,
which conflicts with the product's frozen 90-day evidence window. Persistent author
derivation is not explicitly authorized, refresh can change or remove bytes bound to
review packets, and the project has no executable refresh/purge path.

Decision status: **NOT_ELIGIBLE**. Do not create an API key, fixture, adapter, smoke run,
or analysis dataset. Re-entry requires official compliance clearance or a verified
lifecycle that preserves 90-day evidence and author independence without prohibited
tracking. The next action is to select a replacement source.

### M2-B5 — Reddit Feasibility · Authorization unverified

Reddit is blocked before collection under a conservative engineering gate. Current
internal calibration and future commercial reuse are evaluated separately, and model
training/fine-tuning are distinguished from planned embedding, inference extraction,
and derived-output storage. The repository contains no verified access, commercial
reuse, or automated-processing authorization, and no executable derivative-deletion
path.

Decision status: **NOT_ELIGIBLE for current collection and future commercial reuse**.
This is not a permanent prohibition finding. Compliance routes to
`seek_compliance_clearance`, while Source Spike execution routes immediately to
`select_replacement_source`; no Reddit API, fixture, adapter, or smoke work begins.

### M2-B6 — TED Replacement Feasibility · Passed

TED is the preferred replacement candidate for the YouTube source slot. Its official
Search API permits anonymous access to published procurement notices for analysis and reuse,
and the legal notice permits commercial and non-commercial reuse unless otherwise stated.
The frozen contract excludes direct contact fields, attachments, unpublished notices, model
training, and fine-tuning.

Decision status: **PASS for current collection and future commercial reuse**. The
machine-readable route remains `probe_capacity`, not analysis collection. The official
Search API transport, synthetic OpenAPI-shaped fixture, bounded query-syntax validator,
aggregate-only executor primitives, and exact receipt validator are now implemented solely
to support a non-persistent capacity probe. The syntax validator deterministically builds
and hashes all four frozen stratum queries, requires the exact stable sort, fails closed on
unexpected success-wrapper fields, and retains no query text in its result. The first real
run failed at the first stratum because TED rejected the frozen per-field direction syntax
after the first `DESC`; a single-field descending sort reached the syntax-success HTTP 200
path, where `totalNoticeCount` was nullable. These observations require an explicit contract
revision rather than an implicit runtime fallback. The receipt is
UUID/hash-bound, rejects raw-field expansion and non-finite numeric
values, and retains zero notice text or author identifiers. Notice persistence and smoke
execution remain blocked until an actual probe receipt passes. Smoke data will
not increase the **300 / 500** analysis-ready progress metric.

The capacity probe contract is now frozen before network execution. It requires 38 unique
candidates in each of four CPV strata (`48`, `79`, `85`, `50`), for 152 candidates total,
using the fixed 90-day window and deterministic sort. API fields, contact-field exclusions,
privacy behavior, quality thresholds, pagination, retry limits, and request budgets are
hash-bound and validated against immutable values. The validator rejects feasibility drift,
query/window drift, field-policy weakening, and threshold or budget rehashing before any
request is made. The transport targets the official `/v3/notices/search` endpoint, executes
the query rather than syntax-checking it, preserves multilingual wrapper data only in memory,
and fails closed on malformed or non-finite JSON. The aggregate-only execution state,
selection/deduplication rules, pagination continuity checks, shared request/deadline/byte
budgets, and PASS/FAIL receipt contract are implemented and regression-tested. The next
milestone is to revise and re-freeze the deterministic sort and nullable syntax-success
wrapper contract, obtain a complete real four-stratum syntax-validation PASS, then execute
the non-persistent capacity probe and preserve only its validated aggregate receipt.

### M2-B7 — Naver Blog Search Feasibility · Persistent use blocked

Naver Blog Search was evaluated as a possible replacement for Reddit. Project-local API
credentials were registered and a non-persistent one-item access smoke returned HTTP 200
with the required result fields. No credentials, query text, response body, or result item
were persisted by the smoke.

The current official NAVER API terms do not clearly authorize this product's evidence
contract. General condition 7.3 prohibits copying, storage (including caching), processing,
distribution, and third-party provision outside the permitted API scope. Search-specific
condition 2.1 describes faithful, independent exposure of search results, but does not grant
an explicit right to build a separate persistent analysis corpus. Result rights remain with
NAVER or the original rightsholder. This conclusion is about persistent evidence use, not
about ordinary non-commercial API calls. The API is also migrating from NAVER Developers to
NAVER API HUB, with the legacy Search API scheduled to end on 2027-06-30.

Decision status: **BLOCKED for the current persistent Source Spike design**. Do not create a
stored smoke corpus or analysis dataset. Re-entry requires authoritative scope confirmation
for persistent storage, automated extraction/indexing, and derived-output retention. A
separate transient discovery adapter may be evaluated only if it stores no API result text,
uses NAVER results solely to locate canonical originals, and evaluates those originals under
their own access and reuse rules. Future commercial operation remains a separate horizon.

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
- [x] Freeze TED dual-horizon feasibility and route it through a capacity probe
- [x] Freeze the TED capacity allocation, query, privacy, threshold, and request-budget contract
- [x] Implement the TED official Search API transport and synthetic response fixture
- [x] Implement deterministic TED query generation and bounded four-stratum syntax validation
- [x] Execute the first real TED syntax validation and preserve its aggregate FAIL receipt
- [x] Qualify partial FAIL receipts to preserve the original transport termination
- [x] Implement the TED aggregate-only capacity executor and exact PASS/FAIL receipt validation
- [x] Freeze Stack Exchange compliance and complete its real 10-record smoke
- [x] Freeze Steam compliance for official public-review endpoint use only
- [x] Evaluate YouTube lifecycle feasibility and mark it **NOT_ELIGIBLE** before collection
- [x] Evaluate Reddit dual-horizon feasibility and block collection while authorization is unverified
- [x] Verify Naver Blog Search credentials with a non-persistent access smoke and block persistent collection pending scope clearance or transient-path redesign
- [x] Freeze the Steam four-archetype `3/3/2/2` smoke manifest and 90-day window
- [x] Complete Steam fixture parsing and valid-count collection at **10 / 10**
- [x] Complete Steam real API smoke with **10 / 10** valid reviews and privacy PASS
- [x] Pass the Steam hash-bound capacity probe at **38 / 38** per application
- [x] Collect and qualify the balanced Steam **100 / 100** analysis sample
- [x] Collect and qualify the balanced Stack Exchange 100-record analysis sample
- [ ] Pass TED real query-syntax validation for all four frozen strata
- [ ] Pass the TED non-persistent capacity probe
- [ ] Implement the remaining source adapters with fixtures
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
- [x] Generate Steam blind primary/secondary packets and separate offline handoffs
- [x] Complete and freeze Steam primary human review at **20 / 20**
- [x] Add a machine-readable feasibility gate and freeze the YouTube rejection decision
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
