"""Gate locale de gouvernance HyperSmart.

Certifie les invariants versionnés du dépôt. La politique main-only interdit les
robots qui créent des branches automatiques : la surveillance des dépendances
passe donc par pip-audit/CI, sans Dependabot.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    Path("SECURITY.md"),
    Path(".github/CODEOWNERS"),
    Path(".github/workflows/security-quality.yml"),
    Path("docs/CURRENT_STATE.md"),
    Path("requirements-ci-tools.txt"),
    Path("tools/check_coverage_ratchet.py"),
    Path("tests/test_repository_governance.py"),
)


def local_failures() -> list[str]:
    failures: list[str] = []
    for rel in REQUIRED:
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"fichier requis absent/vide: {rel.as_posix()}")

    if (ROOT / ".github" / "dependabot.yml").exists():
        failures.append("Dependabot interdit: il crée des branches et viole le contrat main-only")

    gateway = ROOT / "docs" / "ETAT_ET_FEUILLE_DE_ROUTE.md"
    if not gateway.is_file():
        failures.append("passerelle docs/ETAT_ET_FEUILLE_DE_ROUTE.md absente")
    else:
        text = gateway.read_text(encoding="utf-8", errors="replace")
        if "CURRENT_STATE.md" not in text or "Source de vérité actuelle" not in text:
            failures.append("ancien document maitre ne redirige pas explicitement vers CURRENT_STATE.md")

    current = ROOT / "docs" / "CURRENT_STATE.md"
    if current.is_file():
        text = current.read_text(encoding="utf-8", errors="replace")
        for marker in (
            "775/775",
            "MORE_DATA",
            "Cross-Venue v2",
            "security-quality",
            "hypersmart/security-quality",
            "hypersmart/technical-perfect",
            "indépendante du verdict économique",
            "main-only",
            "sans Dependabot",
        ):
            if marker not in text:
                failures.append(f"CURRENT_STATE incomplet: marqueur absent {marker}")

    workflow = ROOT / ".github" / "workflows" / "security-quality.yml"
    if workflow.is_file():
        text = workflow.read_text(encoding="utf-8", errors="replace")
        for marker in (
            "statuses: write",
            "hypersmart/security-quality",
            "needs: [governance, supply-chain]",
            "python -m pip_audit",
            "python -m ruff check --select E9,F63,F7,F82 src tools tests",
        ):
            if marker not in text:
                failures.append(f"security-quality incomplet: marqueur absent {marker}")
        for forbidden in (
            "coverage-ratchet",
            "python -m coverage run --source=src",
            "python tools/check_coverage_ratchet.py",
            "hypersmart/technical-perfect",
        ):
            if forbidden in text:
                failures.append(f"security-quality mélange des responsabilités: marqueur interdit {forbidden}")

    perfect = ROOT / ".github" / "workflows" / "pre-run-321-775.yml"
    if perfect.is_file():
        text = perfect.read_text(encoding="utf-8", errors="replace")
        for marker in (
            "hypersmart/pre-run-775",
            "hypersmart/technical-perfect",
            "python -m pip_audit",
            "python -m coverage run --source=src",
            "python tools/check_coverage_ratchet.py",
        ):
            if marker not in text:
                failures.append(f"pre-run perfect incomplet: marqueur absent {marker}")

    return failures


def main() -> int:
    failures = local_failures()
    if failures:
        print("REPOSITORY_GOVERNANCE_RED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("REPOSITORY_GOVERNANCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
