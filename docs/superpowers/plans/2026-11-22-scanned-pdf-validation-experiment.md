# Scanned PDF Validation Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-subagent-driven-development (recommended) or superpowers-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether a local OCR-backed verifier detects discrepancies between scanned PDF tables and existing spreadsheets better than basic checks, without prematurely building a product.

**Architecture:** A separate experiment package reads image-only PDF pages and CSV through a local macOS OCR adapter. One shared OCR snapshot feeds a basic comparator and a candidate strategy that reconstructs labels/columns from geometry and compares semantic cells. A separate evaluator consumes frozen answer keys; an offline report contains metrics and a blinded manual-review packet, not an official Opportunity Card.

**Tech Stack:** Python 3, pytest, installed Pillow, CSV/JSON standard library, Swift Vision + PDFKit (local import probe succeeded; actual OCR still needs validation). No new paid API or package installation.

**Spec:** [Scanned PDF / row-label validation design](../specs/2026-11-22-scanned-pdf-validation-experiment-design.md)

## Global Constraints

- 20 distinct document inputs: target 10 permission-verified public scans and 10 synthetic scans; if public documents or human-verified transcription are unavailable, stop before final freeze and request approval to substitute. No real customer files, private/personal records or fabricated rights/transcriptions.
- One preselected table per doc, 1–2 pages, 8–20 data rows, 3–6 columns, at most 120 data cells. Cover grid/borderless, merged/multiline labels, repeated values, numbers/units, noisy scans and some page breaks. Do not use assessment documents to tune the verifier.
- 40 document-input combinations (20 clean, 20 corrupted), 60 nonoverlapping injected events, 12 each numeric, row swap, column swap, missing cell/row, label corruption. Include equal-total swaps; count swaps as one event. Freeze protocol, provenance, truth, OCR config, faults and matching policy before assessment. Never amend frozen results to improve metrics.
- Candidate and baseline use the same raw OCR tokens. Inputs to the candidate are original image/text observations and CSV only; no answer keys, source-value fixtures, injected-event labels or human annotations. No synthetic ID encoded in candidate input that reveals answer. Use local OCR; no credentials, external API, deployment or paid service.
- Alert uncertainty explicitly; no automatic edits, accuracy guarantees, fabricated human times or automatic opportunity promotion. Pilot remains HOLD; no change to production Research-Auto or existing artifacts.
- Exact gates: precision ≥95%, recall ≥90%, row/column/label combined TP improves versus B0 and no individual type declines. H0/H1: 10 matched pairs (8 corrupted pairs + 2 clean pairs), each arm 10 documents; median time saving ≥50%, H1 FP/FN no greater than H0. Human review missing → PENDING, never full success.
- Git metadata is restricted in current session; only scoped commits if permissions allow, otherwise leave changes uncommitted and report. All tests deterministic/offline; avoid modifying pre-existing untracked work.

## File Structure

- `src/scanned_pdf_experiment/contracts.py`: shared event and evidence contracts.
- `src/scanned_pdf_experiment/dataset.py`: safe public input imports, synthetic fixtures, error injection/freeze validation.
- `src/scanned_pdf_experiment/ocr.py` and `src/scanned_pdf_experiment/vision_ocr.swift`: actual local PDF rendering/OCR bridge.
- `src/scanned_pdf_experiment/verify.py`: table reconstruction, basic B0 and candidate A, uncertainty.
- `src/scanned_pdf_experiment/evaluate.py`: exact event matching, metrics, gates, human review pairs/timing.
- `src/scanned_pdf_experiment/run.py`: bounded CLI and result report.
- `tests/scanned_pdf_experiment/`: contract/dataset, OCR, verifier, evaluator, smoke tests.
- `artifacts/scanned-pdf-experiment/<run-id>/`: frozen inputs, separately held ground truth, outputs, report, human packet. `docs/scanned-pdf-experiment-runbook.md`: commands and procedure.

## Review Focus

1. Ground-truth leakage or mislabeled born-digital PDF masquerading as scanned input — T1/T2 tests isolate truth and image-only synthetic generation.
2. OCR unavailable, empty/low-confidence output or corrupt PDF must not look like correct data — T2 tests require explicit failure/uncertainty.
3. Equal-total swaps and repeated values must not be classified as correct or guessed — T3 tests include equal totals, ambiguity, missing row and multi-page headers.
4. Duplicate warning or swapped pair incorrectly counts twice; clean FP and denominator zero hidden — T4 exact event matching and gate tests.
5. Cherry-picked sample, invented human timing or silently overwritten artifact — T5 freeze/receipt/reproducibility and PENDING checks.

---

### Task 1: Contracts, dataset generation and sealed evaluation protocol

