# Roadmap dashboard

Internal single-page inspection of `../roadmap.md`, not a live product-status service.
The source snapshot is dated 2026-10-20 (revision ship-gates-blocked).
The approved 40-record metric-v1 execution stopped after its first document with
CLI_OUTPUT_MISSING: INCOMPLETE / OPERATIONAL_FAILURE, one operational failure,
39 not attempted, zero valid extraction/abstention/invalid outputs, tokens 36334/839.
No quality metrics were produced; this is not a 40-record failure rate or abstention result.
The raw events were not retained, so its terminal-message subtype remains UNKNOWN.
The new terminal diagnostics distinguish absent, multiple and non-string messages,
retain null for early unobserved counts and do not backfill historical evidence.
The dedicated terminal-probe-v1 local candidate is implemented and review-approved.
Offline regression passed 367 tests with one skipped and the staged TDD gate passed.
Call attempts and actual processes are separate: known prelaunch failure=0, observed
execution=1, unknown=null. Orphan claim inspection infers neither value.
No live model execution has exercised this probe. A future run needs separate approval
for at most one first-document call, no retry, subprocess timeout 120 seconds, no total
workflow time bound and an unenforced CLI cost ceiling; no 40-record evaluation.
Historical v1-v5 and metric-v1 custody remain preserved. V5 synthetic positive PASS
(true/false/true, tokens 17132/1155) remains a separate observation, not product evidence.
No model calls, retries or historical writes are part of this dashboard refresh.
Any future execution needs an explicitly approved new version and bounded contract.
Actual CLI cost and resolved model are unavailable. The API $0.099756/$0.10 upper bound
is not a measured CLI cost. Fixture output is not counted as product output.

## Delivery readiness

Probe code review approval is not SHIP READY. Project quality gates remain unconfigured.
Project-wide test/type/lint/secret gate execution is not established by the focused
offline regression or dashboard render checks. Type/lint project commands are not
configured; a locally available executable is not a project contract.
Configuration application, quality execution, model execution and push/deploy each
require separate approval. This documentation refresh changes the complete candidate
and therefore needs a fresh integrated review before ship.

## Build and preview

From this directory, with Node.js and Python available:

```sh
node build.cjs
python3 -m http.server 8766 --bind 127.0.0.1
```

Open `http://127.0.0.1:8766/`. The checked-in `index.html` also opens directly and
requires no external assets, network data, package installation, or application server.

`source-data.json` is a curated projection of the roadmap, not synthetic observations.
The build freezes local source and question-contract snapshots in Git-ignored
`evidence/<snapshot_revision>/`,
records initial hashes, and checks the displayed aggregates against those snapshots.
Preserve historical evidence when making a new revision; give changed source data a new
`snapshot_revision` instead of overwriting a frozen snapshot. Earlier unversioned evidence
is also preserved.

## Render verification

With an existing Playwright installation resolvable by Node.js and Google Chrome installed:

```sh
node verify-render.cjs
```

No dependencies or browser binaries are downloaded by either script. Set `NODE_PATH`
to an existing package directory when using a shared runtime. Render verification records
1440px and 390px screenshots, horizontal-overflow checks, expected source/milestone counts,
and displayed aggregate values. The local `evidence/<snapshot_revision>/handoff.json` keeps the results;
source claims still require independent live verification.
