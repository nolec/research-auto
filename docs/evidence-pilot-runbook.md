# Evidence pilot: local review packet

This offline command renders one bounded, frozen, document-conversion or documentation-checking candidate for review. It does not make API calls, collect records, infer source identity, conduct human review, or promote an Opportunity Card. Every packet is `PILOT_REVIEW_ONLY`, `HOLD`, and `UNKNOWN` for actionability and growth.

## Prepare approved inputs

1. Before inspecting results, freeze the candidate actor, task and failure, public source, broad and focused queries, sampling method, cap (1–20 per arm), date window and timezone-aware `as_of`. Preserve selection limitations and avoid silent substitutions.
2. Import exact public source snapshots locally. Retain original source links, publication-date precision, full source text, and metadata. Mark unknown metadata as unknown; do not synthesize timestamps from calendar dates. Use separately generated structured AI extractions, not the production provider.
3. Build a manifest with the exact contract in the [implementation plan](superpowers/plans/2026-11-20-evidence-first-vertical-slice.md). Compute `protocol_hash` as the SHA-256 of the UTF-8 JSON of the manifest excluding `protocol_hash`, with sorted keys, `ensure_ascii=False`, and separators `(',', ':')`.
4. Build the matching review per the [membership review guide](evidence-pilot-review-guide.md). Use `AI_PROPOSAL` until a human actually reviews the candidate. Verify original source records and quote meaning independently; if any frozen inputs need changing, create a revised manifest, recompute the hash and bind a new review. Never modify an existing run.

## Generate a packet

From the repository root with the project Python environment (use `python` in environments where that is the configured interpreter):

```sh
python3 -m src.evidence_pilot_cli \
  --manifest /path/to/manifest.json \
  --review /path/to/review.json \
  --out-dir artifacts/evidence-pilot/new-run-id \
  --extraction-mode 'separate-session structured AI annotations'
```

The default extraction mode is `separate-session structured AI annotations`; use `--extraction-mode synthetic` for test fixtures. These are caller-declared modes, not authenticated provider metadata. Never label synthetic or otherwise unverified test inputs as a genuine research run.

The destination must be a new directory, including when a prior directory was empty. Invalid input is rejected before writing. Existing directories, files and symlinks are never overwritten. If a write fails mid-run, there may be an incomplete directory without a valid receipt; obtain a new run ID for a retry.

| File | Contents |
| --- | --- |
| `manifest.json` | Byte-for-byte original source and extraction snapshot |
| `review.json` | Byte-for-byte original attributed review or AI proposal |
| `packet.json` | Candidate, summary, decision boundary, and every reviewed/proposed/unreviewed occurrence |
| `index.html` | Static bilingual report, containing escaped source links, exact quotes, reasons, counts and gate deficits |
| `receipt.json` | Locked protocol hash, SHA-256 of original review bytes, SHA-256 of the other four artifact bytes, declared extraction mode, input counts, and null audit duration/findings until separately measured |

The receipt does not hash itself. An identical pair of inputs and declared extraction mode produces the same bytes in any new destination. This command checks structure and quote offsets, not whether an original source is truthful or a reviewer really performed an audit.

## Human review of the rendered packet

Open `artifacts/evidence-pilot/new-run-id/index.html` locally in a browser (on macOS, `open artifacts/evidence-pilot/new-run-id/index.html`). No local server, JavaScript or external page resources are required. Following a source link is an explicit browser navigation to that source.

1. Start timing the actual human audit and confirm the candidate actor, task and failure, frozen protocol and source record provenance.
2. Inspect source links, full preserved text and exact extraction quotes. Verify whether the quoted meaning actually supports the proposed membership; record reasons for `DIRECT`, `ADJACENT`, `REJECT` or `UNREVIEWED`. A validated span does not establish semantic meaning.
3. Inspect loss and payment separately. Direct willingness to pay, actual direct expenditure or payment for a direct substitute must concern the exact failure. Adjacent spending is not direct economic evidence.
4. Inspect negative, contradictory and uncertain findings. Counter status `NOT_ASSESSED` is not an absence of critical evidence. Record verified counter findings and rationale even on rejected or adjacent rows.
5. Check broad/focused reviewed denominators and overlap. `0/0 — UNAVAILABLE` does not mean zero yield. The `AI proposed direct / proposals` column is a separate occurrence count, not a human precision measure. Date-only publication records are retained but not counted toward recency; all records, including proposals, appear in the publication precision table. A comparison can only be descriptive and must be labeled invalid if unmatched.
6. Check the exact gate deficits, identity conflicts and uncertainty. Note which losses, payments and quote meanings were not established, what improvements are needed, and stop timing. Record elapsed time and actual reviewer findings in a separate attributed audit record linked to the run and receipt hashes. Until there is a genuine timed review, leave duration and findings null. Do not edit an earlier receipt or manufacture a human decision.
7. If source verification or review decisions change, generate a new hash-bound run. A reviewable `HOLD` is a legitimate result; no pilot outcome establishes production calibration, rank, or V1 acceptance.

## Test the command offline

```sh
python3 -m pytest tests/test_evidence_pilot_cli.py -q
python3 -m pytest -q
```

Tests use invented inputs and do not establish real-world review findings.