**Files:** Create `src/scanned_pdf_experiment/__init__.py`, `contracts.py`, `dataset.py`, `tests/scanned_pdf_experiment/test_dataset.py`.

**Interfaces:**
- `Event(kind: str, cells: tuple[str, ...])` immutable; kind in `numeric`, `row_swap`, `column_swap`, `missing`, `label`. Cell refs use `page-independent source row label // source column display label` (unique normalized labels only; repeated labels must carry a visibly disambiguating group label); missing row uses `row_label//*`, sorted swap pair refs. `Event` contains no hidden truth IDs supplied to verifier. `Token(page:int, text:str, bbox:tuple[float,float,float,float], confidence:float)`, bbox normalized top-left (x0,y0,x1,y1), page one-based. `Alert(event: Event|None, status: str, evidence: dict)`, status `DETECTED`, `UNCERTAIN`, `GENERAL`; detected has explicit source bbox and observed/expected evidence; unlocalized warnings have no event.
- `make_synthetic_tables(seed: int, out: Path, count: int=10) -> list[dict]`: Pillow raster render each distinct layout into page images then save PDF in raster-only mode. Each record contains doc_id, relative PDF, allowed scope/pages, row/column counts, style, rights, SHA-256, input/answer paths. Serialize truth as canonical row label, headers and decimal values; CSV is visible values only. No QR codes, hidden text, injected ID in input. Independent dev fixtures use distinct seed/templates.
- `inject_errors(table: dict, schedule: list[dict]) -> tuple[list[list[str]], list[Event]]`: apply predeclared nonoverlapping events (row swap and col swap use exact sorted cell refs; row missing wildcard; numeric replacement not equal original; label replacement uses original source label and `//label`); reject overlapping or no-op. Preserve clean CSV separately.
- `freeze_dataset(records: list[dict], out: Path) -> dict`: validate 20 unique source PDF hashes/doc IDs, source type/rights and human transcription verification for public, page/row/col limits, distinct visible keys, 40 variant entries and 60 events distrib 12 each; write hash-bound manifests (candidate manifest excludes any truth paths/error metadata; evaluator references truth manifest and input hash). Refuse pre-existing frozen destination; do not copy public docs until rights verified. Candidate and evaluator artifacts separate roots.

- [ ] Write failing tests: generate small dev raster fixture; `assert len(clean_csv_rows)==8`; fault injection equal-sum swap `assert sum(before)==sum(after)` and `len(events)==1`; overlapping/no-op `pytest.raises(ValueError)`; freeze duplicate PDF/invalid rights/public truth unverified/incorrect counts fail. Candidate public manifest must not contain truth/event filenames or error flags (use opaque variant IDs). Test 20 valid in-memory manifest records with canonical hash stable across key order; no fake public acceptance.
- [ ] Run `python3 -m pytest tests/scanned_pdf_experiment/test_dataset.py -q`; expected module import failure.
- [ ] Implement contracts and dataset functions. Use Pillow RGB raster PDF saving and manifest SHA-256 bytes, no network calls in dataset code. Define canonical normalization: Unicode NFKC, whitespace collapsed, casefold labels, Decimal plain values; unparseable values are uncertainty. Synthetic documents cover design styles; keep truth and event files outside candidate input directory.
- [ ] Run targeted tests; expect green. Verify 10 synthetic PDF bytes and actual raster OCR in T2 rather than claim scan support based on fixtures alone.
- [ ] Scoped commit when permitted (`git add src/scanned_pdf_experiment/{__init__,contracts,dataset}.py tests/scanned_pdf_experiment/test_dataset.py`); report blocked if git read-only.

### Task 2: Actual offline OCR adapter and preflight

**Files:** Create `src/scanned_pdf_experiment/ocr.py`, `vision_ocr.swift`, `tests/scanned_pdf_experiment/test_ocr.py`.

**Interfaces:** `recognize_pdf(pdf: Path, pages: tuple[int, ...], *, dpi: int=300, timeout: int=120) -> list[Token]` emits only OCR tokens from PDF rasterization. Swift helper CLI `vision_ocr <file> <comma-separated-pages> <dpi>` returns JSON array of Token fields. `OCRFailure` on unreadable PDF, missing Vision, bad page, timeout, malformed output; no empty success unless blank page explicitly identified as failure. Compile helper once in a task-specific writable temp/cache dir (Swift executable import was confirmed, actual runtime not yet confirmed).

