"""Audit repo-complet des dépendances machine réellement non portables.

Le scanner reste fail-closed sur les chemins absolus utilisés comme configuration/exécution et sur
les accès registre arbitraires ou en écriture. Il distingue cependant les littéraux purement
diagnostiques : exemples de chemin court, motifs anti-fuite et lecture read-only de MachineGuid
utilisée uniquement pour prouver qu'une archive a changé de machine.
"""
from __future__ import annotations

import re
from pathlib import Path


def _cibles(racine: Path) -> list[Path]:
    cibles: list[Path] = []
    for rel in (
        "LANCER_HYPERSMART.cmd",
        "ANALYSER_BACKTESTS_REPLAYS.cmd",
        "CREER_ARCHIVE_PORTABLE.cmd",
        "tools/portable_env.cmd",
    ):
        p = racine / rel
        if p.is_file():
            cibles.append(p)
    src = racine / "src" / "hl_observer"
    if src.is_dir():
        cibles += [p for p in src.rglob("*.py") if "__pycache__" not in p.parts]
    tools = racine / "tools"
    if tools.is_dir():
        cibles += [p for p in tools.glob("*.py") if p.name != "audit_portabilite.py"]
    return cibles


_DRIVE = re.compile(r"""['"(\s]([A-Za-z]:\\)""")
_SANDBOX = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/")
_USERS = re.compile(r"[Cc]:\\Users|Users\\flo", re.IGNORECASE)
_REGISTRE = re.compile(r"\bwinreg\b|\bHKEY_[A-Z_]+|\breg\s+add\b|\breg\s+query\b")
_REGISTRE_ECRITURE = re.compile(
    r"\breg\s+(?:add|delete)\b|winreg\.(?:SetValue|SetValueEx|CreateKey|CreateKeyEx|DeleteKey|DeleteValue)",
    re.IGNORECASE,
)
_DEF = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")

# Deux fonctions peuvent lire MachineGuid en lecture seule pour produire une empreinte hashée.
# Elles ne configurent rien et leur panne est déjà tolérée : l'archive reste fonctionnelle.
_MACHINE_ID_READERS = {
    "src/hl_observer/ops/premier_lancement.py": {"_identite_hote"},
    "src/hl_observer/ops/portable_clone.py": {"machine_fingerprint"},
}


def _est_commentaire(ligne: str, est_cmd: bool) -> bool:
    s = ligne.strip()
    if est_cmd:
        return s.upper().startswith("REM") or s.startswith("::")
    return s.startswith("#")


def _litteral_diagnostic_portable(ligne: str) -> bool:
    """Littéraux qui décrivent/détectent un chemin sans jamais imposer ce chemin au runtime."""
    low = ligne.casefold()
    return any(
        marqueur in low
        for marqueur in (
            "deplacer vers c:\\\\hypersmart",
            "choose a short path such as",
            "extract to a short writable path such as",
            '"long_path_recommendation"',
            "token in rel.casefold()",
        )
    )


def auditer(racine: str | Path) -> list[dict]:
    """Rend les violations {fichier, ligne, categorie, texte}. Vide = portable."""
    racine = Path(racine)
    violations: list[dict] = []
    for p in _cibles(racine):
        est_cmd = p.suffix.lower() == ".cmd"
        try:
            lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rel = p.relative_to(racine).as_posix()
        fonction: str | None = None
        for i, ln in enumerate(lignes, 1):
            if not est_cmd:
                match_def = _DEF.match(ln)
                if match_def:
                    fonction = match_def.group(1)
                elif ln and not ln[0].isspace() and not ln.lstrip().startswith(("#", "@")):
                    # Sortie d'une fonction au niveau module.
                    fonction = None
            if _est_commentaire(ln, est_cmd):
                continue
            sans_vars = ln.replace("%~dp0", "").replace("%HYPERSMART_PROJECT_ROOT%", "")
            for cat, rx in (
                ("chemin_absolu_disque", _DRIVE),
                ("chemin_sandbox_profil", _SANDBOX),
                ("users_flo", _USERS),
                ("registre_windows", _REGISTRE),
            ):
                if not rx.search(sans_vars):
                    continue
                if cat == "chemin_absolu_disque" and _litteral_diagnostic_portable(sans_vars):
                    continue
                if cat == "registre_windows":
                    readers = _MACHINE_ID_READERS.get(rel, set())
                    if fonction in readers and not _REGISTRE_ECRITURE.search(sans_vars):
                        continue
                violations.append(
                    {"fichier": rel, "ligne": i, "categorie": cat, "texte": ln.strip()[:160]}
                )
    return violations


def formater(violations: list[dict]) -> str:
    if not violations:
        return "PORTABILITE OK : aucune dependance machine dans le runtime actif."
    out = ["PORTABILITE : %d violation(s)" % len(violations)]
    for v in violations:
        out.append("  [%s] %s:%d  %s" % (v["categorie"], v["fichier"], v["ligne"], v["texte"]))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from hl_observer.portabilite import racine_projet

    ap = argparse.ArgumentParser(
        prog="audit_portabilite",
        description="Audit repo-complet des dependances machine (item 12).",
    )
    ap.add_argument("--racine", default=None, help="racine du projet (defaut: auto depuis ce fichier)")
    args = ap.parse_args(argv)
    racine = Path(args.racine) if args.racine else racine_projet(Path(__file__))
    violations = auditer(racine)
    print(formater(violations))
    return 0 if not violations else 1


__all__ = ["auditer", "formater", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
