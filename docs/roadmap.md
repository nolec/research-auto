# Demand Intelligence V1 Roadmap

> Updated: 2026-08-28
> Status: Task 1 complete, Task 2 frozen at 400/500, Task 3 bounded provider-preflight implementation complete; live preflight pending

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

### Task 2 — Source Spike · Frozen at 400 / 500

Original goal: evaluate five structurally different public sources with at least 100 normalized records per source, then select three V1 sources using measured evidence quality rather than intuition. The fifth-source search is now deferred: four qualified archetypes and 400 real observations are sufficient to test whether the downstream product path produces useful structured evidence. Source selection remains unfinished and no source has official eligibility.

Primary progress metric: **400 / 500 valid real observations**

| Source | Valid real observations | Target |
|---|---:|---:|
| GitHub | 100 | 100 |
| Stack Exchange | 100 | 100 |
| Steam | 100 | 100 |
| Reddit | 0 | 100 |
| TED | 100 | 100 |
| Naver Blog Search | 0 | blocked |
| **Total** | **400** | **500** |

Smoke collections are reported separately and do not increase this table unless they follow the frozen analysis manifest and strata.

Latest implementation checkpoint: TED passed official Search API syntax validation,
aggregate-only capacity, real smoke, and the final privacy-qualified analysis run. The
analysis dataset contains **100 / 100** valid notices balanced at 25 records across each of
four frozen CPV strata. Contact redaction removed one observed contact candidate, residual
contact scanning passed, and no raw buyer identifiers or payloads were retained. The local
authorization is mode `0600` and exactly bound to the qualified smoke receipt. A deterministic
20-item labeling sample with 10 development, 10 source-spike-reserved, and five secondary assignments is
ready. The full regression suite passes **518 tests** with one intentional local-custody
integration skip. Four source datasets are qualified;
source eligibility remains deferred because every independent secondary review is
still incomplete.

| Source | Primary review | Independent secondary | Canonical ingestion | Official eligibility |
|---|---:|---:|---|---|
| GitHub | 20 / 20 | 0 / 5 | blocked | deferred |
| Stack Exchange | 20 / 20 | 0 / 5 | blocked | deferred |
| Steam | 20 / 20 | 0 / 5 | blocked | deferred |
| YouTube | excluded | unavailable | unavailable | `NOT_ELIGIBLE` |
| Reddit | blocked before collection | unavailable | unavailable | `NOT_ELIGIBLE` (authorization unverified) |
| TED | 20 / 20 | 0 / 5 (handoff ready) | blocked | analysis qualified; eligibility deferred |
| Naver Blog Search | access smoke passed | unavailable | unavailable | blocked for persistent evidence use |
| CFPB complaints | feasibility reviewed | unavailable | unavailable | `NOT_ELIGIBLE` (no public author identity) |
| CPSC SaferProducts | feasibility reviewed | unavailable | unavailable | `NOT_ELIGIBLE` (no public author identity) |
| Wikimedia Phabricator | anonymous preflight failed | unavailable | unavailable | blocked (`authentication_required`) |

Immediate execution order after the product-scope correction:

1. Keep all four qualified datasets, packets, thresholds, and confirmed primary labels frozen.
2. Treat the original 10-per-source `holdout` assignment as `source_spike_reserved`: it has
   already been exposed during human review and is not an independent extractor evaluation set.
3. Use only the 40 development-calibration records for the first extraction slice, with
   inference documents and human gold physically separated at the public API boundary.
4. Freeze an inference profile and run the first real structured extraction only after its
   model, prompt, schema, request budget, and secret policy are explicit.
5. Continue independent secondary reviews as a parallel Source Spike workstream; they remain
   mandatory for canonical source-quality reporting but no longer block Task 3 calibration.
6. Keep the fifth-source search deferred until the downstream vertical slice shows that more
   source diversity is a real bottleneck. Reddit and Wikimedia Phabricator remain blocked.
7. Keep Naver Blog Search blocked from the persistent Source Spike path after the
   credentialed access smoke. This is not a finding that non-commercial API calls are
   prohibited. The blocker is narrower: the official terms authorize search-result
   presentation but do not expressly authorize this product's separate corpus storage,
   automated extraction, and durable evidence outputs; they prohibit storage and processing
   outside the permitted API purpose. Re-entry requires written scope confirmation or a
   redesigned transient-discovery path that persists no API result content.
