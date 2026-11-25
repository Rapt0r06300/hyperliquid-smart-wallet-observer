from __future__ import annotations

import ast
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from hl_observer.security.dependances import auditer_l_environnement
from hl_observer.security.secrets import SecretFinding, scan_file_for_secret, scan_text_for_secret


@dataclass(slots=True)
class SafetyAuditResult:
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    secret_findings: list[SecretFinding] = field(default_factory=list)


TEXT_SUFFIXES = {
    ".py", ".toml", ".yaml", ".yml", ".env", ".example", ".txt",
    ".cmd", ".bat", ".ps1", ".sh", ".js", ".mjs", ".cjs", ".ts",
    ".html", ".htm", ".jsx", ".tsx", ".vue", ".psm1",
}
OPERATIONAL_SUFFIXES = {
    ".py", ".cmd", ".bat", ".ps1", ".sh", ".js", ".mjs", ".cjs", ".ts",
    ".yaml", ".yml",
    ".html", ".htm", ".jsx", ".tsx", ".vue", ".psm1",
}
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".venv-portable",
    ".ci-venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "data",
    # SAFE datasets are immutable evidence, not executable/source material;
    # their integrity is checked by manifests and hashes, not by this text
    # secret scanner. Pruning them keeps CLI audits bounded on full clones.
    "datasets",
    "logs",
    "node_modules",
    "portable_runtime",
    "runtime",
    "tmp_pytest",
    "venv",
    "_validation_workspace",
}
EXCLUDED_DIR_PREFIXES = (".portable-",)
EXCLUDED_RELATIVE_PREFIXES = {
    ("runtime", "research", "github_repos_v24"),
    # Runtime CPython tiers : son integrite est verifiee par le wheelhouse lock et
    # le manifeste portable. Ses sources de dependances ne sont pas notre code.
    ("tools", "python"),
}
# These files intentionally mention prohibited endpoints/methods while testing
# or enforcing their refusal. Keep exceptions path-scoped: a same-named
# operational file elsewhere must still be checked. Every file remains in the
# bounded read and secret scan.
POLICY_SCAN_EXEMPTIONS: dict[str, frozenset[str]] = {
    "src/hl_observer/security/safety_audit.py": frozenset({"exchange_endpoint"}),
    "src/hl_observer/agent_tools/manifest.py": frozenset({"exchange_endpoint"}),
    "src/hl_observer/perf/hot_path_guard.py": frozenset({"exchange_endpoint"}),
    "src/hl_observer/ui/simulation_log_export.py": frozenset({"exchange_endpoint"}),
    "src/hl_observer/ops/validation_portable.py": frozenset({"exchange_endpoint"}),
    "hyper_smart_observer/audit/source_scanner.py": frozenset({"exchange_endpoint"}),
    "hyper_smart_observer/hyperliquid_client/info_client.py": frozenset({"exchange_endpoint"}),
    "hyper_smart_observer/app/safety.py": frozenset({"exchange_endpoint"}),
    "hyper_smart_observer/simulation/diagnostic_log.py": frozenset({"exchange_endpoint"}),
    "tools/audit_report.py": frozenset({"exchange_endpoint", "mainnet_order_method"}),
    "tools/securite_18h.py": frozenset({"exchange_endpoint"}),
    "tools/valider_chaine_bout_en_bout.py": frozenset({"exchange_endpoint"}),
}


def _policy_scan_exemptions(project_root: Path, path: Path) -> frozenset[str]:
    """Return narrowly scoped checks skipped for a known refusal/audit file."""
    try:
        relative = path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return frozenset()
    return POLICY_SCAN_EXEMPTIONS.get(relative, frozenset())


_SIMPLE_STRING_LITERAL = r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
_STRING_CONCATENATION = re.compile(
    rf"(?:{_SIMPLE_STRING_LITERAL}\s*\+\s*)+{_SIMPLE_STRING_LITERAL}"
)
_QUOTED_VALUE = re.compile(r"\"([^\"\\]*)\"|'([^'\\]*)'")
_EXCHANGE_ENDPOINT = re.compile(
    r"^(?:https?://[^/\s?#]+)?(?:/[^/\s?#]+)*/exchange(?=$|[/?#\s])",
    re.IGNORECASE,
)
_UNQUOTED_EXCHANGE_ENDPOINT = re.compile(
    r"(?<![A-Za-z0-9_/])/(?:[^/?#\s\"'`]+/)*exchange(?=$|[^A-Za-z0-9_])",
    re.IGNORECASE,
)


def _is_exchange_path(value: str) -> bool:
    """Match a path or URL, not prose mentioning it or another venue's endpoint."""
    return _EXCHANGE_ENDPOINT.match(value.strip()) is not None


