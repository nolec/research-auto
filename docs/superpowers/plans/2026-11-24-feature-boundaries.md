# Research-Auto Feature Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-executing-plans for native execution (or superpowers-subagent-driven-development if explicitly chosen). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 납품 기능과 가상 실험 코드를 목적별로 정리하면서 기존 엔진의 재현성과 사용법을 보존한다.

**Architecture:** 구현은 `src/services/`에 단일화하고 기존 모듈은 호환 진입점으로 유지한다. 동결된 엔진 패키지는 현재 경로/바이트를 유지하고 신규 가상 Excel→PDF 실험만 `experiments/excel_pdf/`로 이동한다. 실험 데이터/산출물은 변동 없이 보존한다.

**Tech Stack:** Python 3.11, pytest, openpyxl (XLSX 테스트), 기존 Node artifact-tool 및 LibreOffice (실험 재실행 시에만).

**Spec:** `docs/superpowers/specs/2026-11-24-feature-boundaries-design.md`

## Global Constraints

- 기존 엔진/수집기의 소스 바이트, 고정 프롬프트·스키마·골드·측정 결과 변경 없음. 새 모델 호출 및 외부 네트워크 수집 없음.
- 기존 사용자 미커밋 파일 보존. 전체 `git add .`, 강제 삭제, Git push 금지.
- 이전 CLI, import, 기능별 검증·입력 제한 및 출력 구조 유지. 스캔의 OCR와 숫자 검증 재사용은 예외적으로 허용.
- `.git` 쓰기 불가 시 커밋하지 않고 명시 경로별 계획을 제공. 자료 공개 여부가 확인 안 된 JSON, 고객 파일, 생성된 HTML/PDF/이미지/실험 산출물은 커밋 선택에서 제외.

## Review Focus

- 기존 모듈에서 monkeypatch한 속성이 새 구현의 함수 실행에도 같은 모듈 객체를 통해 반영되어야 한다.
- CLI가 기존 경로와 새 경로 모두에서 실행되고, `argparse --help` 외에 합성 입력의 결과가 동일해야 한다.
- 주문 화면 HTML 및 OCR 실행 리소스를 잘못된 상대 경로에서 읽지 않아야 한다.
- 동결된 엔진 소스, config, 증거 및 원본 산출물의 SHA-256이 달라지지 않아야 한다.
- 로컬 결과물이 없어도 서비스 import가 성공하고, 실험 코드는 명시적으로 실행할 때만 결과를 생성해야 한다.

---

### Preflight (before Task 1)

- [ ] Capture working tree before moving anything (tracked+untracked relevant source files, clean index status, HEAD `0ea997e` or reviewed successor, hashes for preexisting core files and all protected result/manifest paths). If the index has unrelated staged changes or files overlap a new user edit, stop and inspect. Record the existing results separately from the source relocation. Do not write Git metadata in a read-only session.

### Task 1: 스프레드시트, 정기 보고서, 송장 대조 경계

**Files:**
- Create `src/services/__init__.py`, `src/services/spreadsheet.py`, `src/services/periodic_report.py`, `src/services/invoice_reconciliation.py`, `tests/test_service_boundaries.py`.
- Modify `src/spreadsheet_pilot.py`, `src/periodic_report.py`, `src/invoice_reconciliation_pilot.py` to compatibility entries; preserve historical JS sample `src/spreadsheet_pilot_workbook.mjs`.

**Interfaces:**
- Existing `reconcile(paths, key)`, `export_review_package(result, directory, *, xlsx=False, report_summary=False)`, `build_report(paths, *, key, date_field, category_field, quantity_field, frequency)`, `export_report_package(result, directory)`, `reconcile(invoice_csv, payment_csv)`; keep all signatures unchanged.
- Old/new module mappings as in this task's file list; no duplicated implementation.

