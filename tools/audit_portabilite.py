"""[PORTABILITE item 12] Audit REPO-COMPLET des dépendances machine — pas seulement les 2 CMD.

Cherche dans TOUT le runtime actif (src/hl_observer, tools/*.py, les .cmd maîtres + portable_env +
archive) les vrais BRISEURS de portabilité, et échoue si l'un réapparaît :
  - chemin absolu à lettre de disque (`C:\\...`, `D:\\...`) dans du CODE (hors commentaire) ;
  - chemin absolu du bac à sable / d'un profil (`/home/<user>/`, `/Users/<user>/`) codé en dur ;
  - `C:\\Users` / `Users\\flo` littéral ;
  - accès au registre Windows (`winreg`, `HKEY_`, `reg add`, `reg query`).

On ne signale PAS les faux positifs à faible signal : `Path.home()/Desktop` (sortie d'archive par
utilisateur, par conception), `expanduser` conditionnel, `gettempdir` de scratch, ports localhost —
ils ne cassent pas la portabilité. On vise ce qui EMPÊCHE une copie de tourner ailleurs.

Pur, 0 réseau, importable et testable. `main()` rend un code non nul s'il reste une violation.
"""
from __future__ import annotations

import re
from pathlib import Path

# Périmètre = le runtime qui DOIT être portable. On exclut les fixtures de test, le code mort (archive/),
# le legacy hyper_smart_observer (Desktop par conception) et l'état généré (runtime/).
def _cibles(racine: Path) -> list[Path]:
    cibles: list[Path] = []
    for rel in ("LANCER_HYPERSMART.cmd", "ANALYSER_BACKTESTS_REPLAYS.cmd",
                "CREER_ARCHIVE_PORTABLE.cmd", "tools/portable_env.cmd"):
        p = racine / rel
        if p.is_file():
            cibles.append(p)
    src = racine / "src" / "hl_observer"
    if src.is_dir():
        cibles += [p for p in src.rglob("*.py") if "__pycache__" not in p.parts]
    tools = racine / "tools"
    if tools.is_dir():
        # l'auditeur lui-même DÉFINIT les motifs qu'il cherche (regex) : il ne se scanne pas.
        cibles += [p for p in tools.glob("*.py") if p.name != "audit_portabilite.py"]
    return cibles


_DRIVE = re.compile(r"""['"(\s]([A-Za-z]:\\)""")          # C:\ D:\ ... précédé d'un quote/espace/paren
_SANDBOX = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/")  # /home/claude/  /Users/flo/
_USERS = re.compile(r"[Cc]:\\Users|Users\\flo", re.IGNORECASE)
_REGISTRE = re.compile(r"\bwinreg\b|\bHKEY_[A-Z_]+|\breg\s+add\b|\breg\s+query\b")


def _est_commentaire(ligne: str, est_cmd: bool) -> bool:
    s = ligne.strip()
    if est_cmd:
        return s.upper().startswith("REM") or s.startswith("::")
    return s.startswith("#")


def auditer(racine: str | Path) -> list[dict]:
    """Rend la liste des violations {fichier, ligne, categorie, texte}. Vide = portable."""
    racine = Path(racine)
    violations: list[dict] = []
    for p in _cibles(racine):
        est_cmd = p.suffix.lower() == ".cmd"
        try:
            lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rel = p.relative_to(racine).as_posix()
        for i, ln in enumerate(lignes, 1):
            if _est_commentaire(ln, est_cmd):
                continue                                   # un commentaire ne casse pas la portabilité
            # tolère %~dp0 / %HYPERSMART_*% : ce sont des chemins DÉRIVÉS, pas absolus machine.
            sans_vars = ln.replace("%~dp0", "").replace("%HYPERSMART_PROJECT_ROOT%", "")
            for cat, rx in (("chemin_absolu_disque", _DRIVE), ("chemin_sandbox_profil", _SANDBOX),
                            ("users_flo", _USERS), ("registre_windows", _REGISTRE)):
                if rx.search(sans_vars):
                    violations.append({"fichier": rel, "ligne": i, "categorie": cat,
                                       "texte": ln.strip()[:160]})
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
    ap = argparse.ArgumentParser(prog="audit_portabilite",
                                 description="Audit repo-complet des dependances machine (item 12).")
    ap.add_argument("--racine", default=None, help="racine du projet (defaut: auto depuis ce fichier)")
    args = ap.parse_args(argv)
    racine = Path(args.racine) if args.racine else racine_projet(Path(__file__))
    violations = auditer(racine)
    print(formater(violations))
    return 0 if not violations else 1


__all__ = ["auditer", "formater", "main"]


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
