# Independent public scan holdout — candidate intake

2026-11-22 KST. Status: SCAN_PREFLIGHT_COMPLETE; 16 new local PDFs,
ten selected page scopes pass mechanical scan preflight, zero human-verified
answers, no candidate execution. Final corpus freeze remains pending.
The existing 1950 Statistical Abstract files are excluded, including unused
sections already downloaded in the development run. Do not substitute them.

## Candidate queue (not yet accepted)

The following official Census Bureau URLs were discovered without inspecting
candidate results. These are distinct source files, not ten accepted table
scopes. Some share an institution and era; document/style diversity remains
to be checked during visual preflight. Federal authorship on the selected
tables, absence of third-party restrictions, no personal data and relevance
must be checked individually; public hosting alone is not proof of rights.

| ID | Subject | PDF source |
|---|---|---|
| H01 | Historical irrigation | https://www2.census.gov/prod2/decennial/documents/13400387.pdf |
| H02 | Historical drainage | https://www2.census.gov/prod2/decennial/documents/08536390.pdf |
| H03 | Internal migration | https://www2.census.gov/library/publications/decennial/1940/population-internal-migration/41272177_ch5.pdf |
| H04 | Occupation by region | https://www2.census.gov/library/publications/decennial/1940/population-volume-3/33973538v3p4ch03.pdf |
| H05 | Population summary | https://www2.census.gov/library/publications/decennial/1940/population-volume-2/33973538v2p1ch2.pdf |
| H06 | Labor force sample statistics | https://www2.census.gov/library/publications/decennial/1940/population-labor-force-sample/41236810p2_ch3.pdf |
| H07 | Housing general characteristics | https://www2.census.gov/library/publications/decennial/1940/housing-volume-2/housing-v2p1-ch2.pdf |
| H08 | Housing small-area statistics | https://www2.census.gov/library/publications/decennial/1940/housing-volume-1/housing-v1p1-ch2.pdf |
| H09 | Agriculture general statistics (1930) | https://www2.census.gov/library/publications/decennial/1930/agriculture-volume-4/03337983v4.pdf |
| H10 | Historical wholesale survey | https://www2.census.gov/wholesale/pdf/mwts/historic/1936.pdf |

Rights reference: https://www.usa.gov/government-copyright (verify federal
authorship and any exceptions for each selected scope). Wholesale index:
https://www2.census.gov/wholesale/pdf/mwts/historic/.

## Intake, scope and freeze order

1. Acquire original PDFs through authorized network access. Save separately
   from historical artifacts, record URLs and SHA-256. Compare all historical
   source hashes, then visually check for near-duplicate tables or repeated
   statistics across publications. A different byte hash alone is insufficient.
2. Use `src.scanned_pdf_experiment.holdout_intake` to check the selected pages
   have no extractable text and contain raster images. This is a mechanical
   preflight, not evidence that the page is a legible table or public domain.
3. Before running candidate inference, choose one table scope per document
   and preserve the page/crop geometry, source permissions and scope hash.
   Reject unsuitable inputs before evaluation; document any replacements.
   Require 8–20 rows, 3–6 columns, unique visible semantic keys and at most
   120 data cells; avoid personal records. Retain visual inspection evidence.
4. Obtain actual independent human verification of all selected cells. Do not
   infer approval from an LLM transcription or use it as verified ground truth.
5. Freeze the first-read model/runtime, crop-generation path, numeric v1
   component and full comparator/evaluator, including their code/runtime
   hashes. Freeze clean/corrupt variants and event schedules separately from
   candidate inputs (30 faults across ten documents, six of each of five types).
6. Execute once after freeze; count uncertainty as FN when an expected event
   is not detected. Report precision, recall, uncertainty, per-type breakdown
   and baseline results. Maintain HOLD and human timing PENDING.

## Observed blocker

`curl -IL --max-time 15` against the H03 source returned exit code 6:
`Could not resolve host: www2.census.gov`. This is an execution-environment
download failure, not evidence that the public URLs are unavailable elsewhere.
No network workarounds, paid services, OCR or benchmark execution attempted.
Resume once original PDFs are available locally through authorized access.

## Browser acquisition follow-up (2026-11-22 KST)

Chrome can reach the source server. Two original PDFs were downloaded and
copied without overwriting to `artifacts/scanned-pdf-experiment/public-holdout-20261122/source/`.
Both were checked against all twelve historical public PDF hashes and are byte-distinct.
Rendered page previews are in `preflight/`; no inference or truth verification was run.

