# Prospective scan-only holdout intake — 2026-11-22 KST

Status: INCOMPLETE, business HOLD. The previous corrected 233/233 development
result is not a prospective benchmark; this intake never ran candidate inference.

## Acquisition

Eight byte-distinct new official US Census PDFs were downloaded and copied to
`artifacts/scanned-pdf-experiment/prospective-holdout-20261122/source/`.
The acquisition manifest `intake.json` records exact source URLs, hashes,
page counts and zero-text page indices. All hashes are distinct from the 28
previous public source files. The source indexes are:

- https://www2.census.gov/library/publications/decennial/1940/agriculture/
- https://www2.census.gov/library/publications/decennial/1950/population-volume-2/

All 363 pages were checked for extractable text using Poppler. Six pages had no
text: the four agriculture covers and two repeated front-matter contents
pages. All six were visually inspected (`preflight/zero-text-contact.jpg`);
they are not eligible aggregate-statistics scopes. The other 357 pages have
embedded text. Thus **0/10** eligible scan-only documents, not a failed
recognition benchmark. The downloaded files are retained as an alternative
scan-with-text-layer candidate pool, not silently counted in the strict cohort.

## Remaining candidates (not acquired)

The 1940 pre-2025 legacy chapter archives have previously yielded image-only
pages. New candidate URLs discovered in the official indexes, not yet locally
downloaded due to browser navigation timeouts:

- https://www2.census.gov/library/publications/decennial/1940/population-volume-3/33973538v3p2ch5.pdf
- https://www2.census.gov/library/publications/decennial/1940/population-volume-3/33973538v3p4ch04.pdf
- https://www2.census.gov/library/publications/decennial/1940/population-volume-2/33973538v2p2ch3.pdf
- https://www2.census.gov/library/publications/decennial/1940/population-volume-2/33973538v2p4ch5.pdf

These require original-byte acquisition, source rights/near-duplicate review,
page preflight and independent truth. No score has been computed.

## Separate alternative (requires explicit protocol decision)

An image-input evaluation on scanned PDFs that already have a hidden text
layer is useful if the reader receives only original-page raster crops and
cannot access the embedded text. This is a distinct stratum, not a substitute
for the frozen image-only criterion. Embedded OCR text is not gold truth;
human verification and frozen candidate inputs are still required. The eight
acquired documents could support this complementary test, reducing the need to
seek rare image-only files. Do not strip text layers to claim original
image-only eligibility.

## Approved complementary image-input stratum

The user approved the separate image-input evaluation. Eight distinct source
scopes were selected visually, one per source, each with eight selected
rows and three numeric columns (192 positional numeric cells). No semantic
row-label or row/column-swap claim is made. Source scans are rendered at 300
dpi and localized crops are generated from visually selected geometry with
image-only row alignment. Candidate packet filenames are opaque tokens; the
candidate directory contains only PNGs and a shuffled token list. The original
PDF text layer is used solely in the evaluator-side review draft (not gold
truth). Reviewer verification is pending; no candidate result is scored.

Reviewer: `image-input-review-v2/reviewer/review.html`. The v1 packet was
superseded before review because some crops clipped numerals; v2 image-only
alignment improved crop boundaries. The draft contains 31 unreadable entries
requiring manual entry and 161 prefilled values requiring visual confirmation.
The manifest binds all 192 crop hashes and the 24-fault schedule; target
precision >=95%, recall >=90%. A suitable independent reader must receive
only `candidate-images` (not the reviewer directory or original PDF).
Manual same-assistant reading is not fully blinded because of geometry review;
record reader provenance explicitly. Existing strict scan-only holdout remains
incomplete and business HOLD.

## Image-input v2 initial evaluation (2026-11-22)

The user exported the 192-cell verified CSV. It passed manifest validation
and was copied to the reviewer directory without changing its values. The
same assistant visually transcribed the 16 randomized image packets before
opening the verified CSV, with prior geometry exposure disclosed. Captured
reads and provenance are saved in `candidate-images/visual-reads-v1.json`.
Initial result against the unmodified reviewer CSV: 182/189 eligible numeric
matches (96.30%), 3 excluded nonnumeric tokens, 24 TP, 8 FP, 0 FN, 6 uncertain
document-input cells (3 unique cells), precision 75%, recall 100%. The frozen
threshold was not met. No business promotion or strict scan-only claim.

Seven unique disagreements were inspected using expanded original-page
context. `disputed-cells.png` preserves the evidence. Some likely reflect
clipped/adjacent-row crops or erroneous human truth rather than recognition
alone. Three possible truth issues require user adjudication: N01 row 3
1940 (-6 vs visible 5), N04 row 6 1920 (13,061 vs visible 13,961), and N08
row 5 Urban total (1,718,422 appears on the following row; target row appears
to be a dash). No correction was applied. Original initial result remains
immutable even if a later retrospective adjudication is performed.

