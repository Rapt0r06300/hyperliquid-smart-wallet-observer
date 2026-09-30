"""#166/#169/#240/#241 — L'INVARIANT « BRANCHER OU ENTERRER », AU NIVEAU DE LA **FONCTION**.

🔴 POURQUOI CE FICHIER EXISTE, ET POURQUOI T3b/T3c/T3e NE SUFFISAIENT PAS
========================================================================
Mes invariants precedents raisonnaient **par MODULE** : « ce fichier est-il importe par la
production ? ». Ici, la reponse est OUI :

    backtesting/regime_detection.py  <- regime_label <- regime_wiring <- scenario_search  (VIVANT)

Et pourtant, sur ses QUATRE fonctions, **une seule** est appelee (`garch11_variance_causale`).
Les trois autres sont mortes -- **dont une qui LIT LE FUTUR**, a huit caracteres de distance du
bon nom, dans le meme fichier :

    from ... import garch11_variance_causale   # le bon (causal, branche depuis #595)
    from ... import garch11_variance           # le meme nom en plus court -- et il triche

C'est une mine. Un jour l'autocompletion choisira, et il y aura du **lookahead dans le moteur de
recherche**, en silence. *Un module vivant peut heberger des fonctions mortes, et l'une d'elles
peut etre dangereuse.*

🚩 ET LA TASKLIST SE TROMPAIT : #241 affirmait « GARCH est CODE mais MORT ». **FAUX** -- le GARCH
causal tourne en production. Ce qui est mort, c'est son jumeau qui fuit. *On ne peut pas enterrer
ce qu'on n'a pas regarde a la bonne echelle.*

Aucun ordre reel.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hl_observer.backtesting.tombstones_backtesting import (
    FONCTION_QUI_LIT_LE_FUTUR,
    FONCTIONS_ENTERREES,
    MODULES_ENTERRES_BACKTESTING,
    TOMBES_BACKTESTING,
)

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "src" / "hl_observer"
BACKTESTING = SRC / "backtesting"


# ============================================================ outils (AST, jamais un grep)


def _symboles_importes(fichier: Path) -> set[str]:
    """Les NOMS reellement importes depuis `backtesting.*` par ce fichier.

    Par l'AST : un grep compterait « garch11_variance » dans le docstring de `regime_label.py`
    (qui explique justement pourquoi il ne faut PAS l'utiliser). *Une mise en garde n'est pas un
    appel.* On l'a deja paye trois fois aujourd'hui.
    """
    out: set[str] = set()
    try:
        arbre = ast.parse(fichier.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return out
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and n.module:
            if "hl_observer.backtesting" in n.module or n.module.startswith("."):
                out |= {a.name for a in n.names}
    return out


def _modules_importes(fichier: Path) -> set[str]:
    out: set[str] = set()
    try:
        arbre = ast.parse(fichier.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return out
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and n.module:
            if n.module.startswith("hl_observer.backtesting."):
                out.add(n.module.split(".")[-1])
            elif n.module == "hl_observer.backtesting":
                out |= {a.name for a in n.names}
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("hl_observer.backtesting."):
                    out.add(a.name.split(".")[-1])
    return out


def _fichiers_de_production() -> list[Path]:
    """Tout `src/`. Les tests et les outils ne sont PAS de la production."""
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.as_posix()]


# ============================================================ 1. LE VERROU CRITIQUE


def test_LA_PRODUCTION_NE_PEUT_PAS_IMPORTER_LA_FONCTION_QUI_LIT_LE_FUTUR():
    """🔴🔴🔴 LE test de cette tache.

    `garch11_variance` lit le futur DEUX FOIS (amorcage sur toute la serie ; out[i] connait r[i]).
    Elle vit dans le MEME fichier que sa version causale, a huit caracteres de distance. Si un jour
    quelqu'un importe la mauvaise, il y aura du lookahead dans `scenario_search` -- et le moteur
    trouvera des « alphas » qui n'existent pas.

    Ce test est le seul obstacle entre l'autocompletion et un mensonge silencieux.
    """
    coupables = []
    for f in _fichiers_de_production():
        if FONCTION_QUI_LIT_LE_FUTUR in _symboles_importes(f):
            coupables.append(f.relative_to(SRC).as_posix())
    assert not coupables, (
        "🔴 LOOKAHEAD : ces fichiers de production importent `%s`, qui LIT LE FUTUR : %s\n"
        "Utilise `garch11_variance_causale` (meme fichier, version causale, branchee depuis #595).\n"
        "Un garde-fou anti-lookahead qui contient du lookahead ne garde rien."
        % (FONCTION_QUI_LIT_LE_FUTUR, ", ".join(coupables))
    )


def test_la_version_CAUSALE_elle_EST_bien_branchee():
    """L'autre moitie de la verite : on n'a pas seulement interdit la mauvaise, on utilise la bonne.

    Si ce test tombe, c'est que le regime n'est plus calcule du tout -- et le gate `regime` se
    degraderait EN SILENCE (c'est exactement le bug d'IMPROVE-20).
    """
    vivants = set()
    for f in _fichiers_de_production():
        vivants |= _symboles_importes(f)
    assert "garch11_variance_causale" in vivants, (
        "la version CAUSALE du GARCH n'est plus importee nulle part : le regime n'est plus "
        "calcule, et le gate se degrade en silence (bug d'IMPROVE-20, deja paye une fois)"
    )


# ============================================================ 2. PAS DE RESURRECTION


def test_aucune_FONCTION_enterree_n_est_importee_par_la_production():
    ressuscitees: list[str] = []
    for f in _fichiers_de_production():
        for nom in _symboles_importes(f) & FONCTIONS_ENTERREES:
            ressuscitees.append("%s <- %s" % (nom, f.relative_to(SRC).as_posix()))
    assert not ressuscitees, (
        "fonction(s) ENTERREE(S) importee(s) par la production : %s\n"
        "Si c'est voulu, retire la tombe de backtesting/tombstones_backtesting.py -- et ecris "
        "POURQUOI la raison de l'enterrement ne tient plus." % ", ".join(ressuscitees)
    )


def test_aucun_MODULE_enterre_n_est_importe_par_la_production():
    ressuscites: list[str] = []
    for f in _fichiers_de_production():
        if f.stem in MODULES_ENTERRES_BACKTESTING:
            continue                                   # un mort peut se citer lui-meme
        for nom in _modules_importes(f) & MODULES_ENTERRES_BACKTESTING:
            ressuscites.append("%s <- %s" % (nom, f.relative_to(SRC).as_posix()))
    assert not ressuscites, (
        "module(s) ENTERRE(S) importe(s) par la production : %s" % ", ".join(ressuscites)
    )


# ============================================================ 3. LA QUALITE DES TOMBES


def test_une_tombe_doit_donner_une_raison_CONTREDISABLE_et_une_REOUVERTURE():
    """« obsolete », « legacy », « inutile » ne sont pas des raisons : ce sont des etiquettes.

    Et une tombe sans condition de reouverture est une decision qu'on ne pourra jamais corriger.
    """
    MOTS_VIDES = ("obsolete", "legacy", "deprecated", "inutile", "ancien")
    for t in TOMBES_BACKTESTING:
        assert t.motif and t.pourquoi and t.preuve and t.reouverture, "tombe incomplete : %s" % t.cible
        assert len(t.pourquoi) > 40, "raison trop courte pour etre contredite : %s" % t.cible
        assert len(t.reouverture) > 20, "reouverture trop vague : %s" % t.cible
        assert not any(m in t.pourquoi.lower() for m in MOTS_VIDES), (
            "la tombe de %s se justifie par une ETIQUETTE, pas par un FAIT" % t.cible
        )


def test_les_4_taches_de_ce_lot_sont_bien_tranchees():
    """#166 (SHAP), #169 (Hawkes), #240 (Kalman), #241 (GARCH qui fuit). Fige, pour ne pas
    reperdre le resultat."""
    assert "kalman_filter_1d" in FONCTIONS_ENTERREES          # #240
    assert "garch11_variance" in FONCTIONS_ENTERREES          # #241 (le jumeau qui fuit)
    assert "cusum_change_points" in FONCTIONS_ENTERREES       # IDEA-82, statut faux decouvert ici
    assert "ml_diagnostics" in MODULES_ENTERRES_BACKTESTING   # #166
    assert "microstructure_extras" in MODULES_ENTERRES_BACKTESTING  # #169


# ============================================================ 4. L'INVARIANT MORD-IL ?


def test_le_detecteur_MORD_sur_un_arbre_FABRIQUE(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """🚩 « Un garde-fou qui ne peut pas echouer ne garde rien. »

    On fabrique un fichier qui importe la fonction interdite, et on verifie que le detecteur le
    voit. Sans ce test, un bug dans `_symboles_importes` rendrait l'invariant VERT et AVEUGLE --
    c'est exactement ce qui est arrive a mon audit de couverture (il annoncait 0 %).
    """
    faux = tmp_path / "faux_module.py"
    faux.write_text(
        "from hl_observer.backtesting.regime_detection import garch11_variance\n"
        "def f(r):\n    return garch11_variance(r)\n",
        encoding="utf-8",
    )
    assert FONCTION_QUI_LIT_LE_FUTUR in _symboles_importes(faux)


def test_le_detecteur_NE_MORD_PAS_sur_une_simple_MENTION(tmp_path: Path):
    """Et il ne doit pas crier au loup : `regime_label.py` CITE `garch11_variance` dans son
    docstring, pour expliquer pourquoi il ne faut PAS l'utiliser. *Une mise en garde n'est pas un
    appel.* Un grep aurait rougi ici -- l'AST, non."""
    faux = tmp_path / "avertissement.py"
    faux.write_text(
        '"""ATTENTION : ne jamais utiliser garch11_variance, elle lit le futur."""\n'
        "from hl_observer.backtesting.regime_detection import garch11_variance_causale\n",
        encoding="utf-8",
    )
    assert FONCTION_QUI_LIT_LE_FUTUR not in _symboles_importes(faux)
    assert "garch11_variance_causale" in _symboles_importes(faux)
