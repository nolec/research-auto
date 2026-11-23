# v5 economic-signal diagnostic (2026-11-23 KST)

Scope: review frozen development rows 29 and 31–40, not new holdout data. No gold labels, run artifacts, or acceptance thresholds are changed. This is a semantic review proposal, not independent adjudication.

## Observed disagreements

| Row | Frozen money type | v5 | Source interpretation |
| --- | --- | --- | --- |
| 31 | outsourcing | no | A solicitation with submission deadlines; future external-service procurement, not demonstrated payment. |
| 33 | purchase | no | The subject of an order is event organization; procurement intent, not completed purchase. |
| 36 | purchase | no | A planned purchase under a funded project; purchase intent, not evidence of transaction completion. |
| 37 | purchase | no | Contracting authority explicitly wants to purchase services; intent rather than completed payment. |
| 38 | purchase | no | Procurement scope includes supply and installation; no confirmed completed transaction. |
| 39 | purchase | no | Future purchases under a dynamic purchasing system; recurring procurement mechanism, not confirmed orders. |
| 40 | outsourcing | unknown | Contract scope describes planned external provision; payment and award are not established by the excerpt. |

Row 32 correctly detected a solicitation for outside services, although the timing of payment remains unverified. Row 34 only describes a requested service; row 35 describes a planned upgrade. Both frozen money labels are negative and should not automatically become positive merely because they come from TED. Row 29 (Steam) is a humorous account of discretionary leisure time; its v5 `labor_cost` positive is a false positive against the frozen label. Meaningful work-related burden must be distinguished from optional entertainment.

## Findings and decision

The seven misses are concentrated in procurement language, but the historical gold labels also collapse planned procurement and completed purchase/paid outsourcing. Under the existing guide, purchase means actual purchase. The v5 prompt requires explicit budget/intent and does not count completed purchase merely from procurement. Do not treat the seven misses as seven established payments or modify gold to inflate performance.

Proposed new contract: separate `procurement_intent` (explicit solicitation, order scope, purchasing mechanism, or buyer request), `budget_or_willingness_to_pay`, and `realized_payment_or_award` (award and payment separately); preserve loss and labor burden only with explicit consequential evidence. A procurement notice alone is not proof of market gap, payment, recurring demand, or deliverability. An ordinary service description without buying intent remains unknown/negative. Exact source support is required per dimension.

Next gate: version the taxonomy and labeling guide, independently adjudicate the ambiguous exposed development cases, then freeze an untouched, source-stratified comparison set with genuine procurement intent and negative controls. Do not claim improvement from relabeling the same 40 development records. No production promotion and no additional model calls in this audit.