8. Run canonical ingestion, agreement, and development-only reports only after each
   source's independent secondary packet is complete.
9. Keep Wikimedia Phabricator capacity work blocked after the anonymous Conduit preflight
   returned HTTP 200 with `ERR-INVALID-SESSION`. CFPB and CPSC remain
   excluded from the frozen five-source experiment because their public records cannot
   establish stable cross-run author independence. Do not create or use an API token as an
   implicit fallback; token-based access requires a separate authorization and secret-lifecycle
   decision before any new plan.

Completed foundation:

- [x] Source Spike manifest and compliance contracts
- [x] Source evaluation metrics and selection-gate logic
- [x] Common privacy-safe `RawSourceItem` contract
- [x] Observation-unit selection, normalization, deduplication, and author hashing rules
- [x] Deterministic 20-item screening sample per source
- [x] Development/source-spike-reserved assignment of 10/10 per source
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
- Source Spike analysis-ready observations: **400 / 500**
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
- TED smoke authorization/manifest: **hash-bound and frozen**
- TED capacity manifest/query contract: **frozen and validated**
- TED probe allocation: **38 candidates × 4 CPV strata = 152 required unique candidates**
- TED probe window: **2026-05-20 inclusive → 2026-08-18 exclusive — frozen**
- TED official Search API transport: **implemented and regression-tested**
- TED synthetic multilingual response fixture: **ready; contains no real notice data**
- TED bounded retry, response-byte, deadline, and malformed-response handling: **ready**
- TED four-stratum query generator and bounded syntax validator: **implemented and regression-tested**
- TED initial query-syntax validation: **historical FAIL — two-field sort rejected with `http_400`**
- TED revised query contract: **single-field `publication-date DESC`, version 1.1.0 — frozen**
- TED real query-syntax validation: **4 / 4 PASS — zero retries, aggregate-only receipt qualified**
- TED receipt compatibility: **historical 1.0 validation preserved; capacity gate requires 1.1**
- TED partial FAIL receipt: **qualified; original transport error preserved**
- TED aggregate-only capacity executor/receipt: **implemented and regression-tested**
- TED receipt privacy and numeric-boundary validation: **qualified**
- TED capacity probe: **38 / 38 / 38 / 38 — PASS, retained items 0**
- TED real smoke: **10 / 10 — qualified at 3 / 3 / 2 / 2, privacy PASS**
- TED smoke qualification schema: **frozen; authorization, references, transport, provenance, and privacy validated**
- TED analysis authorization: **local-only, mode `0600`, exact smoke receipt binding PASS**
- TED analysis-ready observations: **100 / 100 — qualified at 25 / 25 / 25 / 25**
- TED publication-date normalization: **100 / 100 preserved as UTC calendar-date midnight**
- TED contact privacy qualification: **PASS — 1 contact candidate redacted, residual 0**
- TED labeling assignments: **20 primary / 5 secondary — deterministic and frozen**
- TED blind packet: **primary 20 / secondary 5 — hash-frozen and idempotent**
- TED external handoffs: **primary and secondary isolated by exact two-file allowlists**
- TED human review: **primary 20 / 20 confirmed, independent secondary 0 / 5**

GitHub analysis qualification uses a frozen `published_before` boundary and four
repository archetypes at 25 records each. The local-only run bundle contains a
dataset hash, privacy qualification, and a deterministic 20-item labeling sample
with 10 development, 10 source-spike-reserved, and five double-review assignments.

The local-only blind review bundle is hash-frozen against the qualified GitHub
dataset. Development and source-spike-reserved identities remain in the internal map only;
reserved labels remain physically sealed at ingestion. They preserve Source Spike audit
history but are not an independent Task 3 evaluation set because their documents and primary
judgments were exposed during human review. Ingestion revalidates the
frozen packet and assignment-map hashes, preserves assignment-level context-use audit
metadata, and rejects incomplete or non-independent reviews. Development reporting
accepts only schema-valid development labels with 10 unique primary records and five
independent secondary pairs. Current parallel Source Spike action is to complete the
independent GitHub, Stack Exchange, Steam, and TED secondary reviews. All four primary reviews
are complete, but canonical ingestion remains blocked on independent secondary reviewers. Qualified
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

