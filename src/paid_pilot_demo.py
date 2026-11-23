"""Offline, synthetic portfolio demonstration; not a customer-ready connector."""
import json
from collections import Counter
from decimal import Decimal


def repair_demo():
    # A fictional inventory reconciliation flow. No live accounts or network.
    events = [
        {"event": "E1", "item": "A", "quantity": 4},
        {"event": "E1", "item": "A", "quantity": 4},
        {"event": "E2", "item": "B", "quantity": 2},
        {"event": "E3", "item": "C", "quantity": None},
        {"event": "E2", "item": "B", "quantity": 9},
    ]
    before = [{"item": e["item"], "quantity": e["quantity"]} for e in events]
    accepted, exceptions, seen = [], [], {}
    for e in events:
        key = e["event"]
        if type(e["quantity"]) is not int or e["quantity"] < 0:
            exceptions.append({"event": key, "reason": "invalid_quantity"})
        elif key in seen:
            exceptions.append({"event": key, "reason": "repeat" if seen[key] == e else "conflict"})
        else:
            seen[key] = e
            accepted.append(e)
    assert [e["event"] for e in accepted] == ["E1", "E2"]
    assert [e["reason"] for e in exceptions] == ["repeat", "invalid_quantity", "conflict"]
    return {"before": before, "after": accepted, "exceptions": exceptions,
            "input_count": len(events), "accounted_count": len(accepted) + len(exceptions)}


def spreadsheet_demo():
    # Source rows are retained; exact duplicates are reported, conflicts are not guessed.
    files = {
        "week-a": [("A-01", "12.50"), ("A-02", "8.00"), ("A-03", "3.25")],
        "week-b": [("A-01", "12.50"), ("A-02", "9.00"), ("A-04", "4.75")],
    }
    grouped = {}
    for source, rows in files.items():
        for row, (key, amount) in enumerate(rows, 2):
            grouped.setdefault(key, []).append({"source": source, "row": row, "amount": str(Decimal(amount))})
    clean, log, unresolved = [], [], []
    for key, rows in sorted(grouped.items()):
        if len({Decimal(r["amount"]) for r in rows}) > 1:
            unresolved.append({"id": key, "reason": "conflicting_amounts", "source_rows": rows})
            continue
        clean.append({"id": key, **rows[0]})
        log.extend({"id": key, "reason": "exact_duplicate", **r} for r in rows[1:])
    total = sum((Decimal(r["amount"]) for r in clean), Decimal(0))
    counts = Counter({"accepted": len(clean), "duplicates": len(log),
                      "unresolved_source_rows": sum(len(r["source_rows"]) for r in unresolved)})
    assert sum(counts.values()) == sum(len(v) for v in files.values()) == 6
    assert total == Decimal("20.50") and [r["id"] for r in unresolved] == ["A-02"]
    return {"source_files": files, "accepted": clean, "change_log": log,
            "unresolved": unresolved, "accepted_total_only": str(total), "counts": dict(counts)}


if __name__ == "__main__":
    print(json.dumps({"mode": "synthetic_offline_demo", "automation": repair_demo(),
                      "spreadsheet": spreadsheet_demo()}, ensure_ascii=False, indent=2))
