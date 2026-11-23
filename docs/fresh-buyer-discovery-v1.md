# Fresh buyer discovery — V1

The previous 40-document exploration used a historical, purposive corpus. Every publication was outside the 90-day window. A second problem was the separation of complaint-heavy sources from buyer-heavy sources, producing many isolated groups rather than recurring, economically relevant problems.

## New discovery workflow

1. Select 3–5 narrow recurring tasks from the exploratory queue, each defined by actor, task, failure and exact vs adjacent fit. Freeze each search arm and its maximum result count before the next run.
2. Search recent public buyer listings in separate arms so one high-volume keyword does not crowd out the others. Track buyer posts independently from seller advertisements, generic procurement and support complaints. Use authorized search interfaces or approved official APIs only; stop at direct access restrictions.
3. Import observed listing ID, source URL, publication date precision, buyer requirement, stated budget, access status and fit. Search-index entries are leads only. Exact calendar days are provisional freshness, not independently verified timestamps. Relative dates remain unknown.
4. Run `python3 -m src.extraction.fresh_buyer_intake SNAPSHOT.json NEW_RESULT.json` to reject wrong sources, duplicate listing IDs, out-of-window dates and off-scope rows. Per-arm caps are enforced. No buyer identity is inferred from a listing ID. Budget, hiring and actual payment remain separate.
5. Independently audit source meaning and buyer independence for shortlisted direct cases; then seek counter-evidence, actual spending and accessible customer channels. Keep the PRD evidence gate unchanged. Do not generate authoritative cards from index-only data.

## 2026-11-22 initial discovery

The 18-row snapshot is a retrospective purposive result of the search, not a pre-registered collection experiment. Search coverage and capped import are not the same as automatic marketplace collection. Source selection and fit annotations are AI assisted. Four direct Upwork page opens returned 403; the direct Freelancer consolidation listing was opened. No access restriction was bypassed, no paid API call or buyer contact occurred.

| Arm | Imported | Direct-fit | Recent day-only direct | Direct budget shown |
|---|---:|---:|---:|---:|
| Spreadsheet quality | 8 | 4 | 2 | 4 |
| Existing flow troubleshooting | 5 | 2 | 1 | 1 |
| Internal software renewal governance | 5 | 0 | 0 | 0 |

The six direct-fit listings are not six independent buyers. One possible buyer overlap is retained without identifying people or establishing an identity match. The initial CRM-oriented results often involve sensitive customer records, low posted budgets and heavy proposal competition, so they are not automatically eligible for our service. A single consolidation listing shows a $30–250 stated range and a displayed award, not a payment. The 90-day gate, repeated purchasing, market size and actionability remain unverified. All arms HOLD; official opportunity output is unchanged.

Next experiment: prioritize non-sensitive multi-file spreadsheet reconciliation and existing workflow troubleshooting, with current direct-access buyer sources, exact-fit criteria and separate comparison arms. Keep generic typing and new automation projects as adjacent evidence only. Do not enlarge the collection until the direct-fit/independence problem is resolved.