Decision status: **CAPACITY PASS for current collection and future commercial reuse**. The
machine-readable route remains `probe_capacity`, not analysis collection. The official
Search API transport, synthetic OpenAPI-shaped fixture, bounded query-syntax validator,
aggregate-only executor, and exact receipt validator are implemented. The syntax validator
deterministically builds and hashes all four frozen stratum queries, requires the exact stable
sort, fails closed on unexpected success-wrapper fields, and retains no query text. Contract
version 1.1.0 freezes the observed-compatible single-field descending sort and accepts nullable
`totalNoticeCount` only for syntax checking. The qualified syntax receipt now gates every
capacity request by exact stratum order and query hash.

The first capacity execution exposed the live API publication-date boundary
(`YYYY-MM-DD±HH:MM`) and terminated at the shared response-byte budget with zero accepted
records; this remains historical aggregate-only evidence. After adding strict support for that
shape, the runner was tightened so notice, procedure, and buyer limits are shared across all
four strata rather than reset at each stratum. The replacement bounded run
`6c4c5ecc-15e3-4a49-9087-0d07f2b8319b` passed at **38 / 38 / 38 / 38** while rejecting five
cross-stratum duplicate notices and one cross-stratum buyer-limit collision. It used four
logical requests and four HTTP attempts, no retries, rate-limit events, transport errors,
repeated pages, or deadline exhaustion, and retained zero notice text or author identifiers.
The hash-bound authorization and smoke manifest then qualified a **10 / 10** live smoke at
the frozen `3 / 3 / 2 / 2` quotas. Four logical requests and four attempts reached
`target_reached` with zero retries, rate-limit events, transport errors, retained items,
raw text, or raw author persistence. Smoke records do not increase the **300 / 500**
analysis-ready progress metric.

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
budgets, qualified-query identity gate, and PASS/FAIL receipt contract are implemented,
regression-tested, and live-qualified. The smoke authorization, exact receipt binding,
manifest, notice parser, compound-buyer hashing, global deduplication, individual-buyer
limit, and aggregate-only qualification report are also regression-tested and live-qualified.
The smoke reuses the capacity selection contract for publication window, notice/form scope,
CPV stratum, change-notice exclusion, global notice/procedure deduplication, and buyer limits.
The final qualification artifact is schema-valid and binds the smoke, capacity, and
authorization hashes before it can be persisted as PASS.
TED analysis is qualified at **100 / 100**. Its next milestone is a blind primary/secondary
review handoff followed by the same gated canonical-ingestion process used for other sources.

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

### M2-B8 — Fifth Persistent Source Shortlist · Phabricator selected for capacity

The fixed three-candidate comparison evaluated CFPB complaints, CPSC SaferProducts, and
Wikimedia Phabricator without collecting a corpus. CFPB and CPSC provide unusually strong
public complaint data and reuse paths, but neither publishes a stable submitter identifier;
a report or complaint ID cannot prove distinct authors under the frozen contract.

Wikimedia Phabricator is the only candidate that preserves official API access, persistent
reuse with attribution, canonical task identity, timestamps, and stable public author
identity. It is selected only for an aggregate-only capacity probe. Its similarity to GitHub
and probable lack of direct money signals remain explicit source-value risks to measure, not
reasons to weaken the feasibility gate.

Decision status: **ANONYMOUS API SHAPE PREFLIGHT FAILED — CAPACITY BLOCKED**. The bounded
one-request run received HTTP 200 with Conduit error `ERR-INVALID-SESSION`, classified as
`authentication_required`. It observed no tasks, made no canonical checks, and persisted no
query, response body, task text, username, or PHID. The validated local aggregate receipt is
ignored by Git under `artifacts/source-spike/`. Receipt integrity is hardened so the shared
response-byte budget covers both API and canonical reads, while PASS validation requires exact
wrapper/cursor shape and consistent observed-task, canonical-check, and request counts. Do not
create an adapter, fixture, smoke corpus, analysis dataset, or API token as part of this path.
Re-entry requires a separate decision explicitly authorizing token-based access and its secret
lifecycle.

