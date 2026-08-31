"""Static proposal-only scanner for mutable economic numeric literals.

The scanner never edits source files and never promotes a finding to a defect
without review.  Its purpose is to locate duplicated fee, latency, capacity,
notional and threshold literals outside the canonical economic authority.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "hypersmart.economic_hardcode_scan.v1"
PROPOSAL_DISPOSITION = "PROPOSAL_ONLY_NO_AUTOMATIC_REWRITE"

DEFAULT_ECONOMIC_PATHS = (
    "src/hl_observer/backtesting/copy_vault_executable.py",
    "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
    "src/hl_observer/backtesting/lead_lag_certified_backtest.py",
    "src/hl_observer/simulation/economic_campaigns.py",
    "src/hl_observer/simulation/economic_objective.py",
    "src/hl_observer/simulation/economic_proof_audit.py",
    "tools/backtest_dislocation_2jambes.py",
    "tools/run_economic_objective_campaigns.py",
)

_CANONICAL_AUTHORITY_PATHS = {
    "src/hl_observer/config/frais_venues.py",
    "src/hl_observer/economics/assumptions.py",
    "src/hl_observer/economics/families.py",
}
_ECONOMIC_TOKENS = {
    "adverse",
    "age",
    "book_age",
    "bps",
    "capacity",
    "capacite",
    "cost",
    "cout",
    "delay",
    "edge",
    "fee",
    "fees",
    "fill",
    "fills",
    "frais",
    "fraicheur",
    "freshness",
    "funding",
    "horizon",
    "latence",
    "latency",
    "liquidity",
    "liquidite",
    "net_pnl",
    "notional",
    "pnl",
    "reserve",
    "seuil",
    "slippage",
    "spread",
    "threshold",
}
_SCHEMA_TOKENS = {"schema", "version", "revision", "protocol"}
_UNIT_CONVERSION_VALUES = {
    100.0,
    1_000.0,
    1_024.0,
    10_000.0,
    1_000_000.0,
    1_000_000_000.0,
}
_TIME_CONVERSION_TOKENS = {
    "age",
    "ms",
    "ns",
    "percent",
    "percentage",
    "pct",
    "s",
    "secondes",
    "seconds",
    "timestamp",
}
_TOLERANCE_TOKENS = {"abs", "abs_tol", "epsilon", "rel_tol", "tolerance"}
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class EconomicHardcodeFinding:
    path: str
    line: int
    column: int
    literal: int | float
    category: str
    confidence: str
    context: str
    reason: str = "ECONOMIC_NUMERIC_LITERAL_OUTSIDE_CANONICAL_AUTHORITY"
    disposition: str = PROPOSAL_DISPOSITION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tokens(text: str) -> set[str]:
    result: set[str] = set()
    for token in _IDENTIFIER_RE.findall(text):
        normalized = token.lower()
        result.add(normalized)
        result.update(part for part in normalized.split("_") if part)
    return result


def _category(tokens: set[str]) -> str:
    for category, aliases in (
        ("FEES", {"fee", "fees", "frais"}),
        ("LATENCY_FRESHNESS", {"age", "delay", "fraicheur", "freshness", "latence", "latency"}),
        ("CAPACITY_NOTIONAL", {"capacity", "capacite", "liquidity", "liquidite", "notional"}),
        ("EXECUTION_COST", {"adverse", "cost", "cout", "slippage", "spread"}),
        ("FUNDING", {"funding"}),
        ("PNL_THRESHOLD", {"bps", "edge", "horizon", "net_pnl", "pnl", "reserve", "seuil", "threshold"}),
        ("FILL_COUNT", {"fill", "fills"}),
    ):
        if tokens & aliases:
            return category
    return "ECONOMIC_OTHER"


def _function_names(tree: ast.AST) -> dict[int, str]:
    names: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                names[id(child)] = node.name
    return names


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    result: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            result[id(child)] = parent
    return result


def _literal_value(node: ast.Constant, parent: ast.AST | None) -> int | float | None:
    if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
        return None
    value: int | float = node.value
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.USub):
        value = -value
    return value


def _is_index_or_loop_bound(parent: ast.AST | None, ancestors: Iterable[ast.AST]) -> bool:
    if isinstance(parent, (ast.Slice, ast.Subscript)):
        return True
    for ancestor in ancestors:
        if isinstance(ancestor, ast.Call):
            name = ""
            if isinstance(ancestor.func, ast.Name):
                name = ancestor.func.id
            elif isinstance(ancestor.func, ast.Attribute):
                name = ancestor.func.attr
            return name in {"range", "enumerate", "round"}
        if isinstance(ancestor, (ast.Assign, ast.AnnAssign, ast.Compare, ast.Return)):
            break
    return False


def _is_harmless_conversion(
    value: int | float,
    parent: ast.AST | None,
    line_tokens: set[str],
) -> bool:
    if abs(float(value)) not in _UNIT_CONVERSION_VALUES:
        return False
    if not isinstance(parent, ast.BinOp):
        return False
    if not isinstance(parent.op, (ast.Div, ast.Mult, ast.FloorDiv)):
        return False
    if abs(float(value)) == 1024.0 and isinstance(parent.op, ast.Mult):
        return True
    if abs(float(value)) == 10_000.0:
        return True
    if abs(float(value)) in {1_000_000.0, 1_000_000_000.0}:
        return True
    return "bps" in line_tokens or bool(line_tokens & _TIME_CONVERSION_TOKENS)


def _is_algebraic_identity_or_diagnostic(
    value: int | float,
    parent: ast.AST | None,
    ancestors: Iterable[ast.AST],
    line_tokens: set[str],
) -> bool:
    if line_tokens & _TOLERANCE_TOKENS:
        return True
    if (
        float(value) == 0.5
        and isinstance(parent, ast.BinOp)
        and isinstance(parent.op, ast.Mult)
    ):
        return True
    if float(value) == 0.5 and line_tokens & {"average", "fair", "half", "mid"}:
        return True
    if 0.0 < abs(float(value)) <= 1e-7 and (
        isinstance(parent, ast.Compare)
        or any(isinstance(ancestor, ast.Compare) for ancestor in ancestors)
    ):
        return True
    if float(value) not in {-1.0, 0.0, 1.0}:
        return False
    structural = (
        ast.BinOp,
        ast.BoolOp,
        ast.Call,
        ast.Compare,
        ast.Dict,
        ast.IfExp,
        ast.List,
        ast.Set,
        ast.Subscript,
        ast.Tuple,
    )
    if isinstance(parent, structural):
        return True
    if isinstance(parent, ast.AugAssign):
        return True
    for ancestor in ancestors:
        if isinstance(ancestor, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            return False
        if isinstance(ancestor, structural):
            return True
    return False


def scan_economic_source(
    source: str,
    *,
    path: str = "<memory>",
) -> dict[str, Any]:
    """Scan one Python source and return review proposals plus suppressions."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return {
            "path": path,
            "findings": [],
            "suppressed": [],
            "parse_error": {
                "line": exc.lineno,
                "column": exc.offset,
                "message": exc.msg,
            },
        }

    lines = source.splitlines()
    parent_by_id = _parents(tree)
    function_by_id = _function_names(tree)
    findings: list[EconomicHardcodeFinding] = []
    suppressed: list[dict[str, Any]] = []
    normalized_path = path.replace("\\", "/")
    canonical_authority = normalized_path in _CANONICAL_AUTHORITY_PATHS

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        parent = parent_by_id.get(id(node))
        value = _literal_value(node, parent)
        if value is None:
            continue
        line = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""
        line_tokens = _tokens(line)
        function_name = function_by_id.get(id(node), "")
        contextual_tokens = line_tokens | _tokens(function_name)
        economic_tokens = contextual_tokens & _ECONOMIC_TOKENS
        if not economic_tokens:
            continue

        ancestors: list[ast.AST] = []
        cursor = parent
        while cursor is not None and len(ancestors) < 5:
            ancestors.append(cursor)
            cursor = parent_by_id.get(id(cursor))

        suppression_reason: str | None = None
        if canonical_authority:
            suppression_reason = "CANONICAL_ECONOMIC_AUTHORITY_DECLARATION"
        elif line_tokens & _SCHEMA_TOKENS and not (line_tokens & (_ECONOMIC_TOKENS - _SCHEMA_TOKENS)):
            suppression_reason = "SCHEMA_OR_PROTOCOL_VERSION"
        elif _is_harmless_conversion(value, parent, line_tokens):
            suppression_reason = "UNIT_CONVERSION_LITERAL"
        elif _is_algebraic_identity_or_diagnostic(
            value,
            parent,
            ancestors,
            line_tokens,
        ):
            suppression_reason = "ALGEBRAIC_IDENTITY_OR_DIAGNOSTIC_LITERAL"
        elif _is_index_or_loop_bound(parent, ancestors):
            suppression_reason = "INDEX_LOOP_OR_ROUNDING_LITERAL"

        if suppression_reason is not None:
            suppressed.append(
                {
                    "line": node.lineno,
                    "literal": value,
                    "reason": suppression_reason,
                }
            )
            continue

        local_hit = bool(line_tokens & _ECONOMIC_TOKENS)
        findings.append(
            EconomicHardcodeFinding(
                path=normalized_path,
                line=node.lineno,
                column=node.col_offset,
                literal=value,
                category=_category(economic_tokens),
                confidence="HIGH" if local_hit else "MEDIUM",
                context=line[:240],
            )
        )

    return {
        "path": normalized_path,
        "findings": [finding.as_dict() for finding in findings],
        "suppressed": suppressed,
        "parse_error": None,
    }


