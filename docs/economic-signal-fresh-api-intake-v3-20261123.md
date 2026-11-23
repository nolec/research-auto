# Fresh economic-signal API intake v3

2026-11-23 KST. Supersedes the search-locator acquisition method in `economic-signal-fresh-collection-v2-20261123.md` before retaining any records. The v2 search produced index, release, and other ineligible results; no records were retained or labeled. Keep the historical document. Existing source-spike compliance decisions require official APIs and take precedence over HTML retrieval. No Steam community profile search or HTML scraping.

## Frozen API acquisition

- Date window: 2026-08-25 to 2026-11-22 inclusive, based on author publication date (UTC calendar date). Preserve timestamp precision.
- GitHub official public issue search API: repository `pandas-dev/pandas`, `is:issue created:2026-08-25..2026-11-22`, two arms: `spreadsheet` and `export`. Sort `created`, descending, at most 10 results per arm (`per_page=10`). Retain the first five eligible distinct original issue bodies per arm, ordered by returned rank. No comments, PRs, exploit/security issues, personal data, duplicates or previously stored IDs/content. Search API response body is source text; no HTML fallback. Local-only short excerpt, canonical URL, publication time, document identifier, source, SHA-256. Do not retain author identifiers or raw payloads.
- Stack Exchange: official documented questions API only; Steam: official Steamworks review API only; TED: official Search API only (existing reviewed privacy, retention, and authorization policy). These strata remain HOLD until the corresponding bounded fresh collection manifests and permitted access are available. No source substitution. Do not reuse historical spent collection authorization.
- Target 10 per source, total 40. If a quota is insufficient, preserve the shortfall; no post-result query tuning or repeated search. No model extraction or gold review until the source snapshot is independently frozen.

Taxonomy, model, scoring, and independence constraints remain those of taxonomy v2 and the previous protocol. Collecting source data is not product validation. No existing labels, assignments, or outputs will be changed.
