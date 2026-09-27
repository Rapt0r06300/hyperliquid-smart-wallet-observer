#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROW = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|"
)
STATUSES = [
    "IMPLEMENTED_AND_WIRED",
    "IMPLEMENTED_BUT_PARTIAL",
    "IMPLEMENTED_BUT_NOT_WIRED",
    "BROKEN",
    "MISSING",
    "NOT_APPLICABLE",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="docs/event-intelligence-120-coverage.md")
    parser.add_argument("--output", default="docs/event-intelligence-120-status.json")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root)
    python_files = sorted(root.rglob("*.py"))
    file_text = {}
    for candidate in python_files:
        try:
            file_text[candidate] = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    rows = []
    for line in Path(args.source).read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if not match:
            continue
        number = int(match.group(1))
        idea = match.group(2).strip()
        refs = match.group(3).strip()
        implementation = match.group(4).strip()
        proof = match.group(5).strip()
        files = []
        for token in re.split(r"\s*[+,/]\s*|\s+\+\s+", refs):
            token = token.strip()
            name = token.split(":")[0].strip()
            if name.endswith(".py"):
                files.extend(
                    str(path.relative_to(root))
                    for path in list(root.rglob(name))[:5]
                )
            elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                files.extend(
                    str(path.relative_to(root))
                    for path in list(root.rglob(f"{name}.py"))[:5]
                )
        files = sorted(set(files))
        callers = []
        for evidence in files:
            stem = Path(evidence).stem
            for candidate, text in file_text.items():
                if str(candidate.relative_to(root)) == evidence:
                    continue
                if re.search(rf"(?m)^\s*(?:from|import)\s+[^#]*\b{re.escape(stem)}\b", text):
                    callers.append(str(candidate.relative_to(root)))
        callers = sorted(set(callers))
        if not files:
            status = "MISSING"
        elif not callers:
            status = "IMPLEMENTED_BUT_NOT_WIRED"
        elif ("À prouver" in proof or "⏳" in proof):
            status = "IMPLEMENTED_BUT_PARTIAL"
        else:
            status = "IMPLEMENTED_AND_WIRED"
        tests = []
        for evidence in files:
            candidate = root / "tests" / Path(evidence).name.replace(".py", "")
            if candidate.exists():
                tests.append(str(candidate.relative_to(root)))
        proof_status = (
            "UNMEASURABLE"
            if "⏳" in proof or "À prouver" in proof
            else "UNPROVEN"
        )
        evidence_digest = hashlib.sha256(
            json.dumps(files, sort_keys=True).encode()
        ).hexdigest()
        rows.append({
            "id": number,
            "idea": idea,
            "declared_references": refs,
            "implementation_contract": implementation,
            "evidence_files": files,
            "actual_callers": callers,
            "required_dataset_family": "external_events",
            "current_data_availability": "STRUCTURAL_ONLY",
            "target_economic_families": [
                "copy_vault", "lead_lag", "cross_venue_dislocation"
            ],
            "tests": sorted(set(tests)),
            "runtime_evidence": callers,
            "wiring_status": status,
            "coverage_state": (
                "UNMEASURABLE" if callers and ("À prouver" in proof or "⏳" in proof) else ("WIRED" if callers else "REGISTERED")
            ),
            "status": status,
            "proof_status": proof_status,
            "proof_text": proof,
            "reason": (
                "Structural implementation is present and referenced by runtime imports; "
                "economic proof remains data/OOS/forward dependent."
                if callers and status != "MISSING"
                else (
                    "Implementation evidence exists but no runtime caller was resolved."
                    if files
                    else "No declared implementation evidence was resolved."
                )
            ),
            "evidence_digest": evidence_digest,
        })
    if len(rows) != 120 or [row["id"] for row in rows] != list(range(1, 121)):
        raise SystemExit("registry must contain ids 1..120")
    body = {
        "schema_version": "alina.event_intelligence_status.v2",
        "source": str(Path(args.source)),
        "items": rows,
        "summary": {
            status: sum(row["status"] == status for row in rows)
            for status in STATUSES
        },
    }
    body["registry_digest"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    Path(args.output).write_text(
        json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": args.output,
        "items": len(rows),
        "registry_digest": body["registry_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