| ID | SHA-256 | Selected page | Embedded text characters | Image count | Result |
|---|---|---:|---:|---:|---|
| H03 | `3c872782c999b0a19eeeb84eae221c4c58abcbd59e79b6b0f1842d26ea818c3b` | 1 | 7,879 | 1 | Reject under image-only rule (text layer present) |
| H04 | `1a175d47bf29be8c8e4ac1a35e04265caa6552a07d9934f26ee5574fd5a91abb` | 8 | 0 | 1 | Mechanical pass; rights, truth, distinct table check pending |

H03 candidate scope: Table V, male employed block, first five NUMBER columns.
H04 candidate scope: Table 10, male operatives block, first 16 rows, State and
Urban four numeric columns. H03 must not be counted as accepted or stripped
of its text layer to manufacture eligibility under the fixed rule. Replace it
with a distinct eligible image-only source before freezing. Eight queued
downloads remain outstanding; nine more mechanical passes are required. Browser
downloads worked but tool latency was substantial, so intake is still incomplete.

## Acquisition completion (same day)

The above was an intermediate snapshot. Fresh browser tabs with one download
per tab enabled the additional acquisitions. 16 distinct local PDF hashes;
none matches the 12 historical public source PDFs. The following ten **selected
pages** each have exactly one raster image and zero extractable text characters.
All were visually inspected as aggregate statistical tables. No OCR inference
was run. The remaining six files are not members of the selected cohort.

| ID | PDF page | Draft scope | SHA-256 |
|---|---:|---|---|
| H04 | 8 | New Mexico Table 10, male operatives, first 16 rows, State/Urban four count columns | `1a175d47bf29be8c8e4ac1a35e04265caa6552a07d9934f26ee5574fd5a91abb` |
| H05 | 12 | US Table XII, first 10 industry rows, employed total/male/female | `67cd9c2ba862cfc34b6addf11136b171d012eb22c996091ba675f4e8974aaa48` |
| H06 | 12 | US Table 1, service workers excluding domestic/protective, group total and nine following rows; all ages, ages 20–24/25–29/30–34 | `9fc368cfc806c19feb20b81fb52d59e9a9ca78b0c791fac0e14e0f2a7488bbe5` |
| H09A | 5 | Farms and farm property Table 1, all land in farms through all other land, 1930/1925/1920 | `12b5fcc28a55ae4a0c6c53440a6ff4299574cc82c1b2e674b22d91421dd1c9af` |
| H10 | 2 | Wholesale sales, Automotive products through Lumber and building material, firm count and three sales months | `03bedb1745a6cdd55d8ffbd8dde4061758537baaab38dd10226644150bb526dc` |
| H13 | 5 | Idaho Table 5, Urban Total, 1940/1930/1920/1910, 12 rows; four count columns and grouped year/nativity keys | `d01a943fb47cc47474e0113270f8dffee8f0982ba24c24b8e0415069f5b3bada` |
| H14 | 8 | Maryland Table 7, Urban 1940, under 5 through 75+, all classes total/male/female | `fd813847598bbaefbf013956030ef6d12f9bfdebb01a0de25d26f6a90d0f9cd5` |
| H15 | 12 | New Hampshire Table 10, first 12 state data rows, total and 21+ population 1940/1930 counts | `df5b9ea14fcd10887009e9512c4efd8fa7ed4988f8b7ac6e2fc77c381a5ee72b` |
| H16 | 2 | Texas Table 23, employment status, 14+ through in institutions, Bailey/Bandera male/female | `5af0242cb2e9f7929ea13b54f68046a2c0d9f3c507f442ad247eda6d69ff07d2` |
| H18 | 2 | Arkansas Table 3, state total/male/female, nonwhite and urban groups, employed/private wage/government counts | `3a30e56d0366c3daaf22432b5ccc39bd59c38456e37a8f5e4e487f0f7f5824cf` |

Additional original source URLs (other IDs use the original candidate queue):

