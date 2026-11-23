"""Run existing extraction logic on saved public documents and inspect outputs."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from time import perf_counter
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.extraction.development_slice import extraction_to_observation
from src.extraction.opportunity_slice import build_vertical_slice
from src.extraction.rule_baseline import _extract


def runs():
    return sorted((ROOT / "artifacts/source-spike").glob("*-analysis/runs/*/collection-result.json"))


def analyze(path: Path, limit: int):
    started = perf_counter()
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for item in data["items"][:limit]:
        doc = {key: item[key] for key in (
            "document_id", "source", "title", "text", "published_at", "source_url"
        )}
        row = {key: doc[key] for key in ("document_id", "source", "title", "source_url")}
        try:
            output = _extract(doc)
            observation = extraction_to_observation(doc, output, source_metadata={
                "document_id": doc["document_id"], "author_hash": item.get("author_hash"),
                "community": item.get("community"),
            })
            assessment = build_vertical_slice([observation], input_contract="extracted-observation-v1")
            row.update(output=output, assessment=assessment)
        except (ValueError, TypeError, KeyError) as exc:
            row.update(error=str(exc))
        rows.append(row)
    return {"run_id": data["run_id"], "source": data["source"], "available": len(data["items"]),
            "engine": "rule_v1", "elapsed_seconds": round(perf_counter() - started, 4), "rows": rows}


def render(result: dict | None, available_runs=None, snapshots=None) -> str:
    template = (ROOT / "docs/research-console.html").read_text(encoding="utf-8")
    payload = json.dumps(result, ensure_ascii=False).replace("<", "\\u003c")
    options = json.dumps(available_runs or [], ensure_ascii=False).replace("<", "\\u003c")
    cached = json.dumps(snapshots or {}, ensure_ascii=False).replace("<", "\\u003c")
    return template.replace("/*__RESULT__*/ null", payload, 1).replace("/*__RUNS__*/ []", options, 1).replace("/*__SNAPSHOTS__*/ {}", cached, 1)


def serve(port: int):
    candidates = {path.parent.name: path for path in runs()}
    options = [{"id": key, "source": path.parents[2].name} for key, path in candidates.items()]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{port}":
                self.send_error(403)
                return
            url = urlsplit(self.path)
            if url.path == "/":
                self.respond(render(None, options), "text/html")
                return
            if url.path != "/api/analyze":
                self.send_error(404)
                return
            try:
                query = parse_qs(url.query)
                run = query["run"][0]
                limit = int(query["limit"][0])
                if run not in candidates or not 1 <= limit <= 100:
                    raise ValueError("Invalid run or limit")
                result = analyze(candidates[run], limit)
            except (KeyError, ValueError):
                self.send_error(400)
                return
            self.respond(json.dumps(result, ensure_ascii=False), "application/json")

        def respond(self, body, content_type):
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Research-Auto: http://127.0.0.1:{port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--run", help="Saved run ID (see --list)")
    parser.add_argument("--limit", type=int, default=100, choices=range(1, 101), metavar="1-100")
    parser.add_argument("--output", type=Path, help="New HTML result file")
    parser.add_argument("--serve", action="store_true", help="Open the local execution UI")
    parser.add_argument("--snapshot", action="store_true", help="Export a standalone browser UI with all saved runs")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.serve:
        serve(args.port)
        return
    candidates = runs()
    if args.snapshot:
        if args.output is None or not candidates:
            parser.error("Snapshot needs saved runs and a new --output path")
        snapshots = {path.parent.name: analyze(path, 100) for path in candidates}
        options = [{"id": key, "source": value["source"]} for key, value in snapshots.items()]
        with args.output.open("x", encoding="utf-8") as output:
            output.write(render(None, options, snapshots))
        print(f"Exported {len(snapshots)} runs: {args.output}")
        return
    if args.list:
        for path in candidates:
            print(path.parents[2].name, path.parent.name)
        return
    matches = [p for p in candidates if p.parent.name == args.run]
    if len(matches) != 1 or args.output is None:
        parser.error("Choose a saved --run and a new --output path; use --list first")
    result = analyze(matches[0], args.limit)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(render(result))
    print(f"Processed {len(result['rows'])} documents: {args.output}")


if __name__ == "__main__":
    main()
