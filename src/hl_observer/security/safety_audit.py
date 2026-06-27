from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from hl_observer.security.secrets import SecretFinding, scan_file_for_secret


@dataclass(slots=True)
class SafetyAuditResult:
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    secret_findings: list[SecretFinding] = field(default_factory=list)


TEXT_SUFFIXES = {".py", ".toml", ".yaml", ".yml", ".env", ".example", ".txt"}
EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "logs", "tmp_pytest"}


def _iter_scannable_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name == ".env.example":
            files.append(path)
    return files


def _is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


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
        for path in (project_root / "src").rglob("*.py")
        if path.name not in {"safety_audit.py", "mainnet_guard.py"}
    ]
    source_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in source_files)
    forbidden_method = "place" + "_mainnet_order"
    checks["no_forbidden_mainnet_order_method"] = forbidden_method not in source_text
    forbidden_exchange_path = "/" + "exchange"
    checks["no_exchange_endpoint_in_runtime_source"] = (
        f'"{forbidden_exchange_path}"' not in source_text
        and f"'{forbidden_exchange_path}'" not in source_text
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