- H09A: https://www2.census.gov/library/publications/decennial/1930/agriculture-volume-4/03337983v4ch02.pdf
- H13: https://www2.census.gov/library/publications/decennial/1940/population-volume-2/33973538v2p2ch5.pdf
- H14: https://www2.census.gov/library/publications/decennial/1940/population-volume-2/33973538v2p3ch5.pdf
- H15: https://www2.census.gov/library/publications/decennial/1940/population-volume-2/33973538v2p4ch7.pdf
- H16: https://www2.census.gov/library/publications/decennial/1940/population-volume-2/33973538v2p6ch8.pdf
- H18: https://www2.census.gov/library/publications/decennial/1940/population-volume-3/33973538v3p2ch3.pdf

Excluded: H03/H07/H08/H11/H12 (text-layer or unsuitable scopes), H17
(illustrative household form/instructions, not an aggregate numeric table).
Only the selected ten pages may be used as prospective inputs, not the entire
source directory. H06 has text layers on other pages; only its verified
image-only page 12 is eligible under the page-level preflight rule.
H01/H02 were not acquired; the browser showed front-matter volumes rather than
the expected complete reports. H09A replaces the H09 front matter.

The selected files are byte-distinct but several belong to related Census
volumes. Their draft scopes use different table topics, states and layouts;
scope geometry, semantic-key uniqueness, third-party rights (especially H10
cooperative publication), and near-duplicate content review must be finalized
before freeze. `check_cohort` returned `SCAN_PREFLIGHT_COMPLETE` (10/10),
benchmark PENDING, business HOLD. No performance claim or human verification.

## Human review packet

The provisional review cohort has been narrowed to 82 rows and 328 cells
(10 tables, one semantic row key and three numeric columns per table).
`artifacts/scanned-pdf-experiment/public-holdout-20261122/human-review-v2/review.html`
contains editable, **unverified** visual drafts alongside enlarged source crops
and links to the full original page renders. The earlier v1 packet is superseded.
The v2 manifest digest is
`2f370e7944df0642475ad296b2e70c849e19e0e1603375c59c8d874eb755da58`.
The reviewer must compare every cell to the original before clicking the table
confirmation and exporting `holdout-human-verified.csv`. The evaluator rejects
incomplete, duplicate, unreadable, unverified, or mismatched-manifest cells.
No candidate reader has been run on these pages. The manifest and draft values
must remain evaluator-side only. Rights, near-duplicate checks, upstream pipeline
freeze and independent human truth remain prerequisites to an official benchmark.

## Human truth received

The reviewer exported and confirmed the 10 tables. The unmodified CSV is
`human-review-v2/holdout-human-verified.csv` under the cohort artifact directory
(SHA-256 `3077d669c9babd51210f84e12211da66062a06c42bfae60affca3b58e9766b81`).
The manifest-bound loader accepted all 328 cells. Compared with the explicitly
unverified visual draft, 75/246 numeric-column strings changed (30.49%);
none of the 82 row keys changed. This is a draft correction rate, not candidate
OCR accuracy. Of the reviewed numeric-column strings, 12 are em dashes and one
is `~` (H16, Class of worker not reported, Bandera male); preserve the raw
reviewer value and exclude unsupported nonnumeric values from numeric reread
eligibility. The pipeline freeze and remaining intake gates are still pending.

## Numeric diagnostic v1 (not an official benchmark)

On 2026-11-22, a fixed geometry-only numeric diagnostic was executed locally.
The geometry file contains 246 numeric-column crop coordinates and no answer
values. The source-only reader received image crops and geometry, not the
human CSV or manifest. The runtime/input/code freeze stored 90 SHA-256 hashes;
all matched after execution. The evaluator loaded the 328-cell human CSV only
after the source readings were recorded. Geometry was manually scoped, not
automatically discovered. H10 is used locally only; this does not establish
permission for redistribution. Census citation guidance:
https://www.census.gov/about/policies/citation.html

Both passes used the same Tesseract.js engine/model: first 3x grayscale with
white border and RAW_LINE, second original grayscale with SINGLE_LINE. Apple
Vision failed its development preflight, so these are **not independently
powered OCR engines**. The fixed schedule inserted 30 numeric changes, three
per table; all 233 supported numeric cells in each of 20 clean/corrupt inputs
were scored. Thirteen nonsupported numeric-column tokens were excluded.

| Method | TP | FP | FN | Uncertain | Precision | Recall |
|---|---:|---:|---:|---:|---|---:|
| First-pass mismatch | 0 | 0 | 30 | 466 | undefined | 0% |
| Numeric agreement | 0 | 0 | 30 | 466 | undefined | 0% |

Post-run diagnostics, not a retuning operation:

