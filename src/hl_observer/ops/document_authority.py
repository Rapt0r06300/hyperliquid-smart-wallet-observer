from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


REQUIRED_ACTIVE_DOCUMENTS = (
    "SECURITY.md",
    "docs/HYPERSMART_CONSTITUTION.md",
    "AGENTS.md",
    "docs/CODEX_GOAL_RUNBOOK.md",
    "docs/LOIS_MESUREES.md",
    "docs/CURRENT_STATE.md",
)

INSTRUCTION_DOCUMENTS = (
    "AGENTS.md",
    "docs/CODEX_GOAL_RUNBOOK.md",
)

REQUIRED_CONSTITUTION_MARKERS = (
    "SECURITY.md",
    "docs/HYPERSMART_CONSTITUTION.md",
    "schema/active_scope.json",
    "AGENTS.md",
    "docs/CODEX_GOAL_RUNBOOK.md",
    "docs/LOIS_MESUREES.md",
    "docs/CURRENT_STATE.md",
    "HL_ENABLE_MAINNET_EXECUTION=0",
    "HL_ENABLE_TESTNET_EXECUTION=0",
    "Carry est historique et non actif",
    "CLAUDE.md",
    "roadmap technique cumulative V5/776+",
)

_UNSAFE_DIRECTIVE = re.compile(
    r"\b(?:HL_ENABLE_MAINNET_EXECUTION|HL_ENABLE_TESTNET_EXECUTION)\s*=\s*(?:1|true)\b"
    r"|\bREAL_MAINNET_TRADING\s*=\s*true\b"
    r"|\bCONFIRM_TESTNET_EXECUTION\s*=\s*true\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DocumentAuthorityIssue:
    path: str
    code: str
    detail: str
    line: int | None = None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def audit_document_authority(repo_root: str | Path) -> list[DocumentAuthorityIssue]:
    root = Path(repo_root)
    issues: list[DocumentAuthorityIssue] = []

    for relative_path in REQUIRED_ACTIVE_DOCUMENTS:
        if not (root / relative_path).is_file():
            issues.append(
                DocumentAuthorityIssue(
                    path=relative_path,
                    code="MISSING_ACTIVE_DOCUMENT",
                    detail="required active authority document is missing",
                )
            )

    constitution_path = root / "docs/HYPERSMART_CONSTITUTION.md"
    if constitution_path.is_file():
        constitution = _read_text(constitution_path)
        for marker in REQUIRED_CONSTITUTION_MARKERS:
            if marker not in constitution:
                issues.append(
                    DocumentAuthorityIssue(
                        path="docs/HYPERSMART_CONSTITUTION.md",
                        code="MISSING_CONSTITUTION_MARKER",
                        detail=f"missing required marker: {marker}",
                    )
                )

    agents_path = root / "AGENTS.md"
    if agents_path.is_file():
        agents = _read_text(agents_path)
        if "docs/HYPERSMART_CONSTITUTION.md" not in agents:
            issues.append(
                DocumentAuthorityIssue(
                    path="AGENTS.md",
                    code="CONSTITUTION_NOT_REFERENCED",
                    detail="active agent rules must reference the constitution",
                )
            )

    for relative_path in INSTRUCTION_DOCUMENTS:
        path = root / relative_path
        if not path.is_file():
            continue
        for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
            match = _UNSAFE_DIRECTIVE.search(line)
            if match is None:
                continue
            issues.append(
                DocumentAuthorityIssue(
                    path=relative_path,
                    code="UNSAFE_ACTIVE_DIRECTIVE",
                    detail=f"unsafe execution directive: {match.group(0)}",
                    line=line_number,
                )
            )

    return issues


def render_document_authority_report(issues: list[DocumentAuthorityIssue]) -> str:
    if not issues:
        return "DOCUMENT_AUTHORITY=PASS"
    lines = ["DOCUMENT_AUTHORITY=FAIL"]
    for issue in issues:
        location = issue.path if issue.line is None else f"{issue.path}:{issue.line}"
        lines.append(f"- {issue.code} {location}: {issue.detail}")
    return "\n".join(lines)
