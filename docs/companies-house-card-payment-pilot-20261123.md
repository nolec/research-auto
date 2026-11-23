# Companies House card expenditure pilot

Frozen before new row retrieval, 2026-11-23 KST. Official [2025 publication](https://www.gov.uk/government/publications/companies-house-government-procurement-card-spending-2025), fixed January, February, March 2025 CSV links from the document section. December 2025 was already exposed and is not fresh. Three files, one GET per file, 64 KiB/file, no redirects/retries, 100 CSV data rows per file; stop on access or schema error. The source terms are the GOV.UK Open Government Licence unless specifically excluded; no identity or sensitive fields retained. No supplier names, transaction identifiers, raw full CSV or personal records stored. Allowlist benign categories (case-insensitive exact): Software as a Service, Software, Software Licences, Software License, IT Equipment, Office Equipment, Office Supplies, Stationery, Training, H & S Equipment. Allow only Companies House entity / CH and exact month, positive amounts are reported card spending, negative/zero excluded from positive evidence and counted separately. No inference of unmet need, current purchase request, recurring purchases, or market demand. Keep only month, source URL, physical row ordinal, date, approved expense type, amount and currency; no free-text description/area. Identical normalized entries counted as duplicate within file (conservative lower bound; no identity claims). Data are exploratory structured evidence, not V7 free-text holdout. Use one-shot local result; no V7 changes or model calls. Source link bindings are resolved from the fixed official publication before direct CSV request. Record observed receipt and access limits.

## Preview-only diagnostic (after freeze)

The official January, February and March CSV previews displayed 10, 16 and 17 rows respectively. The web retrieval tool did not support direct `text/csv`; original CSV bytes were not validated in this environment. A temporary redacted transcription of the preview rows (no supplier/expense-area values) was processed by the adapter. This is an exploratory parser diagnostic, not a successful direct download or independent V7 evaluation. One February-file row was dated January and excluded under the frozen month rule.

| Month | Preview rows | Retained | GBP total |
| --- | ---: | ---: | ---: |
| [January](https://www.gov.uk/csv-preview/67adea8aa1d2c59f9ba29ac7/January_2025_GPC_spend.csv) | 10 | 8 | 27,117.88 |
| [February](https://www.gov.uk/csv-preview/67d82770752bf117d6c15e7d/February_2025_GPC_spend.csv) | 16 | 9 | 16,789.65 |
| [March](https://www.gov.uk/csv-preview/6814c72b359707ba3d44677d/March_2025_GPC_spend.csv) | 17 | 3 | 11,623.77 |

Execute the independently bounded raw CSV intake once from the user's network-enabled environment: `python3 -m src.source_spike.companies_house_card_intake --execute`. Stop on first access or schema error. A completed result is reported card-payment evidence only, not business opportunity validation.
