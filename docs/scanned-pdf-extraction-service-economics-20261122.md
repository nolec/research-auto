# Extraction + verification service economics

2026-11-22 KST. Decision: **HOLD generic extraction product; conditional GO for a small, manually fulfilled paid offer**. The original standalone verification demand gate remains failed. The adjacent offer is a new hypothesis, not a replacement gate counted as passed.

## Competitive price and capability evidence

| Source | Published offer | Implication |
|---|---|---|
| [Upwork: scanned documents to Excel](https://www.upwork.com/services/product/admin-customer-support-your-pdf-scanned-documents-or-invoices-converted-into-clean-excel-tables-2110982447253254041) | $9 for up to 10 pages, totals checked and unreadable items noted | Low-price competitors already offer checking |
| [Upwork: PDF/scanned files to Excel](https://www.upwork.com/services/product/admin-customer-support-pdf-and-scanned-files-converted-to-excel-2120780876082083863) | $20/5 pages, $40/15, $80/30; source comparison and uncertain fields | Direct substitute, dense scans require sample |
| [Upwork: checked Excel](https://www.upwork.com/services/product/admin-customer-support-your-scanned-pdfs-or-invoices-extracted-into-a-checked-excel-sheet-2120225551716008981) | $49/$149/$399; OCR, totals checks and highlights | Premium offer exists; scope differs |
| [AWS Textract](https://aws.amazon.com/textract/pricing/) | Table extraction $0.015/page (US West Oregon, first 1M pages) | Commodity automated extraction inexpensive; not a human verification service |
| [Freelancer: same-layout PDF forms](https://www.freelancer.com/projects/optical-character-recognition/pdf-excel-data-entry-40825456) | Buyer budget $250–750; permitted OCR, demands complete accurate template output | Adjacent buyer signal, field types and actual volume unverified |

Seller prices are asking prices, not proof of completed orders. No evidence of a durable moat or willingness to pay extra specifically for source-linked exceptions. Our differentiator to test is traceability (page/row/column plus source crop and before/after values), structured numeric data, and explicit unresolved status; not a claim that competitors lack these features.

## Retrospective extraction diagnostic

Existing frozen candidate readings were evaluated against their archived user truth. The same confidence threshold (80) and agreement of the primary visual read and both preprocessing views of Tesseract were applied as a *new retrospective extraction acceptance rule*; no sheet value is available in extraction. Both OCR views are one engine. `python3 -m scripts.scanned_pdf_extraction_economics` reproduces this analysis; no new candidate model was executed.

| Corpus | Numeric cells | Visual read errors | Accepted by rule | Queue | Accepted errors |
|---|---:|---:|---:|---:|---:|
| Development new pages | 187 | 6 | 74 | 113 | 1 |
| Idaho one-document pilot | 24 | 1 | 11 | 13 | 0 |
| Total | 211 | 7 | 85 | 126 | 1 |

Primary exact agreement: 204/211 (96.68%). Extraction queue 126/211 (59.72%); accepted precision 84/85 (98.82%); queue contains 6/7 primary errors (85.71%). One incorrect accepted cell means queue-only extraction is not qualified. In the earlier *comparison* task a preexisting sheet was available and the queue included approximately 10% of document-input positions; those figures do not apply to extraction. Selection is manual geometry on known documents, not an end-to-end arbitrary-document extraction benchmark. Human truth may contain residual errors; no new adjudication or user verification performed. Full human checking required for customer deliverables.

## Cost scenarios

Assume Upwork 15% fee (official range 0–15%: [fee policy](https://support.upwork.com/hc/en-us/articles/211062538-Learn-about-the-Freelancer-Service-Fee)); Freelancer fixed projects 10% or $5 minimum ([fee policy](https://www.freelancer.com/feesandcharges)). Use Upwork 15% in table. Labor valuation $15/h, 15 minutes fixed overhead (mapping, inference, communication, delivery), $1 nonlabor reserve, full human check. These are assumptions, not measured costs. Measured visible-tab review times from five *comparison* items on Idaho: median 14.117 s/item, mean 22.879 s/item. Applying them to all extraction cells is a proxy only; mapping, extraction, revisions, acquisition costs, taxes and payment/currency fees may be higher. Mean scenario is not a worst-case guarantee.

Contribution = price * 0.85 - $15 * (15 + cells * seconds / 60) / 60 - $1.

| Pilot price | Numeric cell cap | Median proxy contribution | Mean proxy contribution | Mean proxy total time |
|---|---:|---:|---:|---:|
| $19 | 100 | $5.52 | $1.87 | 53 min |
| $19 | 500 | -$18.01 | -$36.26 | 206 min |
| $25 | 100 | $10.62 | $6.97 | 53 min |
| $49 | 250 | $22.19 | $13.07 | 110 min |
| $79 | 500 | $32.99 | $14.74 | 206 min |

Original $19/500-cell hypothesis fails when applied to extraction. Mean-proxy breakeven at 500 cells is $61.66. Do not publish 500-cell package until actual timing and cost data support it. First offer $25 up to 100 numeric cells or 2 readable fixed-layout pages, whichever reached first; sample approval and non-sensitive printed numeric tables only. $25 yields 21.25 after assumed fee; at $15/h and $1 reserve, a 60-minute full workflow leaves $5.25 contribution. If measured effort forecast exceeds 60 minutes, decline or requote. Do not market as 100% automated or guaranteed accurate.

## Minimal paid experiment (draft, not published)

Title: **Convert scanned numerical tables into Excel with source-linked quality checks.**

Deliverables: editable CSV/Excel-compatible data, source coordinates per numeric value, exception list (source image + uncertain entry), human-confirmed corrections and explicit unresolved values. One layout, no handwriting, personal/medical/financial records, or regulated use; no unapproved external model processing. Free preview 1 row (max 10 cells), scope confirmed before quote. No site/account/infrastructure spend. For pilots all numeric cells checked; preserve original source.

- Gate A: one public sample with source-linked report and a complete stopwatch measurement (including mapping, extraction, QA, delivery) before any offer goes live. Do not count known-source sample as independent accuracy benchmark.
- Gate B: offer to 10 qualified inbound opportunities via authorized platform workflow (no automated unsolicited contact). Track sample acceptance, $25+ paid acceptance, exact rejection reasons. Success: two distinct paying-pilot acceptances and one completed payment. No payments or outreach completed yet.
- Gate C: actual completed pilot contribution >= $5 at $15/hour labor and actual fees, no known missed errors after full review; time reduction >=50% against measured equivalent manual workflow. If traffic insufficient, inconclusive; if no acceptance after ten qualified conversations, HOLD or revise once. Do not build automatic alignment/billing before paid signal.

No new full product implementation, publication, bid, message or spend in this phase.
