# Evidence pilot membership review

This local pilot evaluates one candidate in benign document conversion or checking. A proposal is not a human audit, and a pilot candidate is not an Opportunity Card. No membership label itself promotes a candidate.

## Freeze the candidate and source record

Before reading results together, lock the candidate ID and its relevant actor, task and failure. For example: a document editor exporting a document to preserve its footnotes, where export drops footnotes. Record the exact manifest protocol hash. Review decisions are keyed by document ID; a decision applies to the same preserved document in both arms, not independently to each occurrence. Do not modify the hashed manifest to improve results.

The human source verification flag is in the manifest. Set it to true only after comparing the supplied source identity, URL, publication date (if known), and supplied metadata to the preserved public source. Missing identity details remain unknown. If a source needs correction or verification after freezing, create and rehash a revised manifest and bind a new review to it; never silently change a hashed row. A valid URL and a valid quote offset are not source verification.

## Review contract

The review object has these exact keys:

| Field | Required value |
| --- | --- |
| `protocol_hash`, `candidate_id` | Exact values from the validated manifest |
| `actor`, `task`, `failure` | Nonblank candidate definitions |
| `reviewer` | Nonblank reviewer attribution |
| `review_kind` | `HUMAN` for an actual human decision; `AI_PROPOSAL` for preliminary annotations |
| `decisions` | Object keyed by known document IDs; omit undecided IDs |

Each decision has the following exact fields:

| Field | Review rule |
| --- | --- |
| `membership` | `DIRECT`, `ADJACENT`, `REJECT`, `UNREVIEWED` |
| `reason` | Nonblank explanation comparing actor, task, and failure |
| `quote_meaning_verified` | Boolean; human actually confirmed the quote's meaning in context |
| `membership_quote` | Required for `DIRECT`; otherwise optional/null |
| `loss_direct` | Boolean; true only for a specific loss caused by the candidate's failure |
| `loss_quote` | Required when loss is true; otherwise optional/null |
| `economic_kind` | `DIRECT_WTP`, `DIRECT_SPEND`, `DIRECT_PAID_SUBSTITUTE`, `ADJACENT`, `NONE`, `UNKNOWN` |
| `economic_reason` | Nonblank explanation of why the behavior does or does not support payment for this exact task |
| `economic_quote` | Required for any DIRECT economic kind or `ADJACENT`; otherwise optional/null |
| `counter_signal` | Boolean; concrete counter evidence is present |
| `counter_quote` | Required when counter signal is true; otherwise optional/null |
| `counter_assessment` | `NOT_ASSESSED`, `NONE_CRITICAL`, `CRITICAL`, `UNCERTAIN` |
| `counter_rationale` | Nonblank explanation of what was checked and the remaining uncertainty |

Every nonnull quotation reference must be an exact `{"quote": "...", "start": 0, "end": 3}` object using the existing validated extraction quote and integer offsets (end exclusive). Values in this illustrative object are placeholders; use the actual extraction values. Merely finding another substring of the document is not enough. The extraction contract currently supports one quote. If the one quote does not substantiate both the failure and the economic or loss signal, use a separately validated reviewed record or leave the additional signal uncounted. A quote can be reused for multiple fields only when a human finds it actually supports each claimed meaning; the code can check exact identity, not semantic sufficiency.

## Membership and signal rubric

- `DIRECT`: same relevant actor, task and failure, with a usable extracted problem and validated supporting quote. An abstention or unusable extraction cannot be direct.
- `ADJACENT`: superficially related vocabulary or workflow, with a different actor, task or failure. Exporting footnotes into a bibliography is adjacent to preserving footnotes in a converted document, even though both say “export” and “footnotes.”
- `REJECT`: no relevant problem, unrelated actor/workflow, or misleading association. Preserve the row and explanation for audit.
- `UNREVIEWED`: no actual decision yet; no affirmative findings or counter assessment. Missing decisions default to this state.

Economic kind is narrower than a generic money mention. A buyer saying they would pay to restore missing footnotes supports `DIRECT_WTP`. A buyer describing an actual purchase specifically to correct that export failure supports `DIRECT_SPEND`; payment for a manual correction service instead supports `DIRECT_PAID_SUBSTITUTE`. A paid unrelated export feature, seller's list price, hiring salary/budget, generic price complaint, or general conversion subscription does not establish direct payment for missing footnote restoration. If there is evidence of related spend but the connection is not direct, use `ADJACENT`. A demonstrated loss by itself is not payment evidence. Use `UNKNOWN` when payment was not established and `NONE` only when a human actually assessed the available evidence and found no economic signal.

For counter review, look for existing free satisfactory fixes, cancellation of the problem, contradictory reports, unreproducible or obsolete failures, and evidence that the actor does not actually need this task. Do not infer absence of critical counter evidence from positive documents or model silence. A human chooses `NONE_CRITICAL` only after explicitly assessing counter evidence, `CRITICAL` only when there is an affirmative supporting quotation, `UNCERTAIN` when the assessment is inconclusive, and `NOT_ASSESSED` when there has been no counter review. State the rationale in all cases. An AI proposal cannot assert human quote verification or human counter findings.

## Output and eligibility

`review_membership` returns one audit row per arm occurrence, broad then focused. It preserves all six original row fields and the decision fields, plus `arm`, `document_id`, `observation` (the existing adapter envelope), `review_kind`, `reviewed`, `eligible`, `loss_eligible`, `economic_eligible`, and `counter_eligible`.

- `reviewed` means an actual HUMAN non-UNREVIEWED decision; it does not by itself verify a source or quote.
- `eligible` requires HUMAN review, DIRECT membership, and both explicit source and quote-meaning verification flags. Verified loss and direct economic counts are gated by `loss_eligible` and `economic_eligible` respectively.
- `counter_eligible` requires a human-reviewed decision, verified source and quote meaning, and a counter assessment other than `NOT_ASSESSED`. It does not require DIRECT membership, so reviewed negative and adjacent records are not lost. An uncertain assessment remains uncertain.
- AI-proposed DIRECT labels are retained for human checking but do not count as reviewed or eligible. Source verification already in the manifest is preserved; an AI review cannot create it. The code cannot authenticate a reviewer's identity, so attribution must be truthful.

Overlapping rows remain visible here and must be deduplicated conservatively in the subsequent summary. All unknown evidence and missing reviews remain visible; no gate is passed merely because a label exists.