## Adjudication and contextual reread

The user confirmed the three corrections, including the N08 row label
clarification: N01 row 3 1940 = 5; N04 row 6 1920 = 13,961; N08 row 5
Urban total = dash. All intermediate truth and result files remain preserved.
The final adjudicated cell-only baseline is 183/188 numeric matches,
24 TP, 6 FP, 0 FN, 4 uncertain document-input cells; precision 80%, recall
100%. Four nonnumeric tokens are outside the numeric-only score.

`scripts/scanned_pdf_context_reread.py` creates an image-only contextual
packet for each of eight previously adjudicated scopes. All row labels,
column headers and intervening rows remain visible; markers are drawn outside
the source raster instead of over the figures. The same assistant transcribed
all 192 positions from these packets (not just failed cells) and evaluated
against unchanged adjudicated truth. Results: 188/188 numeric matches,
24 TP, 0 FP, 0 FN, 0 uncertain, precision 100%, recall 100%. Artifacts are
under `image-input-review-v2/context-reread-v1/`.

This is a **retrospective development reread with known prior outcomes**,
not an independent holdout or a measured production accuracy. Numeric-only
thresholds are met on the observed cohort; no claim about row/column swaps,
automatic localization, or independent model performance. Freeze the context
packet method and test new untouched scopes with independent truth and a
source-only reader before any promotion. Business HOLD.

## Frozen contextual new-page evaluation

Eight new pages from the already acquired eight sources were scoped:
N01 p6, N02 p11, N03 p13, N04 p15, N05 p10, N06 p13, N07 p15, N08 p25.
They contain previously unscored table positions, but source PDFs and some
table series are shared with development; this is a page-level holdout, not
document-level independence. No candidate OCR text or previous answer values
are included in the packet. The unchanged contextual method preserves row and
header images with external R/C markers. The v1 packet was superseded before
truth review to include additional header/label context; v2 is frozen.

`context-new-page-v2/reviewer/review.html` contains 192 positions with 175
unverified OCR-layer draft values and 17 needing entry. The candidate
transcription of all 192 positions was captured from raster packets before
the user truth CSV exists. It is stored separately as `candidate-images/
context-reads-v1.json` (SHA-256
`bbd3dc2e7458d31d6697bfb27c838c2b4d3f6d44cc68fda4c449b9f0d2a02629`).
Same-assistant geometry inspection is explicitly disclosed; no independent
model execution. Manifest binds context hashes and 24 numeric faults; the
evaluator rejects tampered context images. Truth review remains pending;
no prospective score yet. Business HOLD.

## Context new-page initial result

User-provided 192-cell manifest-bound CSV was archived unchanged. The
previously frozen reader hash matched. Results: 178/187 numeric matches
(95.19%), 5 excluded nonnumeric cells, 24 TP, 16 FP, 0 FN, 0 uncertain;
precision 60%, recall 100%, thresholds NOT MET. Nine unique mismatches;
`context-new-page-v2/disputed-new-page-v1.png` shows full row text and
enlarged numeric regions without highlighting over content. Five values
appear potentially mis-entered in human truth (N03 R8 C1, N06 R2 C1,
N08 R1 C2, R3 C2, R7 C1); four appear AI digit confusions. Preserve the
initial score and request explicit adjudication before any alternate score.
Business HOLD. This confirms that the prior 100% retrospective result did
not establish generalization to new page scopes.

User adjudication finalized all nine differences. Three human truth entries
were corrected (N03 R8 C1 = 1,654; N06 R2 C1 = 11,609; N08 R1 C2 =
96,062,627). The other six human values were explicitly confirmed. The
unchanged frozen candidate scored 181/187 (96.79%), 24 TP, 10 FP, 0 FN,
precision 70.59%, recall 100%. The initial 60% remains preserved. Full
adjudicated results are in `context-new-page-v2/adjudication-v2/results.json`.
No promotion; business HOLD.

## Context / independent-engine cross-reader development

For all 192 positions, source-only contextual raster crops were read by
Tesseract.js in two frozen preprocessing views (scaled autocontrast and
native-scale padded grayscale). No sheet or truth values were passed to OCR.
Both views share the same OCR engine and are not independent of each other;
they are independent-engine evidence relative to the primary visual read.
The original adjudicated dataset was reused for retrospective diagnosis.

Hard confirmation requires first-read discrepancy, both valid OCR readings
matching it, and OCR confidence >=80. All disagreement remains UNCERTAIN.
The 187 numeric-eligible positions across clean/corrupt variants yield:

| Strategy | TP | FP | FN | Uncertain | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Visual only | 24 | 10 | 0 | 0 | 70.59% | 100% |
| Both OCR views | 7 | 2 | 17 | 25 | 77.78% | 29.17% |
| Scaled OCR only (diagnostic) | 9 | 2 | 15 | 23 | 81.82% | 37.50% |
| Native OCR only (diagnostic) | 9 | 2 | 15 | 23 | 81.82% | 37.50% |

