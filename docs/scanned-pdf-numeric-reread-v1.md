# Numeric reread v1 — development policy freeze

2026-11-22 KST. Scope: isolated numeric confirmation component, not a full
benchmark, not a replacement for the existing comparator, business HOLD.

## Fixed policy

1. A prelocalized source cell with a numeric first reading and a different
   numeric sheet value is eligible. Valid numbers are signed decimal strings
   with optional conventional comma grouping. Unsupported formats are uncertain.
2. Send only the source crop to the independent local OCR reader. Do not send
   first value, spreadsheet value, fault schedule or ground truth to it.
3. Use the original crop, English Tesseract single-line mode, confidence >=80
   and <=100. Require matching crop SHA-256. No threshold tuning on holdout.
4. Confirm a discrepancy only if independent numeric readings agree. If they
   disagree (even if reread agrees with the sheet), or evidence is unavailable,
   return UNCERTAIN with the original candidate and reason. Never correct values.
5. Cache reads by source crop within a batch. Score each document-input variant
   separately; the evaluator matches document/page/cell, consumes at most one
   expected event per detection, and counts unresolved actual errors as FN.
   Uncertain alert count is also reported separately.

The module does not independently locate cells, validate crop geometry against
the full page, or classify row/column swaps, missing cells and label errors.
An upstream comparator must supply prelocalized numeric candidates; other event
types remain under its existing policy. Matching initial reads can still hide
errors; the evaluator must count such missed errors as FN. Agreement is not
proof of correctness. The first-read model, geometry extraction and source
crop preparation are not yet frozen; thus no independent benchmark may start
until they and the dataset/evaluator are separately frozen.

## Component freeze fingerprint

| Component | SHA-256 |
|---|---|
| numeric_reread.py | `4c2ca2d66f45d71bbaee9d9282636d7d9a5dc95013cd94ea7e205d69c9b68dbb` |
| local_ocr.py | `02c1af0853c71238095d1ef054c00abe4f356500201111addb116b285f72b507` |
| local_ocr.cjs | `5c78d765664f3aadfd42a3c1ba16500ca769c7e2498e08d2e8f135e65c82e241` |
| numeric_evaluation.py | `24e22dbfaf11e4f6cae57fc00c86bed2cd1a9f6c39ca92802558d28b5b9943de` |
| eng.traineddata (local) | `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2` |

Observed runtime: Node v22.23.2, tesseract.js 7.0.0. Component hashes above
identify this candidate, not a complete reproducibility manifest; runtime asset
hashes still need binding before a held-out evaluation.

## Status and next step

The historical 30 TP / 0 FP result was a non-blinded visual reread using known
truth, not a measurement of this new OCR adapter. A generated development crop
`123,456` was recognized at confidence 96, confirming a deliberately different
sheet value. This smoke test establishes connectivity only.

Next: select ten previously unseen actual public scanned documents, verify
permissions and image-only status, freeze table scopes without inspecting
candidate results, obtain genuine human-verified truth, and freeze the full
first-read/crop pipeline. Keep candidate inputs separate from truth. Evaluate
clean and corrupted variants with all five event classes, precision >=95%,
recall >=90%, and report uncertainty and baseline comparison. Human timings
remain PENDING. Do not promote the opportunity or alter historical results.
