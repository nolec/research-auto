# Scanned PDF verification — commercial validation

Date: 2026-11-22 KST. Decision: **HOLD product build; GO paid-demand experiment**.

## Evidence boundary

- Development: 24/24 synthetic errors included in a 34/374 review queue; human correction 21/24, 562 seconds visible-tab time.
- New-document pilot: 3/3 synthetic errors included in a 5/48 queue; human review 3 TP, 0 FP, 0 FN, 3/3 correct corrections; 114 seconds visible-tab time. Single document, shared reviewer with truth creation, no manual timing baseline.
- These are feasibility signals only. No production accuracy claim, measured labor savings, real-customer demand, or willingness to pay for this product.

## Market evidence (publicly accessible, as of study date)

| Evidence | Observable finding | Limit |
|---|---|---|
| [Upwork buyer: PDF to Excel](https://www.upwork.com/freelance-jobs/apply/Convert-PDF-Excel-Advanced-Excel-Skills-Required_~022118076429848250872/) | $10–15/hour; requires verification against original and flagging unreadable content; 50+ proposals | Conversion plus verification, not standalone verification; no hire shown |
| [Upwork buyer: 50 financial statements](https://www.upwork.com/freelance-jobs/apply/PDF-Excel-Financial-Statements-into-One-Workbook_~022117661510782057317/) | $12 listed fixed budget, requires numeric cross-check, one hire | Actual payment unknown; low-budget segment likely unattractive |
| [Accounting forum](https://www.reddit.com/r/Accounting/comments/1p3gya9/is_it_normal_to_spend_3_days_manually_typing_data/) | Associate reports days of manual work on poor-quality scanned financial documents | Anecdote, not verified time baseline or purchase evidence |
| [Data entry service](https://www.upwork.com/services/product/admin-customer-support-accurate-data-entry-into-excel-or-google-sheets-verified-against-source-2113191384276651217) | $15/$30/$100 offer tiers; source checking and optional accuracy report | Asking prices, not booked sales |
| [Loan agreement workflow](https://www.reddit.com/r/ChatGPTPro/comments/1s87pvb/extract_structured_data_from_pdfs_to_excel/) | Second team repeats extraction for quality control; reports hundreds of hours annually | Self-report; regulated financial workflow unsuitable as first target |

## Competitors

| Offering | Main capability | Pricing signal | Implication |
|---|---|---|---|
| [DataSnipper](https://www.datasnipper.com/pricing) | Excel document matching and recognition, extraction, audit workflow | Demo/contact sales | Established direct competition; do not compete on broad audit suite |
| [IndexFrog](https://indexfrog.com/) | Excel source-document table matching and differences, auditor-oriented | Demo; public price not established | Direct competitor; no claim of unique matching functionality |
| [PDFHandle](https://pdfhandle.com/blog/check-spreadsheet-against-pdf) | Spreadsheet vs source text PDF, totals/matching | Free allowance described | Explicitly excludes scanned PDFs; possible narrow differentiation, not proof that market is underserved |
| [Docparser](https://docparser.com/pricing/) | Document extraction and Excel/CSV export | $39/mo monthly starter, $32.50/mo billed yearly; 100 credits/month | Extraction substitute, different scope |
| [Nanonets](https://nanonets.com/products/document-intelligence) | Confidence checks, field extraction, human review | Not established here | Review queues are already an industry feature |

## Initial offer hypothesis

Target: independent data-entry / digitization providers and small research/operations agencies already producing spreadsheets from scanned tables. They have a concrete deliverable and can provide a non-sensitive, de-identified example. Secondary targets: archival digitization teams; avoid financial statements, personal records, medical/legal data or compliance certification until appropriate security and domain validation exists.

Job: given an existing CSV and a readable scanned numeric table, confirm the mapping, identify suspected differences, provide original page/row/column images and a human-confirmed exception report. No extraction-only promise, automatic certification, unsupported file-wide guarantee, or silent repair.

Price hypothesis (not validated): $19 for one small batch of up to 5 readable, mapped pages / 500 numeric cells; one revision. Customer must supply existing CSV with clear row/column keys; no complex layout mapping, handwritten material, unbounded volume, or formatting conversion. Pilot includes explicit limitations and a human check of every eligible cell before final delivery until the queue policy is validated on customer documents. Offer a free 1-page / 30-cell preview without requiring sensitive documents. Do not collect payment outside a platform's rules.

## Seven-day validation plan

1. Day 1: create short sample before/after + exception report using public/demo data. Explain 3/3 test errors only as a small synthetic demonstration, not a guarantee.
2. Days 2–4: collect 20 distinct relevant buyer listings on authorized marketplaces; record URL, date, requested checking task, scope, budget, eligibility, and whether recurring. Count exact-fit and adjacent listings separately; no unsolicited contact or platform rule violations.
3. Days 3–7: publish an inbound offer or apply selectively to qualified jobs only after account/listing approval; do not spend on ads. Track unique qualified leads, sample requests, quotes, acceptance, actual completed payment and objections.
4. Work each accepted pilot using actual end-to-end timing (setup/mapping, inference, human checking, delivery, revisions), API cost, and marketplace fees. Protect customer data; no transmission to a model provider without clear consent. Compare against measured full manual review on a small same-document subset, with order randomized where feasible.

Decision gates (predeclared hypotheses, not market statistics):

- Problem evidence: at least 5 exact-fit buyer listings among 20 relevant listings, including at least 2 recurring workflows.
- Commercial signal: at least 2 independent qualified customers agree to a $19+ paid pilot, at least 1 completes payment; no free sample or verbal interest counts as revenue.
- Usability/economics: paid pilot fulfilled with no missed known discrepancies after full human verification and positive contribution after platform fees, API cost and labor valued at $15/hour. Measure time savings; target at least 50% end-to-end vs manual review at comparable accuracy.
- If insufficient traffic, classify inconclusive rather than no demand. If qualified traffic reaches 10 conversations and no paid acceptance, revise target/offer once; do not build a full SaaS. If success, run another paid cohort before automating further.

## Minimum implementation after initial signal

1. Local CSV import and PDF rasterization; explicit page/table and row/column mapping, reject unsupported layout or ambiguous cells.
2. Frozen visual reader + OCR cross-check; uncertainty queue, no automatic “verified” claim for unreviewed cells.
3. Side-by-side source, enlarged target, numeric correction validation, explicit accept/unknown, timestamped review trail.
4. Export original CSV unchanged, separately corrected CSV and exceptions CSV with source page, coordinate, before/after value and status. No silent overwrite. Client-local handling first; no accounts/billing/dashboard/integrations until repeat demand.

Initial capital target: zero paid advertising or new infrastructure; use existing prototype/demo and authorized marketplace access. No actual offer published or buyer contacted in this phase.
