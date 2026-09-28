#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
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


def _load_component_contracts(path: Path) -> dict[int, str]:
    """Read the canonical 1..120 component ownership table without importing the package."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "raw" for target in node.targets):
            continue
        try:
            rows = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            break
        mapping: dict[int, str] = {}
        for row in rows:
            if not isinstance(row, tuple) or len(row) < 4:
                continue
            idea_id, _, component, status, *_ = row
            if isinstance(idea_id, int) and status == "IMPLEMENTED" and isinstance(component, str):
                mapping[idea_id] = component.strip()
        return mapping
    raise SystemExit("unable to parse canonical Event Intelligence component registry")


def _resolve_reference_files(
    root: Path,
    references: str,
    files_by_name: dict[str, list[Path]],
) -> list[str]:
    """Resolve explicit paths/module names conservatively into real repository files."""
    resolved: set[str] = set()
    for raw_token in re.split(r"\s*\+\s*|\s*,\s*", references):
        token = raw_token.strip().strip("\x60")
        if not token:
            continue

        direct = root / token
        if direct.is_file():
            resolved.add(str(direct.relative_to(root)))
            continue

        if token in {"package architecture", "event_intelligence"}:
            package_init = root / "src/hl_observer/event_intelligence/__init__.py"
            if package_init.is_file():
                resolved.add(str(package_init.relative_to(root)))
            continue

        name = token.split(":")[0].strip()
        if name.endswith(".py"):
            for path in files_by_name.get(Path(name).name, ())[:12]:
                resolved.add(str(path.relative_to(root)))
            continue

        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            for path in files_by_name.get(f"{name}.py", ())[:12]:
                resolved.add(str(path.relative_to(root)))

    return sorted(resolved)


def _find_callers(
    *, evidence_files: list[str], import_index: dict[str, set[str]]
) -> list[str]:
    callers: set[str] = set()
    for evidence in evidence_files:
        evidence_path = Path(evidence)
        if evidence_path.suffix != ".py":
            continue
        key = evidence_path.parent.name if evidence_path.stem == "__init__" else evidence_path.stem
        callers.update(path for path in import_index.get(key, ()) if path != evidence)
    return sorted(callers)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="docs/event-intelligence-120-coverage.md")
    parser.add_argument("--output", default="docs/event-intelligence-120-status.json")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--component-registry",
        default="src/hl_observer/event_intelligence/idea_coverage.py",
    )
    args = parser.parse_args()
    root = Path(args.repo_root)

    python_files = sorted(root.rglob("*.py"))
    file_text: dict[Path, str] = {}
    for candidate in python_files:
        try:
            file_text[candidate] = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

    files_by_name: dict[str, list[Path]] = {}
    import_index: dict[str, set[str]] = {}
    for candidate, candidate_text in file_text.items():
        files_by_name.setdefault(candidate.name, []).append(candidate)
        relative = str(candidate.relative_to(root))
        for match in re.finditer(r"(?m)^\\s*(?:from|import)\\s+([^#\\n]+)", candidate_text):
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", match.group(1)):
                for part in token.split("."):
                    import_index.setdefault(part, set()).add(relative)
    test_text = {
        candidate: text
        for candidate, text in file_text.items()
        if candidate.name.startswith("test_")
    }

    component_contracts = _load_component_contracts(root / args.component_registry)

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
        component_contract = component_contracts.get(number, "")

        files = sorted(
            set(_resolve_reference_files(root, refs, files_by_name))
            | set(_resolve_reference_files(root, component_contract, files_by_name))
        )
        callers = _find_callers(evidence_files=files, import_index=import_index)

        policy_only = bool(component_contract) and (
            component_contract.startswith("docs/")
            or component_contract == "package architecture"
        )

        if policy_only and files:
            status = "NOT_APPLICABLE"
        elif not files:
            status = "MISSING"
        elif not callers:
            status = "IMPLEMENTED_BUT_NOT_WIRED"
        elif "À prouver" in proof or "⏳" in proof:
            status = "IMPLEMENTED_BUT_PARTIAL"
        else:
            status = "IMPLEMENTED_AND_WIRED"

        tests: set[str] = set()
        python_evidence_stems = {
            Path(evidence).stem for evidence in files if Path(evidence).suffix == ".py"
        }
        if python_evidence_stems:
            for candidate, candidate_text in test_text.items():
                if any(stem in candidate_text for stem in python_evidence_stems):
                    tests.add(str(candidate.relative_to(root)))

        proof_status = (
            "UNMEASURABLE"
            if "⏳" in proof or "À prouver" in proof
            else "UNPROVEN"
        )
        evidence_digest = hashlib.sha256(
            json.dumps(
                {
                    "files": files,
                    "component_contract": component_contract,
                    "callers": callers,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

        if policy_only and files:
            reason = "Policy/architecture item has repository evidence but no runtime wiring requirement."
        elif callers and status != "MISSING":
            reason = (
                "Structural implementation is present and referenced by runtime imports; "
                "economic proof remains data/OOS/forward dependent."
            )
        elif files:
            reason = "Implementation evidence exists but no runtime caller was resolved."
        else:
            reason = "No declared implementation evidence was resolved."

        rows.append(
            {
                "id": number,
                "idea": idea,
                "declared_references": refs,
                "component_contract": component_contract,
                "implementation_contract": implementation,
                "evidence_files": files,
                "actual_callers": callers,
                "required_dataset_family": "external_events",
                "current_data_availability": "STRUCTURAL_ONLY",
                "target_economic_families": [
                    "copy_vault",
                    "lead_lag",
                    "cross_venue_dislocation",
                ],
                "tests": sorted(tests),
                "runtime_evidence": callers,
                "wiring_status": status,
                "coverage_state": (
                    "NOT_APPLICABLE"
                    if status == "NOT_APPLICABLE"
                    else "UNMEASURABLE"
                    if callers and ("À prouver" in proof or "⏳" in proof)
                    else "WIRED"
                    if callers
                    else "REGISTERED"
                ),
                "status": status,
                "proof_status": proof_status,
                "proof_text": proof,
                "reason": reason,
                "evidence_digest": evidence_digest,
            }
        )

    if len(rows) != 120 or [row["id"] for row in rows] != list(range(1, 121)):
        raise SystemExit("registry must contain ids 1..120")
    if set(component_contracts) != set(range(1, 121)):
        raise SystemExit("component registry must contain ids 1..120")

    body = {
        "schema_version": "alina.event_intelligence_status.v2",
        "source": str(Path(args.source)),
        "component_registry": str(Path(args.component_registry)),
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
    print(
        json.dumps(
            {
                "output": args.output,
                "items": len(rows),
                "summary": body["summary"],
                "registry_digest": body["registry_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