def scan_economic_paths(
    root: str | Path,
    paths: Iterable[str | Path] = DEFAULT_ECONOMIC_PATHS,
) -> dict[str, Any]:
    """Scan explicit economic paths and emit a deterministic proposal receipt."""

    root_path = Path(root).resolve()
    selected: list[Path] = []
    for raw in paths:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root_path / candidate
        if candidate.is_dir():
            selected.extend(sorted(candidate.rglob("*.py")))
        elif candidate.suffix == ".py":
            selected.append(candidate)
    unique = sorted({path.resolve() for path in selected})

    findings: list[dict[str, Any]] = []
    suppressions: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    file_hashes: dict[str, str | None] = {}
    for source_path in unique:
        relative = _relative_path(source_path, root_path)
        if not source_path.is_file():
            parse_errors.append({"path": relative, "reason": "SOURCE_FILE_MISSING"})
            file_hashes[relative] = None
            continue
        file_hashes[relative] = _sha256(source_path)
        result = scan_economic_source(
            source_path.read_text(encoding="utf-8"),
            path=relative,
        )
        findings.extend(result["findings"])
        suppressions.extend(
            {"path": relative, **item} for item in result["suppressed"]
        )
        if result["parse_error"] is not None:
            parse_errors.append({"path": relative, **result["parse_error"]})

    findings.sort(key=lambda item: (item["path"], item["line"], item["column"]))
    suppressions.sort(key=lambda item: (item["path"], item["line"]))
    summary = {
        "files_scanned": len(unique),
        "proposal_count": len(findings),
        "suppressed_count": len(suppressions),
        "parse_error_count": len(parse_errors),
        "by_category": dict(sorted(Counter(row["category"] for row in findings).items())),
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "disposition": PROPOSAL_DISPOSITION,
        "auto_rewrite": False,
        "file_hashes": file_hashes,
        "summary": summary,
        "findings": findings,
        "suppressions": suppressions,
        "parse_errors": parse_errors,
    }
    serialized = repr(body).encode()
    return {**body, "receipt_sha256": hashlib.sha256(serialized).hexdigest()}


__all__ = [
    "DEFAULT_ECONOMIC_PATHS",
    "EconomicHardcodeFinding",
    "PROPOSAL_DISPOSITION",
    "SCHEMA_VERSION",
    "scan_economic_paths",
    "scan_economic_source",
]
