# V7 independent signal challenge — acquisition protocol

Frozen before retrieval, 2026-11-23 KST. Separate manual public-document challenge, not a production source connector, not a representative market sample. V7 and its historical 34-record run remain unchanged.

## Fixed acquisition

Use only publicly accessible official U.S. GAO report landing pages (`www.gao.gov/products/`), dated 2022–2025 inclusive, in English. Search index is a locator, not evidence. No login, crawling, sensitive topics, private data, or alternate access after denial. Exclude defense, cyber, biological, weapon-related, or personal-data reports. Retrieve up to six search results per arm, open only eligible direct report pages, retain first four distinct eligible reports in returned rank order per arm. Do not force quota, retry or substitute sources. Evidence-rich queries intentionally enrich candidates; eligibility does not imply a positive label. Target 20 total, no duplicate reports or excerpts. Store only a short exact source excerpt (max 25 words), title, URL, report ID, publication date, excerpt hash; no full pages. If context is insufficient retain unknown rather than guessing. Search arms are acquisition metadata and must not appear in model input.

| Arm | Fixed search query |
|---|---|
| Budget | `site:gao.gov/products "budget" "software" "million" GAO` |
| Payment | `site:gao.gov/products "paid" "million" "contractors" GAO` |
| Loss | `site:gao.gov/products "lost" "million" "payments" GAO` |
| Labor | `site:gao.gov/products "hours" "staff" "manual" GAO` |
| Controls | `site:gao.gov/products "guidance" "data collection" "recommendations" GAO` |

Use V7 six-dimension schema, prompt, projection and normalization without changes. Frozen SHA-256: V7 `5425863d969ea8acfcac98de634dce87e1f84bd9038f5f32b97c77e9f5a973a0`; CLI runner `cabfd89eb7e2f460159a7a841eb966cc09414131286de45bddb5d9bbc22230ef`; event parser `9e4cd7220a679835df97e5bac4fcc3751591d83ebf08a9d1e1e682819819f5ba`; taxonomy `6bec97bf837be64c70ff3880f00a29c103020839710c393a3529e54f6404bee7`. No model calls during collection; later separate runner must bind exact snapshot and versions, limit to one call per record. No historical data exposure claim beyond deduplication where observable. Independent human reviewer must label blind before inference or keep diagnostic-only status. Measure per-dimension positives, negatives, unknowns, invalid outputs, precision and recall where gold denominators exist; report small-sample limitations. No automatic product promotion or PRD gate changes.
