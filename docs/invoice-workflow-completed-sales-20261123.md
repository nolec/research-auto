# Invoice workflow completed-sales discovery

2026-11-23 KST. Separate bounded follow-up; previous buyer lead and V7 unchanged. Three search arms, one search each, six results maximum and four direct eligible pages per arm. Public direct evidence only, no login, no retry or access bypass. Distinguish marketplace completed project with displayed awarded price, customer-reported payment, public contract award, seller list price and buyer request. Award/review does not establish cash settlement. Exclude personal information, private financial records and unrelated workflows. Record only canonical link, public project identifier, price/currency, status, task, date precision, and limitations. Do not infer current opportunities from historical records or count duplicate projects as independent buyers.

| Arm | Query |
|---|---|
| Completed freelance reconciliation | `site:freelancer.com/projects "invoice" "reconciliation" "Completed" "awarded" automation CSV` |
| Public award | `site:find-tender.service.gov.uk "accounts receivable" "software" "contract award" invoice` |
| Commercial delivered work | `site:upwork.com/services "invoice reconciliation" "reviews" automation CSV` |

## Observed results

Four completed Freelancer projects, three direct and one adjacent, with displayed awards. Two nonzero award displays (USD 50 and USD 400), two zero displays (unknown price, not proof of free work). No verified completed cash payment, exact publication date, or independent buyer identity. Public award query returned no result; commercial-delivered arm yielded seller listings/generic reviews rather than exact completed transactions. No access restriction bypassed.

The direct small-file workflow offers a narrower test than enterprise ERP automation. A proposed service could reconcile two anonymized CSV files and report unmatched/partial/duplicate payments without modifying accounting records or accessing accounts. The historical USD 50 award is a price reference, not a proven attainable sale; the USD 400 award corresponds to substantially broader work, so do not average the two. Confidence remains HOLD. Source-specific observations saved in `artifacts/extraction/calibration/audit-local/invoice-workflow-completed-sales-20261123/observations.json`. No engine or production gate changes. Recommend a small buyer-facing validation of the narrow deliverable before product investment, or continue cross-category opportunity discovery if the user prefers not to pursue this niche.
