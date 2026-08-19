"""Gate locale de gouvernance HyperSmart.

Cette gate certifie ce que le dépôt peut réellement garantir lui-même : fichiers
obligatoires, vérité documentaire, CI de qualité et contrats de sécurité. Les
réglages administrateur GitHub (par exemple la protection native de branche)
sont audités séparément mais ne doivent pas transformer une base de code saine
en faux rouge impossible à corriger depuis le dépôt.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    Path("SECURITY.md"),
    Path(".github/CODEOWNERS"),
    Path(".github/dependabot.yml"),
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
            "hypersmart/technical-perfect",
            "indépendante du verdict économique",
        ):
            if marker not in text:
                failures.append(f"CURRENT_STATE incomplet: marqueur absent {marker}")

    workflow = ROOT / ".github" / "workflows" / "security-quality.yml"
    if workflow.is_file():
        text = workflow.read_text(encoding="utf-8", errors="replace")
        for marker in (
            "statuses: write",
            "hypersmart/technical-perfect",
            "needs: [governance, supply-chain, coverage-ratchet]",
            "python -m pip_audit",
            "python tools/check_coverage_ratchet.py",
        ):
            if marker not in text:
                failures.append(f"security-quality incomplet: marqueur absent {marker}")

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
