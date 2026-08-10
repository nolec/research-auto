# Demand Intelligence V1 PRD

## 1. Product Goal

V1 converts public internet signals into reviewable Opportunity Cards. It does not generate business ideas or make final investment decisions. Its job is to find problems supported by observable behavior, separate evidence strength from business actionability, and reduce a human review to five minutes or less per card.

The first user is the project team itself. The four-week goal is to produce at least five trustworthy opportunities from a frozen model's final TOP 20.

## 2. Core User and Problem

The core user continuously searches for viable business opportunities. Ideas are cheap, but collecting enough evidence to judge recurring pain, loss, spending behavior, solution gaps, and growth is expensive and inconsistent.

V1 automates collection, extraction, grouping, evidence checks, and ranking. A human keeps authority over the final decision.

## 3. Product Contract

The pipeline is:

`public documents → extracted observations → evidence groups → problem clusters → evidence status → actionability status → review value → TOP 20 → human audit`

The unit delivered to the user is an Opportunity Card, not an idea. Every factual claim that affects a decision must link to source evidence. Inferred customer segments are labeled as inference and never count as evidence.

## 4. Decision Layers

### 4.1 Evidence Status

Evidence Status answers only whether the problem and associated economic behavior are supported by public observations.

The initial `provisional-v1` EVIDENCE-BACKED gate requires:

- at least five independent authors;
- at least three independent evidence groups;
- at least ten cases published within the latest 90-day window;
- at least two concrete loss observations;
- at least two observations of willingness to pay, actual spending, or paid substitute behavior;
- at least three representative source links; and
- an explicit counter-evidence assessment with no critical counter-evidence.

Allowed states are `INSUFFICIENT_EVIDENCE`, `CONFLICTING_EVIDENCE`, `EVIDENCE_BACKED`, and `NEEDS_REVIEW`.

### 4.2 Actionability Status

Actionability Status answers whether the evidenced problem is a plausible product or service target for this team. It must not become EVIDENCE-BACKED merely because the problem is frequent.

The initial ACTIONABLE gate requires observed support for the actor, a current solution behavior, at least two solution-gap observations, a scope that can be reduced to a product or service, an accessible customer channel, and no known legal or policy blocker.

Allowed states are `ACTIONABLE`, `NOT_ACTIONABLE`, and `UNKNOWN`.

### 4.3 Review Value

Review Value ranks candidates only after the evidence and actionability gates have run. Frequency establishes eligibility but does not directly increase rank.

The initial score is:

`30% Money Signal + 25% Loss Severity + 20% Solution Gap + 15% Growth + 10% Evidence Diversity - Duplicate Concentration Penalty - Uncertainty Penalty`

The TOP 20 is therefore the set most worth a person's limited review time, not the twenty most frequently mentioned problems.

## 5. Evidence Independence

Evidence is grouped conservatively. Observations from the same author, the same thread, a concentrated time window in one community, highly similar text, or a shared external event may belong to one evidence group. The system does not attempt to identify the same person across platforms. Unknown independence is retained as uncertainty and discounted rather than treated as independent.

## 6. Opportunity Card

Each card contains:

- observed actor and separately labeled inferred customer segment;
- normalized problem statement;
- Evidence Status and Actionability Status;
- Review Value Score;
- independent author, evidence-group, and recent-case counts;
- growth status;
- loss, money, current-solution, customer-channel, solution-gap, supporting, counter, and blocker evidence;
- explicit counter-evidence and blocker assessments;
- current alternatives, a productizable-scope assessment, and a blocker assessment;
- explicit uncertainties;
- automatic decision and reasons;
- optional human audit;
- source, model, prompt, and policy versions.

The machine-readable contracts are `schemas/evidence.schema.json` and `schemas/opportunity-card.schema.json`.

## 7. Human Audit

The fourth-week frozen model produces TOP 20, five boundary candidates, and five stratified random candidates. Duplicate clusters are audited once unless their material evidence changes.

The auditor checks whether core quotations match their source meaning, evidence groups are independent, loss and money signals are classified correctly, decision states match policy, and critical counter-evidence is missing. Median audit time must not exceed five minutes per card.

## 8. Four-Week Success Criteria

- Final TOP 20 contains at least five unique cards that are both EVIDENCE-BACKED and ACTIONABLE after human audit.
- Automatic EVIDENCE-BACKED positive precision is at least 80% on the audited sample.
- Boundary-sample error rate is at most 30%.
- Audited cluster merge error is at most 10%.
- Median card audit time is at most five minutes.

Random-sample miss rate is diagnostic in V1 because the sample is too small to establish a reliable recall target.

Weeks one through three are for source selection, implementation, and calibration. Model, prompt, policy, and thresholds are frozen before the fourth-week evaluation.

## 9. Failure Policy

- Low TOP 20 yield triggers actionability and ranking review before adding sources.
- Low Evidence precision triggers extraction, independence, and evidence-policy review.
- High merge error blocks scoring work until clustering is corrected.
- Excessive audit time reduces card evidence volume and simplifies the audit surface.
- A source failure is isolated; remaining sources continue.
- Unsupported claims are excluded from scoring.
- Missing history produces `UNKNOWN` growth rather than an estimated value.
- A changed model, prompt, or policy starts a new evaluation version.

## 10. V1 Scope Exclusions

V1 excludes dashboards, external SaaS features, private or terms-violating collection, interview-dependent validation, deep research, automatic MVP design, country-gap analysis, automatic investment decisions, and unsupported market-size estimates.