def _contains_python_exchange_endpoint(text: str) -> bool:
    """Inspect executable Python string values, excluding comments/docstrings."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # Invalid operational Python is unsafe to certify; fail closed.
        return True

    docstring_ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstring_ids.add(id(body[0].value))

    def constant_string(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = constant_string(node.left)
            right = constant_string(node.right)
            if left is not None and right is not None:
                return left + right
        if isinstance(node, ast.JoinedStr):
            # Conservative: a dynamic field between constant fragments may
            # still construct the forbidden route at runtime.
            return "".join(
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstring_ids and _is_exchange_path(node.value):
                return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            combined = constant_string(node)
            if combined is not None and _is_exchange_path(combined):
                return True
        if isinstance(node, ast.JoinedStr):
            combined = constant_string(node)
            if combined is not None and _is_exchange_path(combined):
                return True
    return False


def _contains_exchange_endpoint(text: str, suffix: str = ".py") -> bool:
    """Catch executable endpoint paths, ignoring comments and path substrings."""
    if suffix.lower() == ".py":
        return _contains_python_exchange_endpoint(text)
    if suffix.lower() in {".cmd", ".bat"}:
        text = re.sub(r"(?im)^\s*(?:rem\b|::).*?$", "", text)
    if _UNQUOTED_EXCHANGE_ENDPOINT.search(text):
        return True
    for quoted in _QUOTED_VALUE.finditer(text):
        value = quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
        if _is_exchange_path(value):
            return True
    for match in _STRING_CONCATENATION.finditer(text):
        parts = [
            quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
            for quoted in _QUOTED_VALUE.finditer(match.group(0))
        ]
        if _is_exchange_path("".join(parts)):
            return True
    return False


def _is_excluded_project_path(root: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    rel_parts = tuple(rel.parts)
    return any(rel_parts[: len(prefix)] == prefix for prefix in EXCLUDED_RELATIVE_PREFIXES)


def _iter_scannable_files(root: Path) -> list[Path]:
    """Parcours ELAGUE : on ne DESCEND jamais dans un dossier exclu.

    BUG CORRIGE : l'ancienne version faisait `root.rglob("*")`, donc elle traversait TOUT le projet
    (runtime/ ~54 Go, logs/ ~5,6 Go, .git) et faisait deux `.resolve()` par fichier, AVANT de filtrer.
    Resultat : ~20 s juste pour lister 1826 fichiers -> `safety-audit` et `autoscan` figeaient.
    Le jeu de fichiers retourne est IDENTIQUE ; seul le parcours est elague.
    """
    root = Path(root)
    root_resolved = root.resolve()
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(dirpath)
        # ELAGAGE : on retire les sous-dossiers exclus AVANT d'y descendre.
        dirnames[:] = [
            d
            for d in dirnames
            if d not in EXCLUDED_DIRS
            and not d.startswith(EXCLUDED_DIR_PREFIXES)
            and not _is_excluded_project_path(root_resolved, current / d)
        ]
        for name in filenames:
            path = current / name
            if path.suffix.lower() in TEXT_SUFFIXES or path.name == ".env.example":
                files.append(path)
    return files


def _is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _iter_operational_files(root: Path) -> list[Path]:
    """Enumerate executable/source surfaces without descending into payloads.

    Root launchers and workflow commands are executable entrypoints too: omitting
    them leaves a route from the operator/CI surface outside the static safety
    scan even when the imported Python modules are covered.
    """
    root = Path(root).resolve()
    files: list[Path] = []
    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() in OPERATIONAL_SUFFIXES:
            files.append(path)

    for relative_root in (
        "src",
        "hyper_smart_observer",
        "tools",
        "scripts",
        ".github/workflows",
    ):
        base = root / relative_root
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base, topdown=True):
            current = Path(dirpath)
            dirnames[:] = [
                name
                for name in dirnames
                if name not in EXCLUDED_DIRS
                and not name.startswith(EXCLUDED_DIR_PREFIXES)
                and not _is_excluded_project_path(root, current / name)
            ]
            for name in sorted(filenames):
                path = current / name
                if path.suffix.lower() in OPERATIONAL_SUFFIXES:
                    files.append(path)
    return sorted(files, key=lambda path: path.as_posix().casefold())


def _active_self_hosted_workflows(root: Path) -> list[Path]:
    """Return workflows that can actually select a self-hosted runner."""
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return []
    findings: list[Path] = []
    for path in sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            findings.append(path)
            continue
        if re.search(r"(?mi)^\s*runs-on\s*:\s*.*\bself-hosted\b", text):
            findings.append(path)
    return findings


def _git_tracks_env(root: Path) -> bool:
    if not _is_git_repo(root):
        return False
    result = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def run_safety_audit(root: str | Path = ".") -> SafetyAuditResult:
    project_root = Path(root).resolve()
    checks: dict[str, bool] = {}
    findings: list[str] = []

    source_files = list(_iter_operational_files(project_root))
    source_file_set = set(source_files)
    source_files_seen: set[Path] = set()
    source_read_errors: list[Path] = []
    secret_findings: list[SecretFinding] = []
    no_forbidden_method = True
    no_exchange_endpoint = True
    forbidden_method = "place" + "_mainnet_order"
    forbidden_exchange_path = "/" + "exchange"

    # Read operational files once: use the same bytes for secret detection and
    # forbidden execution-path checks, without retaining a concatenated copy of
    # thousands of files in memory.
    for path in _iter_scannable_files(project_root):
        if path.name == ".env.example":
            continue
        if path in source_file_set:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                source_read_errors.append(path)
                continue
            source_files_seen.add(path)
            finding = scan_text_for_secret(path, text)
            exemptions = _policy_scan_exemptions(project_root, path)
            if "mainnet_order_method" not in exemptions:
                no_forbidden_method = no_forbidden_method and forbidden_method not in text
            if "exchange_endpoint" not in exemptions:
                no_exchange_endpoint = (
                    no_exchange_endpoint
                    and not _contains_exchange_endpoint(text, path.suffix)
                )
        else:
            finding = scan_file_for_secret(path)
        if finding:
            secret_findings.append(finding)

    missing_source_files = source_file_set - source_files_seen
    source_scan_complete = not source_read_errors and not missing_source_files
    if source_read_errors:
        findings.extend(
            f"could not read operational source: {path.relative_to(project_root)}"
            for path in source_read_errors
        )
    if missing_source_files:
        findings.append(
            "operational files missing from the bounded scan: "
            + ", ".join(
                str(path.relative_to(project_root))
                for path in sorted(missing_source_files, key=lambda item: item.as_posix().casefold())
            )
        )
    checks["no_secret_patterns"] = not secret_findings and source_scan_complete

    env_committed = _git_tracks_env(project_root)
    checks["env_not_committed"] = not env_committed
    if env_committed:
        findings.append(".env is tracked by git")

    checks["no_forbidden_mainnet_order_method"] = source_scan_complete and no_forbidden_method
    checks["no_exchange_endpoint_in_runtime_source"] = source_scan_complete and no_exchange_endpoint
    self_hosted = _active_self_hosted_workflows(project_root)
    checks["no_self_hosted_workflows"] = not self_hosted
    if self_hosted:
        findings.append(
            "active workflow selects self-hosted runner: "
            + ", ".join(str(path.relative_to(project_root)) for path in self_hosted)
        )

    checks["live_executor_disabled_exists"] = (
        project_root / "src" / "hl_observer" / "execution" / "live_executor_disabled.py"
    ).exists()
    env_example = project_root / ".env.example"
    env_text = env_example.read_text(encoding="utf-8", errors="ignore") if env_example.exists() else ""
    checks["mainnet_disabled_in_env_example"] = "HL_ENABLE_MAINNET_EXECUTION=false" in env_text

    tests_dir = project_root / "tests"
    test_names = {path.name for path in tests_dir.glob("test_*.py")} if tests_dir.exists() else set()
    required_tests = {
        "test_no_mainnet_execution.py",
        "test_safety_audit.py",
        "test_testnet_locked.py",
    }
    checks["security_tests_present"] = required_tests.issubset(test_names)

    # IMPROVE-24 (#131) -- LA CAPACITE, pas seulement le code.
    #
    # Les six controles ci-dessus verifient que notre CODE ne trade pas. Celui-ci verifie que la
    # MACHINE n'en a pas les MOYENS : aucun client d'execution, aucune bibliotheque de signature,
    # aucun portefeuille installe. Sans eux, un ordre reel est physiquement impossible -- meme si
    # quelqu'un ecrivait le code pour, meme par accident.
    #
    # Et parce que ce controle tourne dans la CI, un futur `pip install ccxt` ferait rougir la
    # suite. C'est un CLIQUET : la capacite ne peut pas revenir en douce.
    dep = auditer_l_environnement()
    checks["no_real_execution_capable_package"] = dep.ok
    if not dep.ok:
        findings.append(dep.alerte)

    for finding in secret_findings:
        findings.append(f"secret-like pattern in {finding.path}")
    for name, ok in checks.items():
        if not ok and name not in {"no_secret_patterns", "env_not_committed"}:
            findings.append(f"failed check: {name}")

    return SafetyAuditResult(
        ok=all(checks.values()),
        checks=checks,
        findings=findings,
        secret_findings=secret_findings,
    )
