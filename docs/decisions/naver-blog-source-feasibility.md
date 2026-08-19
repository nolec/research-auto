# Naver Blog Search source feasibility

> Evaluated: 2026-08-19

## Verdict

- CURRENT API ACCESS: PASS
- PERSISTENT SOURCE SPIKE USE: BLOCKED
- FUTURE COMMERCIAL REUSE: SEPARATE CLEARANCE REQUIRED

Naver Blog Search authentication and response shape are technically viable. This is not a
finding that non-commercial use is prohibited. The unresolved issue is whether the API's
permitted search-result use includes a separately stored and automatically processed
research corpus; the current terms do not expressly grant that use.

## Verified technical access

A project-local Client ID and Client Secret were registered. A one-item, non-persistent
request to the official Blog Search endpoint returned HTTP 200 and included `title`, `link`,
`description`, `bloggername`, `bloggerlink`, and `postdate`. The check retained no credential,
query, response body, or result item.

## Blocking policy findings

General condition 7.3 restricts copying, storage (including caching), processing,
distribution, and third-party provision of acquired API information outside the scope
permitted by the terms. Search-specific condition 2.1 permits faithful, independent exposure
of search results and prohibits alteration or misleading composition. It does not explicitly
authorize building a separate persistent analysis corpus. The terms also state that rights
in result data remain with NAVER or the original rightsholder.

That ambiguity conflicts with the frozen product requirements:

- persistent 90-day evidence storage;
- LLM extraction, embedding/indexing, and derived-output storage;
- stable, reviewable evidence packets across runs;
- future commercial operation and reuse of collected evidence.

The legacy Search API is also being migrated to NAVER API HUB and is scheduled to end at
NAVER Developers on 2027-06-30, so any later clearance must cover the API HUB terms and
lifecycle rather than relying on the current credential alone.

## Re-entry conditions

1. Obtain authoritative written scope confirmation covering persistent result storage and
   automated processing for this exact non-commercial internal calibration workflow; or
   formally redesign Naver as a transient discovery index that stores no API result content.
2. For a transient path, evaluate each canonical original under its own access, storage, and
   reuse rules before it becomes evidence.
3. Separately confirm rights for any future commercial product.
4. Re-evaluate NAVER API HUB terms, authentication, quotas, and migration lifecycle.
5. Only then create a machine-readable feasibility decision and capacity probe.

Until an applicable path is cleared, no persistent Naver fixture, corpus, or analysis run
begins. A non-persistent feasibility probe may retain aggregate counts only.

## Sources

- https://developers.naver.com/products/terms/
- https://developers.naver.com/docs/serviceapi/search/blog/blog.md
- https://developers.naver.com/notice/article/32530
- https://developers.naver.com/notice/article/32973
