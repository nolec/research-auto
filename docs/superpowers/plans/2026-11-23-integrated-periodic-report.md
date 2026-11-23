# Integrated periodic report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-subagent-driven-development (recommended) or superpowers-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate one consistent review package containing periodic report totals and the final row dispositions.

**Architecture:** Reuse generic reconciliation unchanged in a report-specific module, validate accepted rows once, aggregate only final accepted rows, and export one snapshot workbook using the existing review export contract.

**Tech Stack:** Python, existing openpyxl export, pytest.

**Spec:** `docs/superpowers/specs/2026-11-23-integrated-periodic-report-design.md`

## Global Constraints

- Identical schemas; 1–3 CSV/XLSX files, 1,000 data rows total, 15 columns, 2 MB each.
- Canonical ISO text dates, nonnegative integer quantities, nonblank categories; distinct input field mappings.
- Generic reconciliation behavior remains unchanged. Preserve raw values and source coordinates. Snapshot only; offline; human review required.
- Reject unsupported scope and quantities/totals beyond Excel exact integer representation; no automated repair or guessed values.

## Review Focus

- All-held input: no invented reporting periods or zero-valued result presented as actual.
- Zero quantity: accepted, count retained; not mistaken for missing value.
- Invalid repeated/conflicting IDs: deterministic precedence, no double inclusion.
- Invalid mapping/frequency/over-limit columns: fail before writing outputs.
- Large integer or cumulative quantity unsafe in Excel: fail before writing outputs.

## Task 1: Report-specific classification and aggregation

**Files:** Create `src/periodic_report.py`, `tests/test_periodic_report.py`.

**Interfaces:** `build_report(paths, *, key, date_field, category_field, quantity_field, frequency) -> dict` returns reconciliation-compatible `accepted`, `duplicates`, `exceptions`, `sources`, `headers`, `key`, `input_count`, `status`, plus `frequency` and `summary` keyed by month or Monday. Every summary entry has `total`, `rows`, `categories`.

- [ ] Write failing tests: independent small fixture, 13 rows -> 6 accepted/1 duplicate/6 held; Sep 14 and Oct 17; held coordinates match source; weekly boundaries, zero, all held, conflicting keys precedence. Parametrize bad mapping/frequency, 16-column input, invalid numeric field, aggregate unsafe integer. Assert generic reconciliation still returns the same pre-existing key-based classification.
- [ ] Run `python3 -m pytest -q tests/test_periodic_report.py`; confirm missing behavior fails.
- [ ] Implement build_report by delegating to `reconcile` and moving invalid accepted rows into exceptions once; aggregate final accepted records exclusively. Reject quantities and totals > 999999999999999 as outside agreed exact Excel scope. Keep original/typed values unchanged.
- [ ] Run focused tests and `tests/test_spreadsheet_pilot.py` using bundled Python.

## Task 2: Unified workbook and command-line path

**Files:** Modify `src/periodic_report.py`, `src/spreadsheet_pilot.py` only for optional summary export, `tests/test_periodic_report.py`.

**Interfaces:** `export_report_package(result, directory)` produces the existing source/validation CSV and JSON package plus `delivery-draft.xlsx` with a first sheet `기간별 실적` and all existing review sheets; `python3 -m src.periodic_report --key ... --date-field ... --category-field ... --quantity-field ... --frequency weekly|monthly --output ... files...`.

- [ ] Write failing boundary tests reading actual saved XLSX and CSV: verify the 13-row source trail, 6 final held entries with reasons, 6 accepted, 1 duplicate, monthly totals 14 and 17; all-held case only explicit no-data label; existing generic workbook still has the original sheets. Add CLI subprocess test for unsupported input and no output directory.
- [ ] Run focused tests and confirm failure due missing export path.
- [ ] Implement report-specific export by passing final report result into existing exporter. Add snapshot report summary sheet (period, category, row count where applicable, quantity) and round-trip assertions to the existing exporter only when report summary is supplied; generic output unchanged. Reject existing output directory.
- [ ] Run focused tests, then full `python3 -m pytest -q` with bundled Python. Report any existing failures without masking them.

## Task 3: Maximum-scope verification and operating notes

**Files:** Create `artifacts/evidence-pilot/report_integrated_verify.py`, update `artifacts/evidence-pilot/report-scale-spike-20261123.md` and a local report runbook under `docs/`.

- [ ] Reuse the synthetic fixture/oracle from `report_scale_spike.py` without deriving expectations from the new implementation. Run 3 mappings x 2 file formats x 2 frequencies = 12 complete exports. Read each workbook and compare total/category data, raw source coordinates and values, 800/50/150 disposition counts; review JSON and CSV classifications too. Measure compute/export time separately from human review.
- [ ] Run full regression suite, verify all outputs, record actual results and limitations. No commits unless Git write authorization is supplied and requested.
- [ ] Hand off CLI usage, scope, remaining actual-customer validation and paid pilot gate.

## Execution ledger — 2026-11-23 KST

- Ruling: user expressly approved execution on current main without Git writes; no worktree or commits, so commit-range helper unavailable. Preserve existing dirty files and use source/test review directly. Cost: no isolated commit history yet.
- Pre-flight: Task 1's reconciliation-compatible final result supplies Task 2 export and Task 3 oracle; no interface conflicts.
- Task 1: complete — RED 9 missing module, GREEN 23 focused tests including 14 generic tests.
- Task 2: complete — RED 4 missing export/CLI, GREEN 27 focused tests. Full normal system run 1271 passed/12 skipped; XLSX dependency unavailable in that interpreter.
- Ruling: bundled Python lacks jsonschema; system Python includes repository dependencies but not openpyxl. Run final suite with temporary symlinks to bundled pure Python openpyxl/et_xmlfile, no dependency install or project configuration changes. Cost: verification uses temporary environment, not a configured deployment environment.
- Task 3: complete — independent fixture comparison on all twelve 1,000-row integrated runs, CSV/JSON/XLSX verified. Final review by fresh read-only reviewer; no critical aggregation or row-loss finding. Fixed ambiguous total label with dedicated row type (RED→GREEN), strengthened oracle comparisons of CSV and JSON. Deferred minor: inherited invalid control character in source filename can leave partial output; runbook warns not to deliver failed outputs and to use normal filenames.
- Final: 1283 passed, 1 skipped (local source-spike artifact unavailable); 12 integrated runs PASS; no commits. See `artifacts/evidence-pilot/report-scale-spike-20261123.md`, `docs/periodic-report-runbook.md`.
