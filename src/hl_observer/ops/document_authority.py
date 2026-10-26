from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

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

ACTIVE_SCOPE_PATH = "src/hl_observer/strategies/active_scope.py"
EXPECTED_ACTIVE_FAMILIES = ("copy_vault",)
SECURITY_SCOPE_HEADING = "8"
SECURITY_SCOPE_MARKER = "Famille économique active unique : **Copy-Vault**."

REQUIRED_CONSTITUTION_MARKERS = (
    "SECURITY.md",
    "docs/HYPERSMART_CONSTITUTION.md",
    ACTIVE_SCOPE_PATH,
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


def _active_families_from_source(source: str) -> tuple[str, ...] | None:
    """Read the literal canonical scope tuple without importing project code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    scope_value: ast.expr | None = None
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(target, ast.Name) and target.id == "_SCOPE"
            for target in (
                node.targets if isinstance(node, ast.Assign) else (node.target,)
            )
        ):
            scope_value = node.value
            break
    if not isinstance(scope_value, (ast.Tuple, ast.List)):
        return None

    active: list[str] = []
    for entry in scope_value.elts:
        if not isinstance(entry, ast.Call):
            return None
        function = entry.func
        if not isinstance(function, ast.Name) or function.id != "StrategyScopeEntry":
            return None
        if len(entry.args) < 3:
            return None
        family_node, status_node, paper_node = entry.args[:3]
        if not isinstance(family_node, ast.Constant) or not isinstance(
            family_node.value, str
        ):
            return None
        active_status = (
            isinstance(status_node, ast.Attribute)
            and status_node.attr == "ACTIVE"
            and isinstance(status_node.value, ast.Name)
            and status_node.value.id == "StrategyScopeStatus"
        )
        materializes = isinstance(paper_node, ast.Constant) and paper_node.value is True
        if active_status and materializes:
            active.append(family_node.value)
    return tuple(sorted(active))


def _markdown_section(text: str, heading_number: str) -> str | None:
    lines = text.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(rf"^##\s+{re.escape(heading_number)}(?:\.|\s)", line)
        ),
        None,
    )
    if start is None:
        return None
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


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

    scope_path = root / ACTIVE_SCOPE_PATH
    active_families: tuple[str, ...] | None = None
    if not scope_path.is_file():
        issues.append(
            DocumentAuthorityIssue(
                path=ACTIVE_SCOPE_PATH,
                code="MISSING_ACTIVE_SCOPE_AUTHORITY",
                detail="the canonical machine-readable strategy scope is missing",
            )
        )
    else:
        try:
            active_families = _active_families_from_source(
                _read_text(scope_path)
            )
        except (OSError, UnicodeError):
            active_families = None
        if active_families is None:
            issues.append(
                DocumentAuthorityIssue(
                    path=ACTIVE_SCOPE_PATH,
                    code="ACTIVE_SCOPE_UNVERIFIABLE",
                    detail="could not parse the canonical active family tuple",
                )
            )
        elif active_families != EXPECTED_ACTIVE_FAMILIES:
            issues.append(
                DocumentAuthorityIssue(
                    path=ACTIVE_SCOPE_PATH,
                    code="ACTIVE_SCOPE_MISMATCH",
                    detail=(
                        f"expected {EXPECTED_ACTIVE_FAMILIES!r}, "
                        f"found {active_families!r}"
                    ),
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

    security_path = root / "SECURITY.md"
    if security_path.is_file():
        security = _read_text(security_path)
        scope_section = _markdown_section(security, SECURITY_SCOPE_HEADING)
        has_single_family_marker = (
            scope_section is not None and SECURITY_SCOPE_MARKER in scope_section
        )
        declares_family_list = bool(
            scope_section
            and re.search(r"(?im)^\s*Familles actives\s*:", scope_section)
        )
        if (
            active_families == EXPECTED_ACTIVE_FAMILIES
            and (not has_single_family_marker or declares_family_list)
        ):
            issues.append(
                DocumentAuthorityIssue(
                    path="SECURITY.md",
                    code="SECURITY_ACTIVE_SCOPE_CONTRADICTION",
                    detail=(
                        "security policy must identify Copy-Vault as the sole "
                        "active economic family and must not list inactive families as active"
                    ),
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