- [ ] Write `test_legacy_service_imports_same_module` with `assert importlib.import_module(old) is importlib.import_module(new)` for all three mappings, `test_report_reuses_canonical_spreadsheet` with `assert report.reconcile is sheet.reconcile`, and `test_both_spreadsheet_and_report_clis` exercising both legacy/new `--help` then deterministic tiny CSV input, comparing returned JSON records and CSV artifacts (excluding output path). Write subprocess test importing each service from a temporary unrelated cwd using repo `PYTHONPATH` with no output writes.
- [ ] Run `python3 -m pytest -q tests/test_service_boundaries.py`; expect missing `src.services` (RED).
- [ ] Move implementations to the new modules with byte content preserved apart from relevant import edits. Legacy alias entries use `sys.modules[__name__] = implementation` for ordinary imports and explicitly call existing `main()` for prior module CLI. For invoice (no CLI), preserve no-op behavior on `-m`; no new CLI. Report imports its counterpart from `src.services.spreadsheet`. Maintain all private helpers/API and no import-time side effects.
- [ ] Run `python3 -m pytest -q tests/test_service_boundaries.py tests/test_spreadsheet_pilot.py tests/test_periodic_report.py tests/test_invoice_reconciliation_pilot.py`. Repeat relevant tests using an installed Python that has openpyxl; verify no XLSX skips in that repeat.
- [ ] Commit only these explicit paths if Git metadata writable: `refactor: isolate spreadsheet and invoice delivery services`.

### Task 2: 스캔 PDF 납품 경로

**Files:**
- Create `src/services/scanned_pdf/__init__.py`, `src/services/scanned_pdf/order.py`, and two existing order templates in the new package. Keep `src/scanned_pdf_experiment/order.py` as compatible alias. Keep study-only `numeric_reread.py`, `holdout_*`, OCR implementation and other research modules at their existing paths. Preserve historical templates at their original paths if any manifest references them; do not create independently maintained active templates.
- Modify `tests/test_service_boundaries.py`, `docs/scanned-pdf-order-runbook.md`.

**Interfaces:** Preserve `prepare(pdf, job, pages)`, `extract(job, mapping, reader=recognize)`, `deliver(job, review)`, `grid_cells(manifest, scope)`, `validated_rows(packet, submission, packet_hash)` and existing `main()` arguments.

- [ ] Add `test_scanned_order_alias` asserting old/new module identity and same signatures; `test_scanned_order_resource_resolution` asserting templates resolve to real files, OCR script path resolves to the original file, and generated HTML has payload substituted using a synthetic minimal HTML packet; `test_scanned_order_both_clis` invoking `--help` at each path and comparing subcommands.
- [ ] Run new tests and confirm failure because new package does not exist.
- [ ] Move the order implementation and runtime templates; adjust lookup for OCR resources explicitly to existing `src/scanned_pdf_experiment/` (inspect `recognize` before move). Old order file invokes new `main()` for `-m` or aliases module. Ensure numeric parsing still uses the original function. Runbook lists canonical and previous commands. No OCR changes.
- [ ] Run `python3 -m pytest -q tests/test_service_boundaries.py tests/test_scanned_pdf_order.py tests/test_scanned_pdf_numeric_reread.py tests/test_scanned_pdf_visual_agreement.py` with existing required dependencies. Verify no extra data or images created under repo.
- [ ] Commit explicit files if permitted: `refactor: isolate scanned PDF order workflow`.

### Task 3: 가상 Excel→PDF 실험 경계

**Files:** Move `artifacts/evidence-pilot/excel_pdf_fixtures.mjs` and `artifacts/evidence-pilot/excel_pdf_pilot.py` to `experiments/excel_pdf/` (both are currently untracked). Create `experiments/excel_pdf/README.md`, `tests/test_excel_pdf_experiment.py`. Update `docs/excel-pdf-pilot-20261124.md` (historical paths identified as such). Keep `outputs/excel-pdf-pilot-20261124/` files unchanged.

**Interfaces:** Existing fixture CLI accepts runtime node modules and output dir; pilot CLI accepts raw fixtures, output dir, native dependency dir. `check_result(result)`, `prepare(src,dst,specs)`, `execute(raw,out,native)` unchanged. Do not accept customer data or generalize fixed synthetic specs.