Decision record: [`decisions/fifth-source-shortlist.md`](decisions/fifth-source-shortlist.md)

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
- [x] Compare CFPB, CPSC, and Wikimedia Phabricator under the frozen fifth-source feasibility gate
- [x] Select Wikimedia Phabricator for a separate aggregate-only capacity plan
- [x] Execute the bounded Wikimedia Phabricator anonymous API shape preflight and preserve its validated `authentication_required` FAIL receipt
- [x] Harden the Phabricator preflight shared byte budget and PASS receipt consistency gate
- [ ] Decide whether token-based Wikimedia Phabricator access is authorized and worth pursuing
- [x] Freeze the Steam four-archetype `3/3/2/2` smoke manifest and 90-day window
- [x] Complete Steam fixture parsing and valid-count collection at **10 / 10**
- [x] Complete Steam real API smoke with **10 / 10** valid reviews and privacy PASS
- [x] Pass the Steam hash-bound capacity probe at **38 / 38** per application
- [x] Collect and qualify the balanced Steam **100 / 100** analysis sample
- [x] Collect and qualify the balanced Stack Exchange 100-record analysis sample
- [x] Pass TED real query-syntax validation for all four frozen strata
- [x] Pass the TED non-persistent capacity probe at **38 / 38 / 38 / 38** with zero retained items
- [x] Freeze the TED smoke authorization and exact `3/3/2/2` manifest
- [x] Complete TED real API smoke with **10 / 10** valid notices and privacy PASS
- [x] Collect and qualify the balanced TED **100 / 100** analysis sample
- [x] Generate the TED hash-frozen primary 20/secondary 5 blind packet and isolated handoffs
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
- [x] Generate TED blind primary/secondary packets with allowlisted isolated offline handoffs
- [x] Complete and freeze GitHub primary human review at **20 / 20**
- [x] Complete and freeze Stack Exchange primary human review at **20 / 20**
- [x] Complete and freeze Steam primary human review at **20 / 20**
- [x] Complete and freeze TED primary human review at **20 / 20**
- [x] Add a machine-readable feasibility gate and freeze the YouTube rejection decision
- [x] Gate holdout unsealing on an explicit freeze receipt
- [ ] Produce accessibility, freshness, identity, continuity, cost, and compliance observations
- [ ] Complete five independent secondary labels for each of the four qualified sources
- [ ] Calculate problem, money, usable-evidence, and noise densities with agreement statistics
- [ ] Apply the preregistered selection gate and document the three selected V1 sources

Task 2 is frozen rather than complete. Its remaining completion conditions are independent
secondary reviews, canonical source-quality reports, and a documented V1 source decision.
The fifth 100-record source is deferred pending evidence that the Task 3 product path needs it.

From M2-A onward, test count is a safety signal rather than the progress metric. Every implementation update must report smoke records separately from analysis-ready observations by source and the total out of 500.

## Following milestones

### Task 3 — Problem and evidence extraction · Calibration foundation in progress

Current code checkpoint:

- [x] Build a deterministic 40-record development projection at 10 records per qualified source
- [x] Separate the gold-free inference corpus from the human-label sidecar at the public API boundary
- [x] Verify qualified dataset hashes, frozen packet hashes, assignment membership, and label types
- [x] Define the minimal structured extraction result with observation type, actor, problem,
      context, consequence, verbatim evidence span, P/M/E signals, confidence, and abstention
- [x] Reject gold-contaminated inference input, malformed labels, inconsistent money signals,
      invalid observation types, unknown documents, and non-verbatim evidence spans
- [x] Pass the deterministic 40-record fixture E2E and the full **551-test** regression suite
- [x] Implement the gold-isolated deterministic `rule_v1` benchmark over the frozen
      development corpus with contract validation, abstention accounting, and a hashed receipt
- [x] Prevent keyword-substring false positives and classify problem and money signals
      independently while preserving a verbatim evidence span
- [x] Dry-run `rule_v1` on all 40 development records: 40 valid outputs, 22 abstentions,
      seven money positives, and zero invalid outputs
- [x] Implement a frozen-run-bound calibration evaluator with corpus/gold/output hash checks,
      duplicate and membership rejection, P/M/usable-evidence confusion matrices,
      quality-constrained coverage, invalid/abstention accounting, and source breakdowns
- [x] Freeze a repository-relative four-source artifact manifest and validate its
      `local_ignored` custody, path containment, exact source set, and required file types
- [x] Separate fresh-clone fixture validation from the opt-in real 40-record integration run;
      `RESEARCH_AUTO_RUN_LOCAL_ARTIFACT_TESTS=1` enables the local-custody projection check
- [x] Bind `rule_v1` to a frozen seven-file implementation hash bundle and persist the
      file-level hash mapping for independent provenance inspection