- [ ] Write failing tests for valid token bounds/normalized direction/page sorting; malformed/zero-token payload, out-of-bounds bbox, missing executable, timeout, failed subprocess raise `OCRFailure`. Integration smoke uses generated dev fixture visibly containing `Total` and numeric `1234`; assert OCR returns both reasonable normalized tokens within [0,1] (no exact OCR guarantee). Skip only if run receipt explicitly marks OCR unavailable; no claiming experiment completion on skip.
- [ ] Run `python3 -m pytest tests/scanned_pdf_experiment/test_ocr.py -q`; expect missing module.
- [ ] Implement local Swift PDFKit render 300 DPI CGImage and Vision text recognition (accurate level; confidence and per-word/range bounding boxes when available, otherwise line boxes marked uncertain in verifier). Convert Vision bottom-left coordinates to documented top-left; no reading embedded text/answer. Python subprocess fixed command, timeout, parse/validate. No network or installs. Record Swift/OS/OCR config and exact binary version/hash as available.
- [ ] Run targeted tests and actual OCR smoke. If host permissions/recognition block real OCR, report BLOCKED, do not substitute simulated tokens for actual benchmark or bypass protections. Dev token fixture tests remain valid.
- [ ] Scoped commit when permitted.

### Task 3: Basic and semantic verification strategies

**Files:** Create `src/scanned_pdf_experiment/verify.py`, `tests/scanned_pdf_experiment/test_verify.py`.

**Interfaces:** `verify_basic(tokens: list[Token], sheet: list[list[str]]) -> list[Alert]`; `verify_semantic(tokens: list[Token], sheet: list[list[str]]) -> list[Alert]`. Both read visible CSV first row headers and row labels only. A source row key derives from original OCR labels (not injected truth), column key from OCR header. `reconstruct_table(tokens: list[Token]) -> dict` returns headers, row labels, cell decimal/value+source-page bbox+confidence, uncertain regions. Same token snapshot input to both methods; event locators use contract from T1.

- [ ] Write failing deterministic token/CSV tests for one numeric mutation, same-total row swap, same-row col swap, missing row/cell, independently incorrect label, clean no detected alerts. Assert exact Event equality (e.g. `Event("row_swap",("a//amount","b//amount"))`) and no second alerts covering the same event. Repeated numeric values with multiple possible alignments produce uncertainty, not a guessed swap. Missing OCR, low confidence (<0.8 starting threshold), duplicate labels/headers without visible disambiguation → UNCERTAIN; no guessed match. Two page headers removed from data rows; out-of-scope OCR excluded at fixture selection. B0 equal-total swaps do not create localized TP.
- [ ] Run test; expect fail on missing functions.
- [ ] Implement B0 row count, numeric format and explicit sum/total sanity general alerts (no semantic key alignment); a localized impossible numeric field can produce numeric event only with valid unambiguous source location. A groups tokens by Y bands and headers by X spans per page, associates row labels and columns, merges repeated header rows, normalizes values, uses only unique label and column matches. Recognize swap pairs only when reciprocal differences are unique and high confidence; label mismatch only when unique numeric row fingerprint and original label alignment support it; suppress generic numeric alerts consumed by swap event. If source geometry or ambiguity prevents a confident conclusion, emit uncertainty. Do not infer text absent from image. No output modifications to CSV.
- [ ] Run targeted tests; record heuristics and config. Tune only dev fixtures, freeze before benchmark; no result-informed parameter changes.
- [ ] Scoped commit when permitted.

### Task 4: Scoring and manual review assignment

**Files:** Create `src/scanned_pdf_experiment/evaluate.py`, `tests/scanned_pdf_experiment/test_evaluate.py`.

**Interfaces:** `score_events(expected: list[Event], alerts: list[Alert]) -> dict`: tp/fp/fn, precision/recall (null undefined), matches, uncertain/general counts. Each detected exact event consumes one expected event; duplicate detection is FP; missing events FN. `aggregate_scores(results: list[dict]) -> dict` micro overall plus per-type, clean/corrupt, provenance, difficulty, OCR failures. `automatic_gate(candidate: dict, baseline: dict) -> dict` exact thresholds. `assign_human_pairs(records: list[dict], seed: int) -> list[dict]`: 10 pairs matching difficulty, size, fault profile; 8 corrupt pairs and 2 clean; each pair one H0/H1; no repeated doc; randomized balanced order. `score_human(assignments: list[dict], observations: list[dict], truth: dict) -> dict`: requires actual attributed start/end elapsed seconds, completion and discrepancy list; returns PENDING for missing/incomplete data, no invented time; median paired relative saving plus per-arm error counts.

