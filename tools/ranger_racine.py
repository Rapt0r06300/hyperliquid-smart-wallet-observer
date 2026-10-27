"""Read-only audit of the repository launcher layout.

This command only reports discrepancies. It never moves, rewrites, or deletes files.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT_LAUNCHERS = frozenset({
    "ALINA_SYNC_COMPLETE.cmd",
    "LANCER_COLLECTEURS_COPY_VAULT.cmd",
    "LANCER_HYPERSMART.cmd",
    "LANCER_LAB_QUANT_COPY_VAULT.cmd",
    "POUSSER-GITHUB-FORCE.cmd",
})


def audit(root: Path) -> tuple[bool, str]:
    root = root.resolve()
    actual = {p.name for p in root.glob("*.cmd") if p.is_file()}
    missing = sorted(ROOT_LAUNCHERS - actual)
    extra = sorted(actual - ROOT_LAUNCHERS)
    sync_shell = root / "ALINA_SYNC_COMPLETE.sh"
    support_dir = root / "tools" / "launchers"
    support = sorted(p.name for p in support_dir.glob("*.cmd") if p.is_file())
    lines = [f"Dépôt : {root}", f"Lanceurs .cmd à la racine : {len(actual)}", ""]
    lines.append("Lanceurs racine attendus :")
    lines.extend(f"  {name}" for name in sorted(ROOT_LAUNCHERS))
    lines.append(f"AlinaSync shell : {'présent' if sync_shell.is_file() else 'ABSENT'}")
    lines.append(f"Lanceurs de support rangés : {len(support)} sous tools/launchers/")
    lines.extend(f"  {name}" for name in support)
    issues = []
    if missing:
        issues.append("Manquants à la racine : " + ", ".join(missing))
    if extra:
        issues.append("À déplacer hors de la racine : " + ", ".join(extra))
    if not sync_shell.is_file():
        issues.append("ALINA_SYNC_COMPLETE.sh est absent.")
    if issues:
        lines.extend(["", "RANGER_RACINE=FAIL", *[f"- {issue}" for issue in issues]])
    else:
        lines.extend(["", "RANGER_RACINE=PASS"])
    return not issues, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    ok, report = audit(args.root)
    print(report)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())