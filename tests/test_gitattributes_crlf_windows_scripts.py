"""AUD-026 — La politique CRLF des scripts Windows est PROUVÉE, pas seulement écrite.

Un `.cmd/.bat/.ps1` livré en LF peut se comporter de travers sous cmd.exe/PowerShell ; et un
working tree dont les fins de ligne divergent du dépôt fabrique un faux « working tree sale »
qui bloque le script de push (c'est précisément la panne vécue). `.gitattributes` fixe
`eol=crlf` pour GARANTIR le CRLF au checkout Windows, quel que soit l'OS.

Ce test échoue si cette garantie disparaît, ou si une extension de script Windows présente dans
le code source n'est pas figée. Invariant MACHINE-INDÉPENDANT : on lit la POLITIQUE
(.gitattributes), jamais les octets du working tree (qui dépendent de l'OS de checkout — cf.
test_env_hermetique). 0 réseau.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
GITATTRIBUTES = RACINE / ".gitattributes"

# Extensions de script Windows qui DOIVENT être livrées en CRLF.
_EXT_CRLF = (".cmd", ".bat", ".ps1", ".psm1")

# Répertoires volumineux / hors-source : ne pas les parcourir (perf + ils ne portent pas la
# politique source). Les scripts Windows vivent à la racine, dans tools/ et config/.
_IGNORE_DIRS = {
    ".git", "runtime", "data", "logs", "archive", "node_modules", "__pycache__",
    ".venv", "venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    "Rapports en continu", "wheelhouse", ".portable",
}


def _regles_eol(texte: str):
    crlf, lf = set(), set()
    for ligne in texte.splitlines():
        l = ligne.strip()
        if not l or l.startswith("#"):
            continue
        m = re.match(r"^\*(\.[A-Za-z0-9]+)\s+.*eol=(crlf|lf)", l)
        if m:
            (crlf if m.group(2) == "crlf" else lf).add(m.group(1).lower())
    return crlf, lf


def _extensions_scripts_windows_dans_source():
    presentes = set()
    for root, dirs, files in os.walk(RACINE):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in _EXT_CRLF:
                presentes.add(ext)
    return presentes


def test_gitattributes_existe():
    assert GITATTRIBUTES.is_file(), ".gitattributes est requis pour figer la politique CRLF."


def test_scripts_windows_pins_crlf():
    crlf, _ = _regles_eol(GITATTRIBUTES.read_text(encoding="utf-8"))
    for ext in (".cmd", ".bat", ".ps1"):
        assert ext in crlf, f"{ext} doit être `text eol=crlf` dans .gitattributes (portabilité Windows)."


def test_sh_reste_lf():
    _, lf = _regles_eol(GITATTRIBUTES.read_text(encoding="utf-8"))
    assert ".sh" in lf, "*.sh doit rester `eol=lf` (scripts POSIX)."


def test_toute_extension_de_script_windows_presente_est_couverte():
    # Cliquet vivant : si un .psm1 (ou autre) entre dans la source sans règle CRLF, ce test rougit.
    crlf, _ = _regles_eol(GITATTRIBUTES.read_text(encoding="utf-8"))
    non_couvertes = sorted(_extensions_scripts_windows_dans_source() - crlf)
    assert not non_couvertes, f"extensions de script Windows présentes mais non figées CRLF: {non_couvertes}"