- [ ] Write failing tests: exact event `tp=1`, duplicate identical alert second FP, misclassified alert FP and FN, uncertainty FN, no events+no alerts precision/recall null, clean FP included, `57 TP/60` with `3 FP` precision .95 passes; `54/60` recall .9 with permitted FP passes; `53/60` recall fails; row/col/label aggregate no improvement or individual TP decline fails. Test group by type/source/difficulty, failed OCR results not removed. Human 20 distinct assignments, 10 pairs, 8 corrupt+2 clean; missing entries PENDING, time saved .5 measured passes only if FN/FP not worse. Reject fake/mismatched IDs/time values; no claim of authenticating human identity.
- [ ] Run targeted pytest, expect fail.
- [ ] Implement functions, matching exact normalized keys and type; enforce one-to-one event matching and micro counts, derive metrics from aggregated integer counts. Preserve uncertainty and diagnostic data; explicit gate reasons. Assignment uses deterministic seed pre-freeze and pair similarity from metadata/error categories without disclosing truth to reviewer. If exact 10 pairs not possible, fail before freeze and adjust scheduling before viewing results; no retrospective matching.
- [ ] Run targeted pytest, expect green.
- [ ] Scoped commit when permitted.

### Task 5: Bounded experiment CLI, real run and report

**Files:** Create `src/scanned_pdf_experiment/run.py`, `tests/scanned_pdf_experiment/test_run.py`, `docs/scanned-pdf-experiment-runbook.md`. Outputs only under `artifacts/scanned-pdf-experiment/<run-id>/`.

**Interfaces:** `python3 -m src.scanned_pdf_experiment.run --manifest PATH --truth-manifest PATH --out-dir PATH` validates both hashes, matching opaque IDs, rights and complete freeze; stages candidate/B0 execution via sandboxed input directory and one shared OCR snapshot per doc, never pass truth to verifier (evaluation after output freeze). Write source/manifests, OCR metadata/tokens, candidate and baseline alerts, exact scoring, JSON summary, Markdown report, H0/H1 packets and blank human timing records; receipt last with hashes and status. Explicit `HOLD`, `human=PENDING`, `opportunity=HOLD` unless genuine review supplied (business decision stays HOLD regardless of metrics). Do not overwrite existing run. Human review inputs contain original PDF/CSV plus alerts only in H1, no labels of corruption/ground truth.

- [ ] Write failing CLI tests using synthetic dev fixtures: invalid manifest/rights refuses before writing, pre-existing dir refuses, frozen hash tamper rejected, OCR failure is surfaced / events counted as FN (or blocked run when OCR unavailable), exactly one OCR snapshot per document for clean+corrupt and both methods, truth not passed to verify functions, blank human timing produces PENDING, no EVIDENCE_BACKED/ACTIONABLE promotion. Test report with clean FP, per-type counts and unavailable values. Small smoke fixture explicitly separate from full 20 corpus; do not call smoke a full experiment.
- [ ] Run tests, expect failure.
- [ ] Implement CLI; use exclusive output creation, receipt last; stage independent candidate inputs and outputs, no truth references in candidate config. Run dev smoke, targeted suite and full `python3 -m pytest -q`; report actual test counts.
- [ ] Retrieve actual permissions-verified open/public scanned PDF candidates (government public-domain archive or explicitly open-license sources; document provenance and license for every file; no login, private docs, attachments containing personal data; use authorized read-only access only). Select 10 distinct appropriate table scopes before examining verifier output. Obtain genuine human transcription confirmation of 10 public truth tables from source images. If fewer than 10 qualifying verified public items, STOP and report what is missing; request approval for synthetic substitution before freezing. Do not treat AI transcription as human verified. Generate 10 synthetic, distribute 60 faults and human pairs, freeze protocol/manifest. Actual full benchmark only if 20 verified documents and OCR preflight succeeded.
- [ ] Run full offline CLI using frozen dataset, including all 40 combinations. Verify receipt hashes, inspect examples of correct and incorrect detections, report actual precision/recall+per-type and baseline comparison with uncertainties. If failed, preserve failure and no tuning on holdout. Link output to candidate evidence via new report (do not alter historical report or existing production state). H0/H1 actual human timing only once reviewer agrees and can participate; otherwise report PENDING with review packet.
- [ ] Scoped commit when permitted; include code/tests/runbook, not arbitrary public source binaries without approval and redistribution rights. Report status separately (technical automated gate, human timing, business HOLD).

## Self-review

- Design §§1–4 mapped to T1 and T5: local isolated experiment, rights/transcription, 20/40/60 exact counts; explicitly stops for missing real-public verification. §5 mapped T2/T3; §6 T4 exact metrics + paired human study; §7 T5 report and startup gates. No service launch, payments or market claim.
- Interfaces use normalized source label/column refs consistently; evaluator holds answer event log only. Candidate input manifest opaque IDs, no hidden truth. T3's explicit swap matching and uncertainty avoid guessing. Small sample and proxy comparator limitations disclosed.
- All five review-focus failure modes have tests. Actual local Swift import passed (not an actual OCR run), no installed Tesseract/poppler; T2 confirms actual recognition or stops. No claim a full experiment has already run.