- [ ] Add tests that import `experiments.excel_pdf.excel_pdf_pilot`, construct in-memory result with the three exact expected file names (1+1+3 pages, totals 425/80/156, 60 detailed rows), and assert `check_result` success; parametrized corruptions (wrong detail row, missing PDF, incorrect page orientation) must raise `AssertionError`. Test import produces no files. Verify original source/product files match baseline hashes without adding large artifacts to Git.
- [ ] Run `python3 -m pytest -q tests/test_excel_pdf_experiment.py`; expect import failure.
- [ ] Relocate exact source bytes, then update docs/README with canonical reproducible commands (use fresh output location). No conversion engine or calculation change. Both source files remain usable and no historical output is regenerated. Do not add the old artifact paths as duplicate implementations.
- [ ] Run the new tests; verify SHA-256 for both old source bytes vs new source bytes and all original input/PDF/result files. If dependencies are available, run the experiment against freshly created synthetic files in a new temporary dir only and compare verification outcomes, not binary PDF hashes. No external APIs.
- [ ] Commit explicit new experiment code, tests, runbook and pilot report if permitted: `refactor: separate synthetic Excel PDF experiment from results`.

### Task 4: 엔진 검증·자료 경계 및 기능별 커밋 구성

**Files:** `README.md`, new `docs/project-structure.md`, `tests/test_service_boundaries.py`. Existing engine modules, configs, schemas and artifacts remain in their original locations and bytes; list existing untracked code and corresponding tests/settings in commit plan; do not move hash-bound code.

- [ ] In `test_service_boundaries.py`, pin no engine-to-service or service-to-engine imports via AST; allow `src.scanned_pdf_experiment` numeric/OCR dependencies only for the scan order package. Assert public service packages and experiment directories do not contain generated PDF/PNG/XLSX files; new test fails if violation is artificially introduced in a temporary representation.
- [ ] Update README link and project structure document; include actual canonical and legacy commands, protected engine version paths, experiment scope, output locations, `config/` vs `configs/` existing distinction and why not renamed. Explain the user-run dependency mismatch (openpyxl in bundled Python, jsonschema in framework Python) and feature-specific commands. Add no new external dependency.
- [ ] Define precise candidate groups (source, tests and non-sensitive config/doc only; verify existence, no overlap, and review public/derived-data terms before adding). Semantic problem: `src/extraction/semantic_problem_{development,holdout}.py`, matching tests, `configs/extraction/semantic-problem-{development,holdout}-v1.csv`, relevant review docs and AI labels only if reviewed. Cluster: `src/extraction/{cluster_diagnostic,semantic_cluster_development,semantic_cluster_multitask,semantic_cluster_ensemble}.py`, corresponding 4 tests, pair configs `configs/cluster-development-pairs-v1.csv`, `configs/extraction/semantic-cluster-development-v1.csv` and corresponding docs. Solution gap: `src/extraction/solution_gap_{diagnostic,holdout,holdout_v2}.py`, matching 3 tests and 3 JSON manifests + gap docs (review extracted excerpts). Integrated/fresh: `src/extraction/integrated_discovery_pilot.py`, `src/source_spike/{fresh_discovery_diagnostic,fresh_integrated_discovery}.py`, matching 4 tests, protocol/review docs. Other existing buyer exploration docs are a separate docs group. No `git add .`, no bulk generated assets. Preserve all user changes; report excluded paths and why. Existing local snapshots required for integrated replay remain local-only until a separately approved portable data protocol exists.
- [ ] Run focused service tests and all tests (`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider`), capture skips; separately run XLSX tests with bundled runtime Python. Verify unchanged engine/config/input/result SHA-256, clean unintended tracked diff, and no commit includes generated output. Report actual test results rather than latest historic counts.
- [ ] If Git write access exists, commit feature groups only after path-by-path staged set validation; no push. If not, leave worktree intact and supply a reviewed explicit-path commit manifest for the user to run in their normal local terminal. No permission workaround. Never claim commits completed without `git log` evidence.
