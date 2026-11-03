"""Deterministic fail-closed progress reader for the canonical 722-task Codex roadmap.

The Markdown checkboxes and their adjacent Codex metadata are the sole tracking
source. This script never changes files, executes strategies or accesses a network.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROADMAP = ROOT / "docs/superpowers/plans/2026-11-02-alina-audit-roadmap-190.md"
EXPECTED = {"ASF": 150, "AUD": 72, "ECO": 200, "LCH": 300}
TASK = re.compile(r"^- \[([ xX])\] \*\*\[((?:ASF|AUD|ECO|LCH)-\d{3})\] ([^*]+)\*\*")
META = re.compile(r"^  - \*\*Suivi Codex :\*\* `([A-Z_]+)`")
PRIORITY = re.compile(r"\*\*Priorité :\*\* `(P[0-3])`")
RECEIPT = re.compile(r"\*\*Reçu de clôture :\*\* (.*?)(?=\s+\*\*|$)")
SHA = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
STATES = frozenset({
    "TODO", "IN_PROGRESS", "PARTIAL", "BLOCKED", "VERIFIED_DONE",
    "DUPLICATE", "SUPERSEDED", "HISTORICAL", "OUT_OF_SCOPE",
})
CLASSIFIED = {"VERIFIED_DONE", "BLOCKED", "DUPLICATE", "SUPERSEDED", "HISTORICAL", "OUT_OF_SCOPE"}


def inspect_roadmap(content: str, *, expected: dict[str, int] | None = None) -> dict:
    """Return evidence-gated progress and audit errors; never infer completion."""
    expected = dict(EXPECTED if expected is None else expected)
    items: dict[str, dict] = {}
    issues: list[str] = []
    current: str | None = None
    for line in content.splitlines():
        match = TASK.match(line)
        if match:
            checked, identifier, title = match.groups()
            if identifier in items:
                issues.append(f"DUPLICATE_ID:{identifier}")
            else:
                items[identifier] = {
                    "title": title.strip(), "checked": checked.lower() == "x",
                    "state": None, "priority": None, "receipt": None,
                    "reason": None,
                }
            current = identifier
            continue
        meta = META.match(line)
        if meta and current:
            item = items[current]
            if item["state"] is not None:
                issues.append(f"DUPLICATE_METADATA:{current}")
            item["state"] = meta.group(1)
            pr = PRIORITY.search(line)
            item["priority"] = pr.group(1) if pr else None
            rc = RECEIPT.search(line)
            item["receipt"] = rc.group(1).strip() if rc else None
            if "**Motif Codex :**" in line:
                item["reason"] = line.split("**Motif Codex :**", 1)[1].strip()
            current = None
    for prefix, n in expected.items():
        actual = sorted(i for i in items if i.startswith(prefix + "-"))
        wanted = [f"{prefix}-{k:03d}" for k in range(1, n + 1)]
        if actual != wanted:
            issues.append(f"MISSING_OR_BAD_IDS:{prefix}:{len(actual)}/{n}")
    for ident, item in items.items():
        status = item["state"]
        if status not in STATES:
            issues.append(f"UNKNOWN_OR_MISSING_STATUS:{ident}:{status}")
        if item["priority"] is None:
            issues.append(f"MISSING_PRIORITY:{ident}")
        if status == "VERIFIED_DONE":
            receipt = item["receipt"] or ""
            if not item["checked"]:
                issues.append(f"VERIFIED_NOT_CHECKED:{ident}")
            if "PENDING" in receipt.upper() or not SHA.search(receipt) or "test" not in receipt.lower():
                issues.append(f"INVALID_VERIFIED_RECEIPT:{ident}")
        elif item["checked"]:
            issues.append(f"CHECKED_WITHOUT_VERIFIED_DONE:{ident}")
        if status in CLASSIFIED - {"VERIFIED_DONE"}:
            reason = item["reason"] or ""
            if len(reason) < 16 or "PENDING" in reason.upper():
                issues.append(f"NO_CLASSIFICATION_REASON:{ident}")
    total = sum(expected.values())
    verified = sum(v["state"] == "VERIFIED_DONE" and v["checked"] for v in items.values())
    handled = sum(v["state"] in CLASSIFIED for v in items.values())
    by_group = {}
    for group, expected_count in expected.items():
        group_items = [v for k, v in items.items() if k.startswith(group + "-")]
        by_group[group] = {
            "verified": sum(v["state"] == "VERIFIED_DONE" and v["checked"] for v in group_items),
            "handled": sum(v["state"] in CLASSIFIED for v in group_items),
            "total": expected_count,
        }
    p0_open = sum(v["priority"] == "P0" and v["state"] != "VERIFIED_DONE" for v in items.values())
    return {
        "total": total, "present": len(items), "verified": verified, "handled": handled,
        "verified_pct": round(100 * verified / max(total, 1), 2),
        "handled_pct": round(100 * handled / max(total, 1), 2),
        "p0_open": p0_open, "status_counts": dict(Counter(v["state"] for v in items.values())),
        "groups": by_group, "errors": issues,
    }


def format_progress(result: dict) -> str:
    pct = result["verified_pct"]
    filled = min(30, round(pct * 30 / 100))
    lines = [
        "ALINA CODEX — FEUILLE DE ROUTE 722 TÂCHES",
        f"VÉRIFIÉ : {result['verified']}/{result['total']} ({pct:.2f} %)",
        f"[{'█' * filled}{'░' * (30 - filled)}] {pct:.2f} %",
        f"TRAITÉ / CLASSÉ : {result['handled']}/{result['total']} ({result['handled_pct']:.2f} %) — distinct du travail vérifié",
        f"P0 NON VÉRIFIÉS : {result['p0_open']}",
    ]
    for key, data in result["groups"].items():
        lines.append(f"{key}: {data['verified']}/{data['total']} VERIFIED_DONE ; {data['handled']}/{data['total']} traitées/classées")
    lines.append(f"ANOMALIES DE SUIVI : {len(result['errors'])}")
    lines.extend("  - " + e for e in result["errors"][:20])
    if len(result["errors"]) > 20:
        lines.append(f"  ... et {len(result['errors']) - 20} autres anomalies")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roadmap", type=Path, default=DEFAULT_ROADMAP)
    parser.add_argument("--json", action="store_true", help="Emit structured metrics")
    args = parser.parse_args()
    try:
        result = inspect_roadmap(args.roadmap.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"ROADMAP_UNAVAILABLE: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_progress(result))
    return 2 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
