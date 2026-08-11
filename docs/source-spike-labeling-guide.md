# Source Spike Human Labeling Guide

Version: 1.0.0

## Purpose

This labeling pass measures whether a source contains analyzable demand evidence. It does not judge whether an idea is commercially attractive. Label the source text before viewing automated extraction or scoring results.

The initial 20 items per source are a screening sample. Ten are development examples and ten are a sealed holdout. Do not use holdout labels to tune rules or prompts. Expansion to 40 items and statistical source comparison belong to the next experiment slice.

## Labels

### Problem signal

Mark `problem_signal=true` only when the text identifies a concrete actor or situation, a friction or unmet need, and an observable consequence or desired outcome. Generic anger, unsupported praise, news summaries, and vague statements such as “this is bad” are negative.

### Money signal

Mark `money_signal=true` when the author describes an economic commitment or consequence. Choose exactly one primary type:

- `purchase`: an actual product or service purchase
- `subscription`: recurring paid use
- `outsourcing`: paying another person or firm to do the work
- `labor_cost`: meaningful employee or personal time spent on the problem
- `loss`: revenue, inventory, penalties, or other economic loss
- `willingness_to_pay`: explicit intent or budget to pay
- `price_complaint`: price is part of the concrete problem
- `replacement_search`: seeking a paid alternative or replacement

Set `structural_money_signal=true` only when the signal appears in the author’s text or decision context, not merely in platform metadata. For example, a “verified purchase” badge alone is not a money signal.

### Usable evidence

Mark `usable_evidence=true` when a short quote from the original text could support an Opportunity Card without inventing missing context. The quote must be specific enough to show who has the problem, what happens, or why it matters.

### Noise

Mark `noise=true` for advertising, self-promotion without demand evidence, bots, copied content, link-only posts, generic news, or content unrelated to a user problem. Noise can still contain keywords; label its meaning, not its vocabulary.

## Review procedure

1. Read only the normalized source item and its original URL when context is required.
2. Assign every boolean independently; do not infer one label solely from another.
3. Record a concrete `label_reason` of at least 20 characters, citing the decisive detail. Explain borderline calls explicitly.
4. Use the assigned reviewer ID and review round. Items marked for double review receive independent primary and secondary labels.
5. Do not reconcile disagreements until both reviews are complete. Preserve both original labels.
6. Keep holdout results sealed until source rules and extraction prompts are frozen.

Do not include personal identifiers in labels or reasons. Refer to “the author” or the described role.
