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
OPERATIONAL_RELATIVE_ROOTS = frozenset({
    "src",
    "hyper_smart_observer",
    "tools",
    "scripts",
})
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
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
            and _is_exchange_path(node.value)
        ):
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


def _iter_scannable_files(root: Path) -> list[Path]:
    """Parcours ELAGUE : on ne DESCEND jamais dans un dossier exclu.

    BUG CORRIGE : l'ancienne version faisait `root.rglob("*")`, donc elle traversait TOUT le projet
    (runtime/ ~54 Go, logs/ ~5,6 Go, .git) et faisait deux `.resolve()` par fichier, AVANT de filtrer.
    Resultat : ~20 s juste pour lister 1826 fichiers -> `safety-audit` et `autoscan` figeaient.
    Le jeu de fichiers retourne est IDENTIQUE ; seul le parcours est elague.
    """
    return _enumerate_safety_files(root)[0]


def _is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _iter_operational_files(root: Path) -> list[Path]:
    """Enumerate executable/source surfaces without descending into payloads.

    Root launchers and workflow commands are executable entrypoints too: omitting
    them leaves a route from the operator/CI surface outside the static safety
    scan even when the imported Python modules are covered.
    """
    return _enumerate_safety_files(root)[1]


def _enumerate_safety_files(root: str | Path) -> tuple[list[Path], list[Path]]:
    """Enumerate scannable and operational files in one pruned tree walk.

    The former implementation traversed overlapping source roots twice. Keep
    both public internal views identical while sharing discovery in the full
    audit, and use lexical relative paths because ``os.walk`` never follows
    directory symlinks by default.
    """
    root = Path(root).resolve()
    scannable: list[Path] = []
    operational: list[Path] = []

    def excluded_child(relative_dir: tuple[str, ...], name: str) -> bool:
        relative_child = relative_dir + (name,)
        return (
            name in EXCLUDED_DIRS
            or name.startswith(EXCLUDED_DIR_PREFIXES)
            or any(
                relative_child[: len(prefix)] == prefix
                for prefix in EXCLUDED_RELATIVE_PREFIXES
            )
        )

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        try:
            relative_dir = current.relative_to(root).parts
        except ValueError:
            continue
        dirnames[:] = [
            name for name in dirnames
            if not excluded_child(relative_dir, name)
        ]
        for name in filenames:
            path = current / name
            suffix = path.suffix.lower()
            if suffix in TEXT_SUFFIXES or name == ".env.example":
                scannable.append(path)
            if suffix not in OPERATIONAL_SUFFIXES:
                continue
            in_runtime_root = (
                not relative_dir
                or relative_dir[0] in OPERATIONAL_RELATIVE_ROOTS
                or relative_dir[:2] == (".github", "workflows")
            )
            if in_runtime_root:
                operational.append(path)

    operational.sort(key=lambda path: path.as_posix().casefold())
    return scannable, operational


def _workflow_runner_violations(root: Path) -> list[Path]:
    """Return workflows whose runners are self-hosted or cannot be proven hosted.

    GitHub expressions make a text-only ``runs-on`` check incomplete: a matrix
    can inject ``self-hosted`` or an operator input can choose an arbitrary
    runner. Parse the workflow data and allow only literal runner labels or a
    simple matrix axis whose complete values are statically visible.
    """
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return []
    try:
        import yaml
    except ImportError:
        # The safety result must fail closed if the declared YAML parser is
        # missing; silently falling back to a weaker text scan is unsafe.
        return sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml")))

    findings: list[Path] = []
    for path in sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            document = yaml.safe_load(text) or {}
        except (OSError, yaml.YAMLError):
            findings.append(path)
            continue
        jobs = document.get("jobs") if isinstance(document, dict) else None
        if not isinstance(jobs, dict):
            # A non-workflow YAML file in the workflows directory cannot be
            # certified as safely selecting a hosted runner.
            findings.append(path)
            continue

        for job in jobs.values():
            if not isinstance(job, dict):
                findings.append(path)
                break
            runner = job.get("runs-on")
            if runner is None:
                reusable = job.get("uses")
                if isinstance(reusable, str) and reusable.startswith(
                    "./.github/workflows/"
                ):
                    reusable_path = (root / reusable[2:]).resolve()
                    try:
                        reusable_path.relative_to(workflows.resolve())
                    except ValueError:
                        findings.append(path)
                        break
                    if (
                        reusable_path.parent == workflows.resolve()
                        and reusable_path.suffix.lower() in {".yml", ".yaml"}
                        and reusable_path.is_file()
                    ):
                        # The referenced local workflow is itself included in
                        # this directory scan and its jobs are checked below.
                        continue
                findings.append(path)
                break
            strategy = job.get("strategy")
            matrix = strategy.get("matrix") if isinstance(strategy, dict) else None
            if _runner_selection_unproven(runner, matrix):
                findings.append(path)
                break
    return findings


_MATRIX_RUNNER_EXPRESSION = re.compile(
    r"^\s*\$\{\{\s*matrix\.([A-Za-z_][A-Za-z0-9_-]*)\s*\}\}\s*$"
)


def _runner_selection_unproven(runner: object, matrix: object) -> bool:
    """Fail closed on self-hosted labels or runner expressions not statically bounded."""
    if isinstance(runner, list):
        return not runner or any(_runner_selection_unproven(value, matrix) for value in runner)
    if not isinstance(runner, str) or not runner.strip():
        # The mapping form (runner groups/labels) is intentionally not accepted
        # until its group can be proven to contain only GitHub-hosted runners.
        return True
    if re.search(r"\bself-hosted\b", runner, re.IGNORECASE):
        return True
    if "${{" not in runner:
        return False

    match = _MATRIX_RUNNER_EXPRESSION.fullmatch(runner)
    if match is None or not isinstance(matrix, dict):
        return True
    axis = match.group(1)
    raw_values = matrix.get(axis)
    if not isinstance(raw_values, list) or not raw_values:
        return True
    values = list(raw_values)
    include = matrix.get("include", [])
    if not isinstance(include, list):
        return True
    for item in include:
        if not isinstance(item, dict):
            return True
        if axis in item:
            values.append(item[axis])
    # Any dynamic/non-string matrix member is unprovable. Exclusion lists only
    # remove combinations, so considering the full declared axis is conservative.
    return any(
        not isinstance(value, str)
        or not value.strip()
        or "${{" in value
        or re.search(r"\bself-hosted\b", value, re.IGNORECASE) is not None
        for value in values
    )


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

    scannable_files, source_files = _enumerate_safety_files(project_root)
    source_file_set = set(source_files)
    source_files_seen: set[Path] = set()
    source_read_errors: list[Path] = []
    secret_findings: list[SecretFinding] = []
    no_forbidden_method = True
    no_exchange_endpoint = True
    forbidden_method = "place" + "_mainnet_order"

    # Read operational files once: use the same bytes for secret detection and
    # forbidden execution-path checks, without retaining a concatenated copy of
    # thousands of files in memory.
    for path in scannable_files:
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
    unsafe_runner_workflows = _workflow_runner_violations(project_root)
    checks["no_self_hosted_workflows"] = not unsafe_runner_workflows
    if unsafe_runner_workflows:
        findings.append(
            "workflow runner is self-hosted or cannot be proven GitHub-hosted: "
            + ", ".join(
                str(path.relative_to(project_root)) for path in unsafe_runner_workflows
            )
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