- [x] Bind the preflight receipt to the source manifest, qualification snapshots, validated
      packet manifests, source quotas, inference corpus, and physically separate gold sidecar
- [x] Define recursive exact-allowlist schemas for preflight, run, metrics, evaluation, and
      bundle-manifest artifacts while persisting no raw source text, author, URL, or prediction rows
- [x] Write the aggregate metric bundle through a same-filesystem temporary directory and atomic
      rename; make identical reruns idempotent and reject conflicting existing bundles
- [x] Require explicit local-custody opt-in and record `outputs_persisted=false` plus
      `reverification_requires_local_custody=true`
- [x] Evaluate the frozen 40-record `rule_v1` run against the physically separate development
      gold sidecar and persist the aggregate-only baseline metric bundle: coverage 14/40,
      Problem P/R 100%/30.3%, Money P/R 75%/33.3%, Evidence P/R 100%/42.4%, invalid 0
- [x] Implement and review-approve the count-aware calibration gate with frozen absolute
      thresholds, baseline provenance binding, exact four-source diagnostics, integer audit
      boundaries, and fail-closed candidate run/report/count verification
- [x] Implement local-only blind semantic-audit custody with exact evidence-positive membership,
      private atomic packet creation, assignment/packet/submission hash verification, aggregate-only
      receipts, candidate-run binding, expiry enforcement, and raw-row non-persistence
- [x] Atomically publish, independently verify, and code-review approve the immutable gate freeze
      receipt against clean Checkpoint `f694a2c`, including config, baseline, and commit-blob hashes
- [x] Freeze absolute and baseline-relative calibration thresholds before any model call
- [x] Freeze the first real inference profile: provider/model, prompt version, schema version,
      request and cost ceilings, retries, secret handling, and raw-response retention
- [x] Implement the strict OpenAI Responses transport with frozen prompt/schema hashes,
      sanitized structured output, bounded retries, resolved-model validation, and no raw-response persistence
- [x] Implement the one-shot 40-record model runner with repository-local atomic run custody,
      aggregate-only success/failure receipts, request/token/cost accounting, and explicit unknown-usage handling
- [x] Reject caller-selected or injected calibration ledgers and consume the single metric-run claim
      before the first provider request
- [x] Implement the bounded synthetic provider-contract preflight with a separate atomic claim,
      three-attempt operational ceiling, conservative $0.10 cost bound, metric-claim drift detection,
      aggregate-only receipt, and status-specific CLI exit codes
- [ ] Execute the bounded provider-contract preflight without consuming the canonical 40-record metric-run claim
- [ ] Run actual structured extraction on the 40 development-calibration records
- [ ] Compare the first model-backed extractor against `rule_v1` using the physically separate
      development gold sidecar; report P/M/E coverage and error classes without opening a new holdout
- [ ] Report coverage and P/E diagnostics separately from a gold-hidden structured-field audit
- [ ] Require the calibration gate before expanding extraction beyond the 40-record slice
- [ ] After extractor freeze, select a new untouched evaluation sample from the 320 unassigned
      records; do not claim independent performance from the source-spike-reserved assignments

The current implementation is a working deterministic calibration baseline, a review-approved
count-aware gate, and a review-approved model-execution path, but not yet a useful demand extractor.
It projects the four qualified datasets into a gold-free 40-record corpus,
emits contract-valid rule-based outputs, records abstentions and hashes, keeps human gold
physically separate, and can evaluate a hash-bound frozen run without silently dropping duplicate
documents. The gate now binds candidate run and evaluator receipts to recomputed hashes, requires
complete diagnostics for GitHub, Stack Exchange, Steam, and TED, and blocks expansion until every
evidence-positive extraction has a valid blind semantic audit. The frozen OpenAI GPT-5.6 profile,
strict Responses transport, and one-shot calibration runner are implemented with canonical local
run custody and fail-closed usage/cost receipts. The code does not yet complete a real provider
call, produce semantically reliable structured problem
extraction, cluster problems, or generate Opportunity Cards. The actual `rule_v1` aggregate
baseline bundle and calibration gate are frozen. The bounded provider-preflight executor is now
implemented but has not made a live API call. The immediate bottleneck is its single authorized
live execution followed by the single authorized 40-record model calibration run, not additional
source infrastructure. The full suite passes **606 tests** with one intentional
local-custody integration skip.

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
