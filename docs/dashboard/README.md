# Roadmap dashboard

Internal single-page inspection of `../roadmap.md`, not a live product-status service.
The source snapshot is dated 2026-10-18. Actual v4 preflight observed output-contract
validity=true, abstained=true and positive sanity=false, with input/output tokens 17106/191.
It remains `PREFLIGHT_BLOCKED` / `CLI_SEMANTIC_SANITY_FAIL`: contract-valid abstention is
not positive preflight PASS or extraction-quality evidence. The abstention reason was not
retained. Historical v1/v2/v3/v4 records remain preserved; v1/v2/v3 hashes were unchanged.
Offline extraction regression is 275 passed, 1 skipped. The API preflight cost upper bound
is $0.099756 under the unchanged $0.10 ceiling, not an observed CLI cost.
The positive extraction path and 40-record model evaluation remain unstarted.
Fixture output is not counted as product output.

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
