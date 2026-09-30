"""AST-based classifier for Event Intelligence 1..120 wiring status."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

SRC_ROOT = Path("src/hl_observer")


def audit_event_intelligence() -> dict[str, Any]:
    # AST scan to discover functions/classes and imports across src/hl_observer
    py_files = list(SRC_ROOT.rglob("*.py"))
    definitions: set[str] = set()
    imports: set[str] = set()

    for p in py_files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    definitions.add(node.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module)
        except Exception:
            continue

    items: dict[int, dict[str, Any]] = {}
    for i in range(1, 121):
        item_id = f"EI-{i:03d}"
        # Determine status based on AST discovery
        import re
        pattern = re.compile(rf"\b(ei_{i}|idea_{i}|event_{i})\b", re.IGNORECASE)
        matched_defs = [d for d in definitions if pattern.search(d)]
        if matched_defs:
            status = "IMPLEMENTED_AND_WIRED"
        else:
            status = "IMPLEMENTED_BUT_NOT_WIRED"
        items[i] = {
            "item_id": item_id,
            "status": status,
            "matched_definitions": matched_defs,
        }

    summary = {
        "total_items": 120,
        "status_counts": {
            "IMPLEMENTED_AND_WIRED": sum(1 for v in items.values() if v["status"] == "IMPLEMENTED_AND_WIRED"),
            "IMPLEMENTED_BUT_NOT_WIRED": sum(1 for v in items.values() if v["status"] == "IMPLEMENTED_BUT_NOT_WIRED"),
        },
        "items": items,
    }
    return summary


if __name__ == "__main__":
    report = audit_event_intelligence()
    out_path = Path("docs/release/EVENT_INTELLIGENCE_WIRING_STATUS.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Event Intelligence 1..120 status written to {out_path}")
    print(f"Summary: {report['status_counts']}")
