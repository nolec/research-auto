# Excel to PDF synthetic diagnostic

Fixed three-workbook experiment; not a general customer conversion service. It tests print geometry, exact synthetic table data, chart-title retention, and source-file hashes. It does not establish Microsoft Excel rendering equivalence or market demand.

Run from the repository root using the existing bundled runtime. The fresh temporary directory keeps all prior results intact:

```sh
runtime="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"
pilot_dir=$(mktemp -d)
"$runtime/node/bin/node" experiments/excel_pdf/excel_pdf_fixtures.mjs \
  "$runtime/node/node_modules" "$pilot_dir/raw"
"$runtime/python/bin/python3" -m experiments.excel_pdf.excel_pdf_pilot \
  "$pilot_dir/raw" "$pilot_dir/output" "$runtime/native"
```

Requires the already installed artifact-tool, LibreOffice headless and pypdf. Do not use customer files. Review the PDF pages separately before drawing visual conclusions. Historical measured outputs are under `outputs/excel-pdf-pilot-20261124/`, and the original pilot report is `docs/excel-pdf-pilot-20261124.md`. The two scripts were moved from `artifacts/evidence-pilot/` without code changes.