All 17 unconfirmed actual faults remain in the uncertainty queue; reviewing
all 34 flagged document-input positions (9 confirmed, 25 uncertain) covers
24/24 injected faults, but this is queue coverage, NOT automated recall or
verified human-assisted performance. Review queue size is 34/374 numeric
document-input positions (9.09%). The independent OCR engine remains too
weak for hard gating. Do not promote the strict policy or relax thresholds
retrospectively. Future candidate: independent high-quality vision reader
with explicit row/column context, or separately evaluate an assisted review
product and its actual human effort. Artifacts in `cross-reader-v1/`.

## Assisted review prototype

`assisted-review-v1/review.html` contains the 34 queued document-input
positions in shuffled order, with source raster context, external R/C
markers, sheet value, match/error/unknown decisions, and correction entry.
The page does not embed the evaluator's truth or variant labels. It records
visible-tab review time and exports packet-bound JSON. The answer key is
separate; `python3 -m scripts.scanned_pdf_assisted_review --submission PATH`
scores the completed submission, including faults outside the queue.
This is a retrospective usability exercise on previously inspected sources
with synthetic spreadsheet errors; timing is not an independent benchmark
and no manual baseline or human performance claim has been established.
Business HOLD pending review and independent validation.

Completed user submission (2026-11-22): 34/34 reviewed; 24 TP, 0 FP,
0 FN, 0 unresolved; precision and recall 100% on this retrospective cohort.
Exact correction values matched previous adjudicated truth in 21/24 cases
(87.5%). Disagreements: N02 R1 C1 (1688 vs 688), N02 R7 C3 (1679 vs 679),
N08 R4 C2 (8241560 vs 8241500). The first two entered corrections equal
the sheet value despite an error decision. Preserve the existing truth and
submission; do not adjudicate automatically. Visible-tab time was 561.631 s
(median 9.495 s/item; mean 16.519 s/item; one item 199.139 s). Queue share
34/374 = 9.09%, not a measured time-saving percentage. No manual baseline;
shared-source retrospective usability result only. Business HOLD.

## Assisted review v2 and new-document intake

The archived v1 packet and result remain unchanged. V2 blocks corrections
numerically equal to the sheet value (including alternate comma/decimal
formatting) in both UI and scorer. A source-raster enlargement beside the
sheet value uses the candidate location box without covering the digits;
the whole source table remains visible to resolve alignment uncertainty.
V2 development packet: `context-new-page-v2/assisted-review-v2/review.html`.
23 targeted tests pass; no new human performance measurement yet.

Acquired the Census 1940 Agriculture Volume II Idaho PDF at the official
source URL recorded in `assisted-independent-intake-20261122/reviewer/manifest.json`.
SHA-256 is distinct from every archived PDF. Page 4 (State Table 18) has a
raster image and a text layer, so it qualifies only for the image-input
stratum, not the scan-only stratum. Selected eight livestock/poultry rows
and three years (24 cells) from visual geometry, with empty truth inputs.
Candidate source-only packet and evaluator-side manifest are separated.
No OCR or candidate transcription executed, no human truth yet. This single
document is an initial pilot, not sufficient to establish generalization;
expand to more distinct documents and freeze the candidate process before
formal independent evaluation. Business HOLD.

User's independent pilot CSV received and validated (24 numeric cells).
Before opening the CSV, source-only visual transcription and both OCR views
were frozen. Visual exact agreement with user truth: 23/24 (95.83%). One
disagreement remains at I01 R5 C3 (human 29,249,088; visual 29,249,086);
keep human truth unchanged pending adjudication. On 48 clean/corrupt
positions and three synthetic faults, strict auto-confirmation yielded
2 TP, 0 FP, 1 FN (uncertain), precision 100%, recall 66.67%. Queue included
all three injected errors with five total entries (10.42% review share).
The V2 assisted review packet is available under
`assisted-independent-intake-20261122/assisted-review-v2/review.html`.
Actual human-assisted accuracy and time on this new document remain pending.
Single-document, three-fault diagnostic; no product qualification.

Independent-document V2 user review completed: 5/5 queue entries, 3 TP,
0 FP, 0 FN, 0 unresolved, precision/recall 100% against the frozen human
truth, and all 3 corrected values exact. Visible-tab time 114.394 seconds
(median 14.117 seconds/item). Queue share 5/48 (10.42%). The original
submission is preserved in `assisted-review-v2/assisted-review-results.json`.
This is a single-document, three-synthetic-fault usability diagnostic; no
measured manual baseline or commercial demand evidence. Business HOLD;
prioritize customer workflow and willingness-to-pay validation before
investing in further repetitive manual cohorts.
