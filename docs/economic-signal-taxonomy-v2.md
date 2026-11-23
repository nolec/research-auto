# Economic signal taxonomy v2 — proposed evaluation contract

Date: 2026-11-23 KST. Development protocol only; historical v1 labels, v4/v5 results and official PRD gates remain unchanged. The taxonomy measures evidence, not automatic business value or likelihood of a sale.

## Independent dimensions

Each dimension is `yes`, `no`, or `unknown`. A positive requires a short exact source-text span and a reason. Missing evidence is not evidence of absence. Do not infer one dimension from another.

| Dimension | Positive criterion | Do not count |
| --- | --- | --- |
| `procurement_intent` | Buyer explicitly solicits a supplier, requests a purchase, states order scope or a purchasing mechanism | Product descriptions, project scope without a buying commitment, third-party advertisements |
| `budget_or_willingness_to_pay` | Explicit amount, budget, or stated willingness to pay | Inferred ability to pay, assumed budgets, estimated revenue |
| `contract_awarded` | Explicit award or executed contract reported in the source | Invitation to bid, planned contract, candidate selection alone |
| `actual_payment` | Explicit completed payment or reported paid expenditure | Budget, displayed award, posted price, contract value alone |
| `economic_loss` | Concrete economic consequence or loss stated | Speculative revenue impact |
| `labor_burden` | Meaningful work or necessary-task time burden stated | Voluntary leisure, generic inconvenience, assumed hourly cost |

Additional fields: `transaction_stage` (solicitation/planned/awarded/paid/unknown), reported amount and currency only if stated, evidence span, source URL, date precision and a short limitation. Do not convert a procurement opportunity into proof of unmet demand, completed payment or actionable online work. A document can support several dimensions if each has separate source support. Distinguish an explicit author statement from independent transaction verification.

## Development cases (already exposed)

Use the eleven rows documented in `economic-signal-v5-ted-audit-20261123.md` only for taxonomy discussion and semantic examples. Preserve frozen historical gold. Their proposed interpretations are not independent gold and must not be used as holdout evidence.

## Fresh evaluation protocol

The four qualified historical source runs contain 400 records, including 80 assigned records and 320 unassigned. On 2026-11-23 an ID-only check confirmed that all 320 unassigned IDs are present in `artifacts/research-console-20261120.html` (80/80 per source). The console rendered rule-based results; individual human/model exposure is not established, but the corpus cannot substantiate an untouched claim. Treat it as exploratory, not a new independent holdout.

1. Freeze taxonomy, schema, model, prompt, source access policy, queries, acquisition caps and scoring policy before a new collection. Use authorized public sources, independent documents and explicit date precision; avoid sensitive data. No bypass or collection of private information.
2. Target 40 fresh documents: 10 each from four source strata (GitHub, Stack Exchange, Steam, TED), including positives, negatives and resolved/ordinary procurement cases; do not force quota or substitute silently if acquisition is insufficient. Deduplicate against previously stored IDs and content hashes and retain exposure limitations. An evaluation sample is not a market prevalence estimate.
3. Freeze a prediction-free snapshot and separate gold sidecar. Human/independent reviewer labels each dimension against the snapshot without seeing predictions; resolve disagreement before scoring or retain unknown and report explicitly. No new model calls until source and version bindings are recorded.
4. Run inference on the exact same snapshot without gold. Validate source spans independently; preserve individual invalid/unknown states, reject operational/tool failures, and record per-dimension and per-source predicted positives, true positives, false positives, false negatives, abstentions and invalid counts. Report precision and recall only when denominators exist. Keep v5 label-space results separate; optional legacy comparison requires independently defined mapping, not post-hoc reclassification.
5. Evaluate decision support separately: problem, recurrence, competing solutions, source independence, actual payment, accessible online delivery, and cost. No automatic product promotion from signal-only metrics. Official PRD evidence/actionability gates are unchanged.

## Status

`PROTOCOL_DRAFTED / FRESH_CORPUS_NOT_ACQUIRED / GOLD_PENDING / NOT_EVALUATED`. New acquisition and independent labeling are outstanding. Existing results are untouched.
