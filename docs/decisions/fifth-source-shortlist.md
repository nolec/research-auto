# Fifth persistent source shortlist

> Evaluated: 2026-08-19
> Scope: feasibility only; no adapter, corpus, or analysis collection

## Decision

Evaluate exactly three official-data candidates under the frozen persistent-evidence gate.
Do not lower the stable-author requirement to rescue an otherwise attractive source.

| Candidate | Access and reuse | Stable author independence | Signal fit | Verdict |
|---|---|---|---|---|
| CFPB Consumer Complaint Database | PASS | FAIL | strong money and marketplace problems | NOT_ELIGIBLE under the frozen contract |
| CPSC SaferProducts | PASS | FAIL | concrete product harm and manufacturer response | NOT_ELIGIBLE under the frozen contract |
| Wikimedia Phabricator | PASS, attribution required | PASS | strong problem evidence, likely weak money signal | PROVISIONAL capacity candidate |

The selected fifth-source candidate is **Wikimedia Phabricator**, but selection is limited to
the next aggregate-only capacity probe. It is not yet a qualified Source Spike source and no
source-quality verdict is implied.

## Hard gates

Each candidate is evaluated for an official API or download path, persistent storage and
processing rights, canonical source identity, publication time, stable cross-run author
identity, deletion and refresh behavior, 90-day evidence support, and plausible capacity for
100 valid observations. Problem and money-signal fit are recorded separately and cannot
override a failed compliance or identity gate.

## CFPB Consumer Complaint Database

The CFPB explicitly states that all published complaint data is freely available for anyone
to use, analyze, and build on. It provides CSV, JSON, and an Open Data API; narratives are
published only after consumer opt-in and personal-information scrubbing. Complaint IDs,
dates, products, issues, companies, company responses, and canonical records provide strong
provenance and unusually direct money and loss signals.

The public dataset deliberately omits consumer identity. A complaint ID proves a distinct
submission, not a distinct author, and the project cannot enforce its cross-run author limit
or verify independent authors. Under the frozen `stable_author_identity_required=true`
contract, CFPB is therefore not eligible as one of the five Source Spike sources. It remains
a valuable future aggregate market-signal dataset if the product later defines a separate
institutionally mediated evidence class.

Official evidence:

- https://www.consumerfinance.gov/data-research/consumer-complaints/
- https://www.consumerfinance.gov/complaint/data-use/

## CPSC SaferProducts

CPSC exposes publicly available incident reports through an official OData API. Published
fields include report number, incident and publication dates, incident description, product
and purchase details, manufacturer identity, and manufacturer comments. Data.gov marks the
dataset public-domain, and CPSC states that publicly posted information may be distributed or
copied. The intake process requires submitter identity and attestation before publication,
which improves evidence quality.

However, CPSC explicitly withholds the submitter's name and contact information from the
public database. Report numbers distinguish reports but cannot establish distinct authors,
so the same frozen author-independence gate fails. CPSC is not eligible for the current five-
source experiment, but it is a strong future candidate for a separately defined verified-
intake evidence class.

Official evidence:

- https://www.saferproducts.gov/FAQs/FrequentlyAskedQuestions11
- https://www.saferproducts.gov/FAQs/FrequentlyAskedQuestions3
- https://www.saferproducts.gov/Business/Acknowledge?source=signIn
- https://catalog.data.gov/dataset/saferproducts-api

## Wikimedia Phabricator

Wikimedia Phabricator exposes public bug reports and feature requests with stable task IDs,
canonical URLs, creation times, project tags, and registered authors. Public information is
readable anonymously, and the documented Conduit API supports task search. Wikimedia's
terms support programmatic reuse; contributed material is subject to the applicable free
license and attribution requirements. Collection must exclude restricted-policy and security
tasks and retain task URL, author attribution reference, and applicable license provenance.

This candidate is structurally close to GitHub and probably has weak direct money signals.
Those are source-value risks, not feasibility blockers. The next action is an aggregate-only
capacity probe covering multiple non-overlapping project strata. Only a passing probe may
lead to a frozen smoke manifest and 10-record real smoke.

Official evidence:

- https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Phabricator_Terms_of_Use
- https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use
- https://www.mediawiki.org/wiki/Phabricator/Permissions
- https://www.mediawiki.org/wiki/Phabricator/Help#API_(Conduit)
- https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits

## Next action

Create a separate plan for a non-persistent Wikimedia Phabricator capacity probe. The probe
must establish anonymous API accessibility, four-project capacity, stable author completeness,
public-policy visibility, timestamp and text completeness, cursor continuity, rate limits,
and attribution provenance while retaining aggregate counts only.
