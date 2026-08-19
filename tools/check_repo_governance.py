"""Gate de gouvernance HyperSmart.

Verifie les fichiers de gouvernance versionnes et, sur GitHub Actions, peut
refuser un depot dont main n'est pas protegee. Aucun secret n'est imprime.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    Path("SECURITY.md"),
    Path(".github/CODEOWNERS"),
    Path(".github/dependabot.yml"),
    Path(".github/workflows/security-quality.yml"),
    Path("docs/CURRENT_STATE.md"),
    Path("tools/check_coverage_ratchet.py"),
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
        for marker in ("775/775", "MORE_DATA", "Cross-Venue v2", "security-quality"):
            if marker not in text:
                failures.append(f"CURRENT_STATE incomplet: marqueur absent {marker}")

    return failures


def main_is_protected(repository: str) -> tuple[bool, str]:
    url = f"https://api.github.com/repos/{repository}/branches/main"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "hypersmart-governance-gate"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.load(response)
    except Exception as exc:  # noqa: BLE001 - un gate de gouvernance doit echouer ferme.
        return False, f"impossible de verifier la protection de main: {type(exc).__name__}: {exc}"
    protected = bool(payload.get("protected"))
    return protected, "main protegee" if protected else "main NON protegee"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-protected-main", action="store_true")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()

    failures = local_failures()
    if args.require_protected_main:
        if not args.repository:
            failures.append("GITHUB_REPOSITORY absent: protection de main non verifiable")
        else:
            protected, message = main_is_protected(args.repository)
            print(message)
            if not protected:
                failures.append(message)

    if failures:
        print("REPOSITORY_GOVERNANCE_RED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("REPOSITORY_GOVERNANCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
