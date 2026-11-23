from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from hl_observer.security.dependances import auditer_l_environnement
from hl_observer.security.secrets import SecretFinding, scan_file_for_secret


@dataclass(slots=True)
class SafetyAuditResult:
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    secret_findings: list[SecretFinding] = field(default_factory=list)


TEXT_SUFFIXES = {
    ".py", ".toml", ".yaml", ".yml", ".env", ".example", ".txt",
    ".cmd", ".bat", ".ps1", ".sh", ".js", ".mjs", ".cjs", ".ts",
}
OPERATIONAL_SUFFIXES = {
    ".py", ".cmd", ".bat", ".ps1", ".sh", ".js", ".mjs", ".cjs", ".ts",
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
NON_OPERATIONAL_POLICY_FILES = {
    "audit_report.py",
    "cloturer_291.py",
    "etat_112_145.py",
    "mainnet_guard.py",
    "safety_audit.py",
    "securite_18h.py",
    "trier_h46_h89.py",
    "trier_h90_h180.py",
    "valider_chaine_bout_en_bout.py",
    "validation_portable.py",
}


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
            if path.suffix in TEXT_SUFFIXES or path.name == ".env.example":
                files.append(path)
    return files


def _is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _iter_operational_files(root: Path) -> list[Path]:
    """Enumerate executable/source surfaces without descending into payloads."""
    root = Path(root).resolve()
    files: list[Path] = []
    for relative_root in ("src", "hyper_smart_observer", "tools"):
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
            for name in filenames:
                path = current / name
                if path.suffix in OPERATIONAL_SUFFIXES:
                    files.append(path)
    return files


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

    secret_findings = []
    for path in _iter_scannable_files(project_root):
        if path.name == ".env.example":
            continue
        finding = scan_file_for_secret(path)
        if finding:
            secret_findings.append(finding)
    checks["no_secret_patterns"] = not secret_findings

    env_committed = _git_tracks_env(project_root)
    checks["env_not_committed"] = not env_committed
    if env_committed:
        findings.append(".env is tracked by git")

    source_files = [
        path
        for path in _iter_operational_files(project_root)
        if path.name not in NON_OPERATIONAL_POLICY_FILES
    ]
    source_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in source_files)
    forbidden_method = "place" + "_mainnet_order"
    checks["no_forbidden_mainnet_order_method"] = forbidden_method not in source_text
    forbidden_exchange_path = "/" + "exchange"
    checks["no_exchange_endpoint_in_runtime_source"] = (
        f'"{forbidden_exchange_path}"' not in source_text
        and f"'{forbidden_exchange_path}'" not in source_text
    )
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
