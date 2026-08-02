"""[PORTABILITE item 11] Test AUTOMATISE d'une copie complete du projet dans plusieurs chemins
difficiles : espaces+accents, chemin long, racine differente (autre disque simule). Pour CHAQUE copie,
depuis un repertoire courant ETRANGER, on vérifie :
  - tous les modules coeur s'IMPORTENT (le paquet runtime se charge) ;
  - la racine est resolue depuis __file__ = la COPIE, jamais le cwd (item 1) ;
  - l'audit repo-complet est PROPRE sur la copie (item 12) ;
  - une ecriture representative (catalogue de session) reste CONFINEE a la copie (item 5) ;
  - ZERO fichier ecrit hors de la copie (le cwd etranger reste intact).
Les caches compiles (__pycache__) sont EXCLUS de la copie (item 6) : Python recompile tout seul.
Ce qui exige le Python EMBARQUE (install hors ligne des deps) n'est pas simulable ici -> couvert par
preparer_python_portable.cmd / install_portable_runtime.ps1 (Windows). 0 reseau.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# Script execute DANS la copie, depuis un cwd etranger : il ne doit dependre QUE de son emplacement.
_SONDE = r"""
import json, sys
from pathlib import Path
import hl_observer.portabilite as P
# tous les modules coeur du runtime + collecteurs cataloguables se chargent :
import hl_observer.ops.session_catalog as SC
import hl_observer.ops.archive_portable
import hl_observer.ops.premier_lancement
import hl_observer.ops.session_harvest
import hl_observer.ops.lab_flux
import audit_portabilite as A

racine = P.racine_projet()
attendue = Path(sys.argv[1]).resolve()
# ecriture representative : une session cataloguee, qui DOIT atterrir sous la copie.
cat = SC.CatalogueSession(str(racine), "run_multichemin")
cat.demarrer()
chemin_cat = SC.chemin_catalogue(str(racine), "run_multichemin")
violations = A.auditer(str(racine))
print(json.dumps({
    "racine": str(racine),
    "racine_ok": racine == attendue,
    "catalogue_sous_copie": str(chemin_cat).startswith(str(attendue)),
    "catalogue_existe": chemin_cat.is_file(),
    "audit_violations": len(violations),
}))
"""


def _copier_projet(dest: Path) -> Path:
    """Copie le runtime portable-critique dans `dest` (sans __pycache__ : item 6). Rend la racine copiee."""
    dest.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    shutil.copytree(RACINE / "src" / "hl_observer", dest / "src" / "hl_observer", ignore=ignore)
    (dest / "tools").mkdir(exist_ok=True)
    for nom in ("audit_portabilite.py", "portable_env.cmd", "wheelhouse_lock.py",
                "preparer_python_portable.cmd"):
        src = RACINE / "tools" / nom
        if src.is_file():
            shutil.copy2(src, dest / "tools" / nom)
    for nom in ("pyproject.toml", "LANCER_HYPERSMART.cmd", "ANALYSER_BACKTESTS_REPLAYS.cmd",
                "CREER_ARCHIVE_PORTABLE.cmd"):
        src = RACINE / nom
        if src.is_file():
            shutil.copy2(src, dest / nom)
    return dest


def _lancer_sonde(copie: Path, cwd_etranger: Path) -> dict:
    env = {"PYTHONPATH": "%s:%s" % (copie / "src", copie / "tools"),
           "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", _SONDE, str(copie)],
                       cwd=str(cwd_etranger), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, "sonde KO:\n%s\n%s" % (r.stdout, r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


def _fichiers(dossier: Path) -> set:
    return {p.relative_to(dossier) for p in dossier.rglob("*") if p.is_file()}


def _scenario(tmp_path: Path, sous_chemin: str):
    """Copie le projet sous un chemin difficile + un cwd etranger, lance la sonde, verifie l'isolation."""
    copie = _copier_projet(tmp_path / sous_chemin / "Projet invest")
    cwd_etranger = tmp_path / "cwd_etranger"
    cwd_etranger.mkdir()
    avant = _fichiers(cwd_etranger)
    res = _lancer_sonde(copie, cwd_etranger)
    apres = _fichiers(cwd_etranger)
    assert res["racine_ok"], "racine mal resolue: %s" % res["racine"]
    assert res["catalogue_sous_copie"] and res["catalogue_existe"], "ecriture hors copie: %s" % res
    assert res["audit_violations"] == 0, "audit non propre sur la copie"
    assert avant == apres, "des fichiers ont ete ecrits dans le cwd etranger (fuite hors copie)"
    return res


def test_copie_espaces_et_accents(tmp_path):
    _scenario(tmp_path, "Sauvegarde éval 2026 (copie)")


def test_copie_chemin_long(tmp_path):
    long = "/".join("niveau_tres_profond_%02d_pour_chemin_long" % i for i in range(6))
    _scenario(tmp_path, long)


def test_copie_racine_differente(tmp_path):
    # simule un autre disque : une racine totalement differente, sans rapport avec l'originale.
    _scenario(tmp_path, "AUTRE_DISQUE_SIMULE/D_drive")
