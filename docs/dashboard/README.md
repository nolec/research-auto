# Roadmap dashboard

Internal single-page inspection of `../roadmap.md`, not a live product-status service.
The source snapshot is dated 2026-10-18. Actual v2 preflight and 40-record extraction
have not been executed. Fixture output is not counted as product output.

## Build and preview

From this directory, with Node.js and Python available:

```sh
node build.cjs
python3 -m http.server 8766 --bind 127.0.0.1
```

Open `http://127.0.0.1:8766/`. The checked-in `index.html` also opens directly and
requires no external assets, network data, package installation, or application server.

`source-data.json` is a curated projection of the roadmap, not synthetic observations.
The build freezes local source and question-contract snapshots in Git-ignored `evidence/`,
records initial hashes, and checks the displayed aggregates against those snapshots.
Preserve historical evidence when making a new revision; use a fresh artifact directory
for changed source data rather than overwriting a frozen snapshot.

## Render verification

With an existing Playwright installation resolvable by Node.js and Google Chrome installed:

```sh
node verify-render.cjs
```

No dependencies or browser binaries are downloaded by either script. Set `NODE_PATH`
to an existing package directory when using a shared runtime. Render verification records
1440px and 390px screenshots, horizontal-overflow checks, expected source/milestone counts,
and displayed aggregate values. The local `evidence/handoff.json` keeps the results;
source claims still require independent live verification.
