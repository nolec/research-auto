"""Exploratory grouping of problem-positive saved source records."""
import argparse
import csv
from collections import defaultdict
from hashlib import sha256
from itertools import combinations
import json
import re

from src.research_console import ROOT, runs
from src.extraction.rule_baseline import _evidence_span, _extract, _problem_start


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def steam_problem_quote(row, output):
    text = row["text"]
    subject = re.escape(row["title"])
    praise = re.compile(
        rf"\b(?:cannot|can't)\s+(?:(?:recommend\s+(?:it|this|this game|this app|{subject})"
        r"\s+(?:highly\s+)?enough)|(?:but love it)|(?:believe I missed out on this(?=[.!?]|$)))\b",
        re.I,
    )
    # Mask only the idiom, retaining offsets and any complaint elsewhere in the review.
    remaining, count = praise.subn(lambda match: " " * len(match.group()), text)
    if not count:
        return output["evidence_quote"]
    position = _problem_start(remaining)
    if position < 0:
        symptom = re.search(r"\b(?:crashes|freezes|crashed|froze)\b", remaining, re.I)
        if not symptom:
            return None
        position = symptom.start()
    start, end = _evidence_span(text, position, position)
    return text[start:end]


def problem_quote(row, output):
    """Select source-specific evidence for exploratory grouping."""
    if row["source"] == "steam":
        return steam_problem_quote(row, output)
    text = row["text"]
    header = re.search(r"Type:\s*<b>Bug</b>", text, re.I)
    if row["source"] != "github" or not header:
        return output["evidence_quote"]
    body = text[header.end():]
    footer = re.search(r"\bVS Code version:\s*Code\b|<details>\s*<summary>System Info</summary>"
                       r"|\|Process Argv\|", body, re.I)
    if not footer or output["evidence_end"] <= header.end() + footer.start():
        return output["evidence_quote"]
    description = body[:footer.start()]
    actual = re.search(r"\bactual behaviou?r\b", description, re.I)
    if actual:
        description = description[actual.end():].lstrip(" \t\r\n:*#-")
        description = re.split(r"\s+\*\s+|\n|\bexpected behaviou?r\b", description,
                               maxsplit=1, flags=re.I)[0]
    elif not re.search(r"\b(cannot|fails?|disappears?|flickers?|crashes|broken|unable)\b",
                       description, re.I):
        return ""
    return description.strip()


def corpus(rows, *, include_excluded=False):
    versions = defaultdict(dict)
    for row in rows:
        key = row["document_id"]
        checksum = digest(row["text"])
        prior = versions[key].get(checksum)
        if prior is None or (row["source"], row["title"]) < (prior["source"], prior["title"]):
            versions[key][checksum] = row
    conflicts = sorted(key for key, values in versions.items() if len(values) > 1)
    by_text = {}
    docs = {}
    for key, values in sorted(versions.items()):
        if len(values) != 1:
            continue
        checksum, row = next(iter(values.items()))
        if checksum in by_text:
            docs[by_text[checksum]]["ids"].append(key)
            continue
        output = _extract(row)
        if output["problem_signal"]:
            quote = problem_quote(row, output)
            if quote is None:
                if not include_excluded:
                    continue
                quote = output["evidence_quote"]
            by_text[checksum] = key
            docs[key] = dict(ids=[key], source=row["source"], title=row["title"], quote=quote,
                             text_sha256=checksum, quote_sha256=digest(quote))
    return docs, conflicts


def clusters(docs):
    # Exact statement + title. Shared terms alone cannot create transitive links.
    groups = defaultdict(list)
    for key, doc in sorted(docs.items()):
        statement = " ".join(doc["quote"].casefold().split())
        title = " ".join(doc["title"].casefold().split())
        enough_context = title and len(set(statement.split())) >= 6
        signature = (title, statement) if enough_context else (key,)
        groups[signature].append(key)
    return list(groups.values())


def review_item(docs, key, checksum):
    for doc in docs.values():
        if key in doc["ids"] and doc["text_sha256"] == checksum:
            return {"title": doc["title"], "evidence": doc["quote"]}
    raise ValueError(f"Missing document or changed digest: {key}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="store_true", help="Show the frozen pairs without predictions")
    args = parser.parse_args()
    rows = [item for path in runs() for item in json.loads(path.read_text())["items"][:100]]
    docs, conflicts = corpus(rows)
    review_docs, _ = corpus(rows, include_excluded=True)
    pairs = []
    with (ROOT / "configs/cluster-development-pairs-v1.csv").open() as stream:
        for pair in csv.DictReader(stream):
            pairs.append([review_item(review_docs, pair[side], pair[side + "_sha256"])
                          for side in ("left", "right")])
    if args.review:
        result = pairs
    else:
        groups = clusters(docs)
        # Surface lexical neighbors for investigation, independently of the frozen review.
        terms = {k: set(re.findall(r"\w{3,}", v["quote"].casefold())) for k, v in docs.items()}
        neighbors = []
        for a, b in combinations(docs, 2):
            shared = terms[a] & terms[b]
            if len(shared) >= 4:
                score = len(shared) / len(terms[a] | terms[b])
                neighbors.append((score, a, b))
        result = dict(version=3, input_rows=len(rows), conflicts=conflicts,
                      praise_without_problem_signal=len(review_docs) - len(docs),
                      missing_problem_quotes=sum(not doc["quote"] for doc in docs.values()),
                      problem_documents=len(docs), review_pairs=len(pairs),
                      merged_groups=[g for g in groups if len(g) > 1],
                      singletons=sum(len(g) == 1 for g in groups),
                      lexical_neighbors=sorted(neighbors, reverse=True)[:10])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