| Source read | Eligible cells | Valid numbers | Exact values | Valid at confidence >=80 | Exact among accepted |
|---|---:|---:|---:|---:|---:|
| First | 233 | 79 | 35 | 0 | 0 |
| Second | 233 | 154 | 94 | 86 | 62 |

Results: `numeric-diagnostic-v1/results.json`; freeze:
`numeric-diagnostic-v1/freeze.json`; source-only observations:
`numeric-diagnostic-v1/source-readings.json`. The first-read gate rejected
every eligible cell; even the second pass had 24 wrong accepted values.
Zero false positives therefore do not imply accuracy. Do not tune any
threshold or crop on this now-observed cohort and retitle it as blind. The
four nonnumeric event classes, automatic semantic matching, independent
engine, near-duplicate assessment and human timings remain unverified.
The existing 10 tables may serve as development data for the next engine
comparison; acquire a new untouched cohort for any subsequent confirmatory
claim. Overall benchmark NOT PASSED / NOT OFFICIALLY RUN, business HOLD.

## Visual cell development comparison v1

RapidOCR and ONNX Runtime package index probes returned no distributions in
the restricted execution environment. No new local OCR engine was installed.
Instead ChatGPT manually transcribed the same 246 original cell crops in
enlarged numbered contact sheets. This is a development observation with prior
cohort exposure, not a blinded API or production OCR evaluation. The captured
reads were saved before programmatic scoring in `vision-cell-development-v1.json`.
On the same 233 supported numeric cells, 231 matched the reviewed truth
(99.14%). The two disagreements are preserved, not silently corrected.

| Fixed 30-fault diagnostic | TP | FP | FN | Uncertain | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Visual cell mismatch | 30 | 4 | 0 | 0 | 88.24% | 100% |
| Visual first / original Tesseract confirmation | 11 | 0 | 19 | 23 | 100% | 36.67% |

Neither reaches both target thresholds. The visual result suggests crop-level
reading is worth investigating; Tesseract as hard confirmation limits recall.
No calibrated visual confidence, automated production reader, or independent
holdout is established. Human truth remains unchanged. Results and input
hashes are in `vision-cell-development-v1-results.json`. Next: establish a
working independent OCR engine or automated vision interface, freeze it on
development data, then evaluate a new untouched cohort. Business HOLD.

## Selective visual reread development v1

Only the 34 mismatching document-input cells were flagged for reread; identical
source image hashes were deduplicated to 32 crops, with randomized opaque
identifiers and source-only numbered image packets. The packets contained no
sheet values, first-read strings or expected fault labels. This was another
manual reading by the same assistant with prior cohort exposure, not an
independent model call. The new policy requires numeric agreement with a
hash-bound visual reread, without inventing numeric confidence scores. Missing,
invalid or disagreeing reads remain uncertain rather than silently dismissed.

All 32 readings repeated the initial numeric values, including the two
disagreements against the human CSV. On the same fixed 30-fault diagnostic:
30 TP, 4 FP, 0 FN, 0 uncertain; precision 88.24%, recall 100%. No improvement
over the first visual pass. 32/233 supported unique cells required a reread
(13.73%), or 34/466 document-input cells (7.30%) before deduplication. Source
truth was not modified. Same-assistant agreement is not proven independence;
the remaining two disputed source values merit independent adjudication, not
automatic replacement. Results: `visual-reread-development-v1/results.json`.
No official holdout or commercial readiness claim. Business HOLD.

## User truth adjudication v1

After being shown both disputed source crops, the user explicitly confirmed
H13 row 1 numeric column 2 as `463` (previously `468`) and H15 row 1 numeric
column 0 as `422,693` (previously `428,693`). The original CSV and prior results
are retained; the corrected 328-cell CSV passed manifest-bound validation.
Corrected truth SHA-256:
`a175973af5e157146134b10eb47f251ff556fbaf21e118661dd3d613a7f78bc2`.
The original 30 injected faults did not overlap the two corrected cells.
Rescoring the unchanged visual readings against corrected truth gives
233/233 numeric matches, 30 TP, 0 FP, 0 FN for both visual-only and selective
visual-reread policies. Visual/Tesseract agreement remains 11 TP, 0 FP,
19 FN. The rescore is retrospective and targeted after seeing discrepancies;
it is not evidence of an independently measured perfect accuracy. See
`human-truth-adjudication-v1/results.json`. Business HOLD; new untouched
cohort required for a prospective evaluation.
