"""[AUD-180/183/184/185/218/219] Robustesse du lanceur Windows : codes de sortie normalises,
chemins a caracteres speciaux, kill de l'ARBRE de process (enfants), forcage locale/timezone
(UTF-8/UTC), ecriture ATOMIQUE tolerante aux verrous (antivirus/file-lock), et sequence
double-clic. Logique testable ; la preuve PROCESSUS Windows reste au CI windows-latest."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Mapping

EXIT_GO = 0
EXIT_ERREUR = 1
EXIT_NO_GO = 2
EXIT_VERROU = 3
EXIT_ENV = 4

_CODES = {"GO": EXIT_GO, "OK": EXIT_GO, "NO_GO": EXIT_NO_GO, "ERREUR": EXIT_ERREUR,
          "ERROR": EXIT_ERREUR, "VERROU": EXIT_VERROU, "LOCKED": EXIT_VERROU, "ENV": EXIT_ENV}


def code_sortie(verdict: str) -> int:
    """Verdict -> code de sortie normalise. Un verdict inconnu = ERREUR (jamais 0 par defaut)."""
    return _CODES.get(str(verdict).upper(), EXIT_ERREUR)


def chemin_windows_sur(chemin: str) -> str:
    """Rend un chemin Windows robuste aux ESPACES et caracteres speciaux (guillemets si besoin) :
    le lanceur doit survivre a 'C:\\Users\\...\\Projet invest\\'."""
    c = str(chemin)
    if any(ch in c for ch in " &()[]{}^=;!'+,`~"):
        c = '"' + c.replace('"', '') + '"'
    return c


def commande_kill_arbre(pid: int) -> list[str]:
    """Commande Windows pour tuer un process ET tous ses enfants (/T) proprement (/F)."""
    return ["taskkill", "/PID", str(int(pid)), "/T", "/F"]


def forcer_locale_utc(env: Mapping[str, str] | None = None) -> dict:
    """Environnement DETERMINISTE independant de la locale/timezone machine : UTF-8, LC_ALL=C, TZ=UTC.
    Evite les bugs de virgule decimale / fuseau / encodage Windows."""
    e = dict(env or {})
    e["PYTHONUTF8"] = "1"
    e["PYTHONIOENCODING"] = "utf-8"
    e["LC_ALL"] = "C"
    e["LANG"] = "C.UTF-8"
    e["TZ"] = "UTC"
    return e


def ecrire_atomique_tolerant_verrou(chemin: str | Path, donnees: bytes, *, tentatives: int = 5) -> dict:
    """Ecriture ATOMIQUE (tmp + os.replace) TOLERANTE aux verrous : si un antivirus/indexeur tient le
    fichier (PermissionError), on retente. os.replace est atomique -> jamais de fichier a moitie ecrit."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(chemin.parent), prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(donnees if isinstance(donnees, bytes) else str(donnees).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        derniere = None
        for essai in range(1, max(1, tentatives) + 1):
            try:
                os.replace(tmp, str(chemin))
                return {"ok": True, "essais": essai}
            except PermissionError as exc:
                derniere = exc
        return {"ok": False, "essais": tentatives, "erreur": str(derniere)}
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def sequence_double_clic() -> list[str]:
    """Sequence LOGIQUE d'un double-clic sur le .cmd : bootstrap env -> porte d'analyse -> lab. La
    preuve PROCESSUS (double-clic reel Windows) reste un artefact CI windows-latest."""
    return ["restaurer_portable_env", "poser_porte_analyser_session", "lancer_lab_alpha"]
