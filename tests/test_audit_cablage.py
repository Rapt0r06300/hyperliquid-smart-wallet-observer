"""T3 -- L'AUDIT DE CABLAGE : « qui appelle ce module ? » (2026-07-12)

Ces tests defendent l'outil qui aurait trouve, en UNE SECONDE, les cinq cablages morts que le
projet a mis des SEMAINES a decouvrir un par un, par accident :

    poller L2 jamais demarre · jambe funding · garde-fou lookahead · copy-follow non garde ·
    delta_neutral_carry (pur, teste, complet... et jamais alimente).

La pathologie a un nom : **la capacite est presente, l'interrupteur est eteint, personne ne rale.**

Aucun ordre reel.
"""
from __future__ import annotations

import sys
from pathlib import Path

from hl_observer.audit.cablage import (
    Interrupteur,
    auditer_les_interrupteurs,
    auditer_les_modules,
    flags_lus,
    flags_poses,
    graphe_des_imports,
    modules_atteignables,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


# ============ LE 3e BUG DE MON PROPRE AUDIT : UN FILTRE QUI EFFACAIT UN PAQUET ENTIER


def test_le_filtre_de_l_audit_ne_doit_PAS_effacer_un_paquet_de_PRODUCTION():
    """🚩 T3c -- L'OUTIL QUI TRAQUAIT LE CODE MORT EN CACHAIT LUI-MEME HUIT.

    `tools/auditer_cablage.py` sautait les dossiers de donnees avec un `in` sur la chaine :

        IGNORE = ("__pycache__", "runtime/", "data/", ..., "_archive", "logs/")
        if any(x in rel for x in IGNORE): continue

    Intention : ignorer le dossier de DONNEES `runtime/` a la RACINE (logs, etat, DB).
    Effet reel : `src/hl_observer/runtime/hot_path.py` contient AUSSI la sous-chaine
    "runtime/" -> **tout le paquet de PRODUCTION `src/hl_observer/runtime/` etait invisible.**

    Huit modules effaces en silence, dont le coeur du travail P4/P5 :
    hot_path, event_driven_decider, persistent_poll_runner, bounded_event_queue,
    graceful_shutdown, safe_mode -- plus `release/clean_archive.py`, mange par "_archive".

    Un module INVISIBLE ne peut jamais etre declare MORT. C'est le pire angle mort possible
    pour un outil dont le seul travail est de trouver ce qui est mort.

    Ce test fige la correction : le filtre est ANCRE (prefixe de racine, ou segment entier).
    """
    from auditer_cablage import _a_ignorer  # tools/auditer_cablage.py

    # --- ce qu'on VEUT ignorer : donnees, caches, code volontairement desactive
    assert _a_ignorer("runtime/state.db")
    assert _a_ignorer("data/reports/x.json")
    assert _a_ignorer("logs/run.log")
    assert _a_ignorer("src/hl_observer/__pycache__/x.pyc")
    assert _a_ignorer("src/hl_observer/cli_pkg_DISABLED/tui_status.py")
    assert _a_ignorer("src/hl_observer/_archive/vieux.py")

    # --- LE BUG : du code de PRODUCTION qui ne doit JAMAIS etre efface
    assert not _a_ignorer("src/hl_observer/runtime/hot_path.py")
    assert not _a_ignorer("src/hl_observer/runtime/event_driven_decider.py")
    assert not _a_ignorer("src/hl_observer/runtime/persistent_poll_runner.py")
    assert not _a_ignorer("src/hl_observer/runtime/bounded_event_queue.py")
    assert not _a_ignorer("src/hl_observer/runtime/graceful_shutdown.py")
    assert not _a_ignorer("src/hl_observer/runtime/safe_mode.py")
    assert not _a_ignorer("src/hl_observer/release/clean_archive.py")

    # --- et le principe general : un nom de FICHIER ne doit pas declencher un filtre de DOSSIER
    assert not _a_ignorer("src/hl_observer/paper_trading/archive_helper.py")


# ============ LE 4e BUG : L'AUDIT SUR-ACCUSAIT (il codait ses portes EN DUR)


def test_un_python_dash_m_dans_un_LANCEUR_est_un_POINT_D_ENTREE():
    """🚩 T3d -- MON AUDIT DECLARAIT MORT UN MODULE QUI TOURNE A CHAQUE SESSION.

    `_points_d_entree` codait EN DUR la liste des portes. Son commentaire disait meme, noir sur
    blanc : « Ce sont les TROIS seules portes » (`__main__`, `cli`, `ui.*`).

    Il y en avait une QUATRIEME, et elle vit dans un fichier PowerShell :

        tools/hypersmart_simulation_poll_loop.ps1:298
        $runnerArgs = "-u -m hl_observer.runtime.persistent_poll_runner --root ..."

    Le lanceur reel demarre ce runner en sous-processus. L'AST ne peut pas le voir : ce n'est pas
    du Python, c'est du PowerShell. Resultat : `persistent_poll_runner` ET tout ce qu'il importe
    (`detailed_logger`, `equity_history_store`) etaient declares MORTS -- alors qu'ils tournent
    a chaque session.

    Mon audit ne se contentait pas de CACHER des modules (bug precedent) : il en ACCUSAIT
    faussement d'autres. Une erreur dans chaque sens, le meme jour.

    Les portes sont maintenant DERIVEES des lanceurs. Une liste ecrite a la main se perime le
    jour ou quelqu'un ajoute une porte -- et personne ne rale.
    """
    from hl_observer.audit.cablage import portes_declarees_par_les_lanceurs

    lanceurs = {
        "tools/poll_loop.ps1": (
            '$runnerArgs = "-u -m hl_observer.runtime.persistent_poll_runner --root `"$Root`""\n'
        ),
        "LANCER.cmd": "python -m hl_observer ui\r\n",
        "tools/autre.ps1": "python -m pytest tests/\n",          # pas a nous : ignore
    }
    portes = portes_declarees_par_les_lanceurs(lanceurs)
    assert "hl_observer.runtime.persistent_poll_runner" in portes
    assert "hl_observer" in portes
    assert not any(p.startswith("pytest") for p in portes)


def test_un_module_lance_par_un_LANCEUR_n_est_PAS_declare_mort():
    """La consequence, de bout en bout : le runner du poller et TOUT ce qu'il importe sont vivants.

    C'est le test qui aurait empeche l'erreur. Sans les lanceurs, `runner` et `journal_du_poller`
    sont declares morts. Avec, ils sont vivants -- et c'est la verite : le bot les execute a
    chaque session.
    """
    fichiers = {
        # la seule porte que l'AST connaisse
        "src/hl_observer/__main__.py": "from hl_observer.cli import app\n",
        "src/hl_observer/cli.py": "app = 1\n",
        # la porte CACHEE, demarree par un .ps1 en sous-processus
        "src/hl_observer/runtime/runner.py": "from hl_observer.runtime import journal_du_poller\n",
        "src/hl_observer/runtime/journal_du_poller.py": "def log(): ...\n",
        "tests/test_runner.py": "from hl_observer.runtime import runner\n",
    }
    lanceur = {"tools/poll_loop.ps1": '"-u -m hl_observer.runtime.runner --root x"'}

    # SANS les lanceurs : l'audit accuse a tort (c'etait l'etat du 12/07 au matin)
    sans = auditer_les_modules(fichiers)
    assert "hl_observer.runtime.runner" in sans.testes_non_branches
    assert "hl_observer.runtime.journal_du_poller" in sans.orphelins

    # AVEC : la verite. Le runner est une porte, et ce qu'il importe vit.
    avec = auditer_les_modules(fichiers, lanceurs=lanceur)
    assert "hl_observer.runtime.runner" not in avec.testes_non_branches
    assert "hl_observer.runtime.journal_du_poller" not in avec.orphelins
    assert "hl_observer.runtime.journal_du_poller" not in avec.testes_non_branches


# ============ LE 5e BUG : L'AUDIT DECLARAIT MORT LE MOTEUR QU'ON LANCE LE PLUS SOUVENT (#597)


def test_un_script_tools_lance_par_un_cmd_est_une_PORTE():
    """🚩 #597 -- LE CLIQUET A ROUGI (304 > 303), ET C'EST L'AUDIT QUI AVAIT TORT.

    Reflexe naturel devant un cliquet qui rougit : relever le plafond. C'est exactement ce
    qu'un cliquet interdit. Alors on est alle voir QUI etait le 304e -- et dans la liste des
    "morts" on a trouve `hl_observer.backtesting.scenario_search` : le moteur qui a evalue
    150 000 000 de scenarios, lance des DIZAINES de fois.

    L'audit ne connaissait qu'une forme de porte : `python -m hl_observer.X`. Or la recherche
    ne se lance pas comme ca :

        python tools\\h181_malediction_du_vainqueur.py
        python tools\\couverture_de_lignes.py

    Un script `tools/*.py` qu'un .cmd demarre EST une porte. Elle ne s'ecrit simplement pas
    en `-m`. 31 modules de recherche etaient declares morts pour cette seule raison.
    """
    from hl_observer.audit.cablage import outils_demarres_par_les_lanceurs

    lanceurs = {
        "H181-MESURE.cmd": "python tools\\h181_malediction_du_vainqueur.py >> h181.txt 2>&1\n",
        "COUVERTURE.cmd": 'python -u "tools/couverture_de_lignes.py"\n',
        "LANCER.cmd": "python -m hl_observer ui\n",          # pas un outil : une porte `-m`
        "TESTS.cmd": "python -m pytest tests\\\n",           # pas un outil non plus
    }
    demarres = outils_demarres_par_les_lanceurs(lanceurs)
    assert "tools/h181_malediction_du_vainqueur.py" in demarres
    assert "tools/couverture_de_lignes.py" in demarres, "la forme `python -u \"tools/x.py\"` est ratee"
    assert len(demarres) == 2, "un `-m` a ete pris pour un script d'outil : %r" % demarres


def test_un_lanceur_avec_prefixe_pdp0_est_reconnu():
    """🔴 22/07 — TOUT-TESTER.cmd lance `python \"%~dp0tools\\lanceur_tout_tester.py\"`. Le
    prefixe `%~dp0` (chemin relatif au .cmd, idiome Windows du projet) faisait RATER le match ->
    le lanceur passait pour non demarre, et tout ce qu'il importe (dont loop_readiness) pour mort.
    On reconnait desormais `%~dp0` et `.\\`/`./` avant le chemin capture."""
    from hl_observer.audit.cablage import outils_demarres_par_les_lanceurs
    lanceurs = {
        "TOUT-TESTER.cmd": 'python "%~dp0tools\\lanceur_tout_tester.py" %*\n',
        "AUTRE.cmd": "python .\\tools\\bot_ready.py\n",
    }
    d = outils_demarres_par_les_lanceurs(lanceurs)
    assert "tools/lanceur_tout_tester.py" in d, "le prefixe %~dp0 fait toujours rater le lanceur"
    assert "tools/bot_ready.py" in d
    # non-regression : un `-m` n'est toujours PAS un script d'outil
    assert outils_demarres_par_les_lanceurs({"L.cmd": "python -m hl_observer ui\n"}) == []


def test_le_MOTEUR_DE_RECHERCHE_n_est_plus_declare_MORT():
    """De bout en bout : sans les outils, la recherche est "morte". Avec, elle est OUTILLEE."""
    fichiers = {
        "src/hl_observer/__main__.py": "from hl_observer import cli\n",
        "src/hl_observer/cli.py": "app = 1\n",
        "src/hl_observer/backtesting/scenario_search.py":
            "from hl_observer.backtesting import eval_trades\n",
        "src/hl_observer/backtesting/eval_trades.py": "def evaluer(): ...\n",
        "tests/test_search.py": "from hl_observer.backtesting import scenario_search\n",
    }
    outils = {"tools/chercher.py":
              "from hl_observer.backtesting.scenario_search import search\n"}
    lanceurs = {"CHERCHER.cmd": "python tools\\chercher.py > out.txt\n"}

    # SANS les outils : l'audit accuse le moteur qu'on lance le plus souvent
    sans = auditer_les_modules(fichiers, lanceurs=lanceurs)
    assert "hl_observer.backtesting.scenario_search" in sans.testes_non_branches
    assert "hl_observer.backtesting.eval_trades" in sans.orphelins
    assert sans.outilles == []

    # AVEC : la verite. Une porte est une porte, meme si elle ne s'ecrit pas en `-m`.
    avec = auditer_les_modules(fichiers, lanceurs=lanceurs, outils=outils)
    assert "hl_observer.backtesting.scenario_search" in avec.outilles
    assert "hl_observer.backtesting.eval_trades" in avec.outilles, (
        "l'atteignabilite depuis un outil doit etre TRANSITIVE, comme depuis une porte `-m`"
    )
    assert avec.testes_non_branches == []
    assert avec.orphelins == []
    assert avec.as_dict()["outilles"] == sorted(avec.outilles)


def test_un_outil_que_PERSONNE_ne_lance_n_est_PAS_une_porte():
    """LE VERROU QUI EMPECHE #597 D'ETRE UN AFFAIBLISSEMENT.

    Si tout `tools/*.py` comptait comme une porte, n'importe qui pourrait ressusciter un module
    mort en ecrivant un brouillon de 3 lignes dans `tools/`. Une porte, c'est un script qu'un
    HUMAIN peut reellement demarrer -- donc cite par un .cmd/.ps1. Un brouillon n'est pas une
    porte : c'est un brouillon.
    """
    fichiers = {
        "src/hl_observer/__main__.py": "X = 1\n",
        "src/hl_observer/mort.py": "def jamais(): ...\n",
        "tests/test_mort.py": "from hl_observer import mort\n",
    }
    outils = {"tools/brouillon.py": "from hl_observer.mort import jamais\n"}
    lanceurs = {"LANCER.cmd": "python -m hl_observer ui\n"}     # ne lance PAS le brouillon

    v = auditer_les_modules(fichiers, lanceurs=lanceurs, outils=outils)
    assert v.outilles == [], "un brouillon de tools/ que rien ne lance a ressuscite un mort"
    assert "hl_observer.mort" in v.testes_non_branches


def test_un_outil_qui_importe_un_AUTRE_outil_transmet_la_porte():
    """`tools/` se met lui-meme sur le sys.path : un outil lance peut en importer un autre.
    Ne suivre qu'un seul niveau raterait la chaine -- meme lecon que l'atteignabilite
    transitive entre modules."""
    fichiers = {
        "src/hl_observer/__main__.py": "X = 1\n",
        "src/hl_observer/backtesting/moteur.py": "def go(): ...\n",
    }
    outils = {
        "tools/lance.py": "import aide\n",
        "tools/aide.py": "from hl_observer.backtesting.moteur import go\n",
    }
    lanceurs = {"GO.cmd": "python tools\\lance.py\n"}

    v = auditer_les_modules(fichiers, lanceurs=lanceurs, outils=outils)
    assert "hl_observer.backtesting.moteur" in v.outilles, (
        "un outil lance qui importe un autre outil doit transmettre la porte"
    )


# ====================================== ATTEIGNABILITE TRANSITIVE (le bug de mon propre audit)


def test_un_module_importe_UNIQUEMENT_par_un_module_MORT_est_MORT_AUSSI():
    """LE BUG DE MA 1re VERSION, reduit a son squelette.

    Ma 1re version demandait « quelqu'un hors tests m'importe-t-il ? » -- un SEUL saut. Elle
    declarait donc `latency_tracker` **branche**, parce que `scale_perf_runtime` l'importe...
    alors que `scale_perf_runtime` n'est appele par PERSONNE.

        latency_tracker  <--  scale_perf_runtime  <--  (rien)

    Un module importe uniquement par un mort est mort. Il faut remonter jusqu'a une VRAIE porte.
    """
    fichiers = {
        # la porte : le lanceur fait `python -m hl_observer`
        "src/hl_observer/__main__.py": "from hl_observer import cli\n",
        "src/hl_observer/cli.py": "from hl_observer.vivant import go\n",
        "src/hl_observer/vivant.py": "X = 1\n",
        # la chaine morte : personne n'entre jamais par la
        "src/hl_observer/mort.py": "from hl_observer.suit_le_mort import f\n",
        "src/hl_observer/suit_le_mort.py": "Y = 2\n",
        "tests/test_mort.py": "from hl_observer.mort import f\n",
        "tests/test_suit.py": "from hl_observer.suit_le_mort import f\n",
    }
    v = auditer_les_modules(fichiers)

    assert "hl_observer.vivant" not in v.testes_non_branches
    assert "hl_observer.vivant" not in v.orphelins

    # `mort` est teste -> non branche. Et `suit_le_mort`, importe SEULEMENT par `mort` (mort)
    # + un test, doit tomber avec lui. La 1re version le disait "branche".
    assert "hl_observer.mort" in v.testes_non_branches
    assert "hl_observer.suit_le_mort" in v.testes_non_branches, (
        "REGRESSION : un module importe par un module MORT a ete declare vivant. "
        "L'atteignabilite doit etre TRANSITIVE, pas a un saut."
    )


def test_les_paquets_ANCETRES_sont_executes_eux_aussi():
    """2e BUG DE MON AUDIT, attrape juste avant de publier un chiffre faux.

    `from hl_observer.edge.edge_remaining import f` n'importe pas QUE `edge_remaining` :
    Python execute AUSSI `hl_observer/__init__.py` puis `hl_observer/edge/__init__.py`.
    Si cet `__init__` importe `edge_calculator`, alors `edge_calculator` EST charge.

    Ma 1re version transitive ne remontait pas aux ancetres : elle declarait morts
    `edge_calculator`, `exit_engine` et la moitie de `paper_trading/`. CLAUDE.md disait le
    contraire -- et c'est CLAUDE.md qui avait raison. Verifier AVANT de publier.
    """
    fichiers = {
        "src/hl_observer/__main__.py": "from hl_observer.edge.edge_remaining import f\n",
        "src/hl_observer/edge/__init__.py":
            "from hl_observer.edge.edge_calculator import compute_net_edge\n",
        "src/hl_observer/edge/edge_remaining.py": "def f(): ...\n",
        "src/hl_observer/edge/edge_calculator.py": "def compute_net_edge(): ...\n",
        "tests/test_calc.py": "from hl_observer.edge.edge_calculator import compute_net_edge\n",
    }
    v = auditer_les_modules(fichiers)
    assert "hl_observer.edge.edge_calculator" not in v.testes_non_branches, (
        "REGRESSION : un module tire par le __init__ d'un paquet importe a ete declare MORT. "
        "Python execute les __init__ des paquets ancetres."
    )
    assert "hl_observer.edge.edge_calculator" not in v.orphelins


def test_l_atteignabilite_remonte_toute_la_chaine():
    fichiers = {
        "src/hl_observer/__main__.py": "from hl_observer import a\n",
        "src/hl_observer/a.py": "from hl_observer import b\n",
        "src/hl_observer/b.py": "from hl_observer import c\n",
        "src/hl_observer/c.py": "Z = 3\n",
    }
    vus = modules_atteignables(fichiers, ["hl_observer.__main__"])
    assert {"hl_observer.a", "hl_observer.b", "hl_observer.c"} <= vus


def test_un_cycle_entre_deux_morts_ne_les_ressuscite_PAS():
    """Deux modules qui s'importent l'un l'autre se « justifient » mutuellement -- un compteur
    d'importeurs les croit vivants. L'atteignabilite depuis la porte, non."""
    fichiers = {
        "src/hl_observer/__main__.py": "X = 1\n",
        "src/hl_observer/p.py": "from hl_observer import q\n",
        "src/hl_observer/q.py": "from hl_observer import p\n",
        "tests/test_pq.py": "from hl_observer import p, q\n",
    }
    v = auditer_les_modules(fichiers)
    assert "hl_observer.p" in v.testes_non_branches
    assert "hl_observer.q" in v.testes_non_branches


# ============================================================ le graphe des imports

def test_le_graphe_dit_QUI_importe_QUOI():
    fichiers = {
        "src/hl_observer/a.py": "from hl_observer.b import truc\n",
        "src/hl_observer/b.py": "X = 1\n",
        "src/hl_observer/c.py": "import hl_observer.b\n",
    }
    g = graphe_des_imports(fichiers)
    assert g["hl_observer.b"] == {"src/hl_observer/a.py", "src/hl_observer/c.py"}


# ============================================================ UN AUDIT QUI MENT RASSURE
#
# LE BUG QUI RENDAIT CET OUTIL INUTILE, TROUVE EN LE LANCANT (2026-07-12).
#
# Ma 1re version SAUTAIT les imports relatifs (`if n.level: continue`). Sur le vrai depot elle
# a sorti **148 "orphelins"** -- dont `hl_observer.config`, evidemment importe partout.
#
# Un rapport de 148 lignes dont la plupart sont fausses ne se lit plus. Il rend le VRAI signal
# INVISIBLE. C'est exactement le peche que cet outil denonce : **un garde-fou qui ne garde
# rien.** Un audit qui ment est PIRE que pas d'audit -- il rassure.

def test_les_imports_RELATIFS_sont_resolus():
    """`from ..config import x` doit compter comme un import de `hl_observer.config`."""
    fichiers = {
        "src/hl_observer/config/reglages.py": "X = 1\n",
        "src/hl_observer/edge/calc.py": "from ..config.reglages import X\n",
        "src/hl_observer/edge/voisin.py": "from .calc import truc\n",
    }
    g = graphe_des_imports(fichiers)
    assert "src/hl_observer/edge/calc.py" in g.get("hl_observer.config.reglages", set()), (
        "`from ..config.reglages import X` n'a pas ete resolu : l'audit va declarer "
        "orphelin un module importe partout"
    )
    assert "src/hl_observer/edge/voisin.py" in g.get("hl_observer.edge.calc", set()), (
        "`from .calc import truc` (meme paquet) n'a pas ete resolu"
    )

    # (`voisin` n'est importe par personne : c'est un VRAI orphelin de mon fixture jouet.
    #  Mon 1er assert disait `orphelins == []` -- il accusait l'outil d'un bug qui etait le
    #  mien. Encore une fois : suspecter le FIXTURE avant le code.)
    #
    # 2e correction (12/07) : il a fallu AJOUTER `__main__`. Depuis que l'atteignabilite est
    # TRANSITIVE, « etre importe » ne suffit plus -- il faut etre importe par quelque chose de
    # joignable. Sans porte, ce fixture ne prouvait plus rien.
    avec_porte = dict(fichiers, **{"src/hl_observer/__main__.py": "from hl_observer.edge import calc\n"})
    v = auditer_les_modules(avec_porte)
    for m in ("hl_observer.config.reglages", "hl_observer.edge.calc"):
        assert m not in v.orphelins, (
            "%s est importe en RELATIF et a ete pris pour du code mort" % m
        )


def test_un_paquet___init___n_est_PAS_un_orphelin():
    """Un `__init__.py` EST le paquet : personne ne l'importe nommement. Le signaler noyait
    40 lignes de bruit dans le rapport -- et le bruit tue le signal."""
    fichiers = {
        "src/hl_observer/__main__.py": "from hl_observer.loops import b\n",
        "src/hl_observer/edge/__init__.py": "",
        "src/hl_observer/edge/calc.py": "X = 1\n",
        "src/hl_observer/loops/b.py": "from hl_observer.edge.calc import X\n",
    }
    v = auditer_les_modules(fichiers)
    assert "hl_observer.edge" not in v.orphelins, (
        "le paquet `edge` (son __init__.py) a ete pris pour du code mort : %r" % v.orphelins
    )
    assert "hl_observer.edge.calc" not in v.orphelins


def test_l_AST_voit_ce_qu_un_grep_rate():
    """`from x import (\\n a,\\n b)` sur plusieurs lignes : un grep naif le rate.
    Et un `import` dans un commentaire : un grep naif l'attrape a tort."""
    fichiers = {
        "src/hl_observer/a.py": (
            "# import hl_observer.PIEGE   <- un commentaire n'est PAS un import\n"
            "from hl_observer.vrai import (\n"
            "    machin,\n"
            "    truc,\n"
            ")\n"
        ),
        "src/hl_observer/vrai.py": "machin = truc = 1\n",
    }
    g = graphe_des_imports(fichiers)
    assert "hl_observer.vrai" in g
    assert "hl_observer.PIEGE" not in g, "un commentaire a ete pris pour un import"


# ============================================================ LE CAS delta_neutral_carry
#
# LE PLUS DANGEREUX DES TROIS, ET CELUI QUI NOUS A EUS.
#
# Un module PUR, TESTE, COMPLET, qui repond exactement a la bonne question... et a qui PERSONNE
# n'a jamais donne de donnees reelles. La suite de tests etait VERTE. Le module etait MORT.
#
# "Teste" et "branche" sont deux choses differentes. Un test ne cable rien.

def test_un_module_importe_UNIQUEMENT_par_les_tests_est_signale():
    fichiers = {
        "src/hl_observer/funding/delta_neutral_carry.py": "def evaluer(): ...\n",
        "tests/test_delta_neutral_carry.py":
            "from hl_observer.funding.delta_neutral_carry import evaluer\n",
        "src/hl_observer/cli.py": "print('rien')\n",
    }
    v = auditer_les_modules(fichiers)
    assert "hl_observer.funding.delta_neutral_carry" in v.testes_non_branches, (
        "un module que SEULS les tests importent est teste mais NON BRANCHE : la suite est "
        "verte et aucun chemin de production ne l'appelle"
    )
    assert "hl_observer.funding.delta_neutral_carry" not in v.orphelins, (
        "il n'est pas orphelin (les tests l'importent) -- c'est PIRE : il est rassurant"
    )


def test_un_module_branche_en_production_n_est_PAS_signale():
    """Symetrie : l'audit ne crie pas au loup. Un module appele par le code de prod est sain.

    NOTE (fixture corrigee le 12/07) : il a fallu ajouter `__main__` -- la porte. Sans elle,
    `boucle` n'est atteignable par rien, donc `calc` non plus, et l'audit avait RAISON de le
    signaler. La fixture d'origine supposait qu'« etre importe » suffisait. C'est precisement
    l'illusion que l'atteignabilite transitive dissipe.
    """
    fichiers = {
        "src/hl_observer/__main__.py": "from hl_observer.loops import boucle\n",
        "src/hl_observer/edge/calc.py": "def edge(): ...\n",
        "src/hl_observer/loops/boucle.py": "from hl_observer.edge.calc import edge\n",
        "tests/test_calc.py": "from hl_observer.edge.calc import edge\n",
    }
    v = auditer_les_modules(fichiers)
    assert "hl_observer.edge.calc" not in v.testes_non_branches
    assert "hl_observer.edge.calc" not in v.orphelins


def test_un_BOM_utf8_n_est_PAS_une_erreur_de_syntaxe():
    """3e BUG DE MON PROPRE AUDIT, trouve le jour meme ou j'ai pose le garde-fou.

    Mon « fichier illisible » a immediatement accuse `tests/test_testnet_mode_controlled.py` :

        SyntaxError : invalid non-printable character U+FEFF  (ligne 1, col 1)

    Le fichier est PARFAITEMENT valide. Python retire le BOM quand il lit un `.py` ; pytest
    l'importe sans broncher. C'est MOI qui decodais en `utf-8` au lieu de `utf-8-sig` et
    passais le BOM a `ast.parse`.

    Le garde-fou a bien fonctionne (il a refuse de conclure) -- mais il accusait un innocent.
    **Un audit qui crie au loup finit ignore le jour ou il a raison.**
    """
    src = "﻿from __future__ import annotations\nfrom hl_observer.edge import calc\n"
    fichiers = {
        "src/hl_observer/__main__.py": src,
        "src/hl_observer/edge/calc.py": "X = 1\n",
    }
    v = auditer_les_modules(fichiers)
    assert v.illisibles == [], "un BOM UTF-8 a ete pris pour une erreur de syntaxe : %r" % v.illisibles
    assert v.fiable is True
    # et le BOM ne doit pas non plus casser la lecture des imports :
    assert "hl_observer.edge.calc" not in v.orphelins
    assert "hl_observer.edge.calc" not in v.testes_non_branches


def test_un_fichier_ILLISIBLE_est_NOMME_et_le_verdict_se_declare_NON_FIABLE():
    """L'AUTO-DEFENSE DE L'AUDIT.

    `_importes_par` avale les SyntaxError. Un `cli.py` tronque par le mount n'importerait donc
    RIEN -- et l'audit declarerait tout le projet mort, avec aplomb. Il doit au contraire dire :
    « je n'ai pas pu lire ce fichier, ne me crois pas. »
    """
    fichiers = {
        "src/hl_observer/__main__.py": "from hl_observer import cli\n",
        "src/hl_observer/cli.py": "from hl_observer.moteur import (\n",   # tronque en plein vol
        "src/hl_observer/moteur.py": "def go(): ...\n",
    }
    v = auditer_les_modules(fichiers)
    assert "src/hl_observer/cli.py" in v.illisibles
    assert v.fiable is False, "un verdict bati sur un fichier illisible ne doit PAS etre opposable"
    assert v.as_dict()["fiable"] is False


def test_un_module_que_PERSONNE_n_importe_est_ORPHELIN():
    fichiers = {
        "src/hl_observer/vieux/mort.py": "def jamais_appele(): ...\n",
        "src/hl_observer/loops/boucle.py": "X = 1\n",
    }
    v = auditer_les_modules(fichiers)
    assert "hl_observer.vieux.mort" in v.orphelins


def test_les_points_d_entree_ne_sont_PAS_des_orphelins():
    """`__main__`, `cli`, `__init__` ne sont importes par personne -- et c'est NORMAL.
    Un audit qui les signale noie ses vraies trouvailles dans du bruit."""
    fichiers = {
        "src/hl_observer/__main__.py": "print('go')\n",
        "src/hl_observer/cli.py": "def main(): ...\n",
        "src/hl_observer/__init__.py": "",
    }
    v = auditer_les_modules(fichiers)
    assert v.orphelins == [], "les points d'entree ont ete pris pour du code mort : %r" % v.orphelins


# ============================================================ L'INTERRUPTEUR MORT
#
# LE BUG DU POLLER DE CARNET L2, MOT POUR MOT.
#
# Le code lisait `V26_BOOK_POLLER` avec un defaut a "0". AUCUN lanceur ne le posait. La capacite
# etait la, cablee, testee... et **eteinte pour toujours**, sans un log, sans une erreur.
# Pendant des semaines, `l2_book.jsonl` n'a pas existe -- et tout le market making etait
# intestable sans que personne ne le sache.

def test_un_flag_lu_avec_un_defaut_ETEINT_et_pose_par_PERSONNE_est_MORT():
    fichiers = {
        "src/hl_observer/collection/poller.py":
            'import os\nACTIF = os.environ.get("V26_BOOK_POLLER", "0") == "1"\n',
    }
    lanceurs = {"LANCER.cmd": 'set "AUTRE_CHOSE=1"\n'}          # il ne pose PAS le flag

    inters = auditer_les_interrupteurs(fichiers, lanceurs)
    i = next(x for x in inters if x.nom == "V26_BOOK_POLLER")
    assert i.defaut == "0"
    assert i.pose_par == ()
    assert i.mort is True, (
        "un flag lu avec un defaut eteint, que PERSONNE ne pose, est une capacite qui ne "
        "s'allumera JAMAIS. C'est exactement le bug du poller L2."
    )


def test_un_flag_POSE_par_un_lanceur_est_VIVANT():
    fichiers = {
        "src/hl_observer/collection/poller.py":
            'import os\nACTIF = os.environ.get("V26_BOOK_POLLER", "0") == "1"\n',
    }
    lanceurs = {"LANCER.cmd": 'set "V26_BOOK_POLLER=1"\n'}
    i = next(x for x in auditer_les_interrupteurs(fichiers, lanceurs)
             if x.nom == "V26_BOOK_POLLER")
    assert i.pose_par == ("LANCER.cmd",)
    assert i.mort is False


def test_un_flag_ALLUME_PAR_DEFAUT_n_est_pas_mort():
    """Symetrie : un defaut a "1" n'a besoin d'aucun lanceur. Il est deja allume."""
    fichiers = {"src/hl_observer/x.py": 'import os\nA = os.getenv("HYPERSMART_TRUC", "1")\n'}
    i = next(x for x in auditer_les_interrupteurs(fichiers, {}) if x.nom == "HYPERSMART_TRUC")
    assert i.mort is False


def test_un_defaut_VIDE_est_AMBIGU_et_ne_s_accuse_PAS():
    """SUR-INTERPRETATION QUE J'AI FAILLI COMMETTRE.

        HYPERSMART_TOP_WALLET_SAMPLE_LIMIT = ""   ->  "aucune limite" = PERMISSIF
        HYPERSMART_PNL_AUDIT_PREFER_APPEND_ONLY = ""  ->  falsy       = eteint

    Les deux s'ecrivent PAREIL. On ne peut pas trancher depuis le defaut seul -- alors on ne
    tranche PAS. Meme discipline que partout ailleurs : donnee ambigue, on n'affirme rien.
    """
    fichiers = {"src/hl_observer/cli.py":
                'import os\nA = os.environ.get("HYPERSMART_TOP_WALLET_SAMPLE_LIMIT", "")\n'}
    i = next(x for x in auditer_les_interrupteurs(fichiers, {})
             if x.nom == "HYPERSMART_TOP_WALLET_SAMPLE_LIMIT")
    assert i.mort is False, "un defaut VIDE peut vouloir dire 'aucune limite' : ne pas accuser"
    assert i.ambigu is True, "il doit tout de meme etre SIGNALE pour une lecture humaine"


def test_un_flag_SANS_defaut_lisible_n_affirme_RIEN():
    """DENY-BY-DEFAULT sur nos propres conclusions : sans defaut, on ne peut pas savoir si la
    capacite est eteinte. On se TAIT plutot que d'accuser a tort."""
    fichiers = {"src/hl_observer/x.py": 'import os\nA = os.environ.get("HYPERSMART_MYSTERE")\n'}
    i = next(x for x in auditer_les_interrupteurs(fichiers, {}) if x.nom == "HYPERSMART_MYSTERE")
    assert i.defaut is None
    assert i.mort is False, "sans defaut lisible, on n'affirme pas qu'il est mort"


def test_un_flag_pose_SEULEMENT_dans_un_test_ne_compte_PAS_comme_branche():
    """Un test qui pose HYPERSMART_X=1 ne l'allume pas en PRODUCTION. C'est exactement le piege
    qui a fait passer l'audit pour vert alors que la capacite etait morte au runtime."""
    fichiers = {
        "src/hl_observer/x.py": 'import os\nA = os.environ.get("HYPERSMART_Z", "0")\n',
        "tests/test_x.py": 'import os\nos.environ["HYPERSMART_Z"] = "1"\n',
    }
    i = next(x for x in auditer_les_interrupteurs(fichiers, {}) if x.nom == "HYPERSMART_Z")
    assert i.mort is True, "un flag allume seulement par un test reste MORT en production"


def test_le_pose_se_lit_dans_TOUTES_les_syntaxes():
    """RATER UNE SYNTAXE DE POSE, C'EST ACCUSER A TORT.

    Ma 1re regex ne connaissait que `set "X="`, `$env:X=` et `export X=`. Or le VRAI lanceur
    du projet utilise l'AUTRE syntaxe PowerShell :

        [Environment]::SetEnvironmentVariable("HYPERSMART_RECORD_MICROSTRUCTURE", "1", "Process")

    L'audit a donc declare MORTS **quatre flags parfaitement vivants** -- dont le recorder de
    microstructure et le fallback de mid, deux correctifs recents.

    Un audit qui crie au loup devient un bruit qu'on apprend a ignorer. Et le jour ou il a
    raison, plus personne ne l'ecoute.
    """
    poses = flags_poses({
        "a.cmd": 'set "HYPERSMART_A=1"\n',
        "b.ps1": '$env:HYPERSMART_B = "1"\n',
        "c.sh": 'export HYPERSMART_C=1\n',
        "d.ps1": '[Environment]::SetEnvironmentVariable("HYPERSMART_D", "1", "Process")\n',
        "e.py": 'os.environ["HYPERSMART_E"] = "1"\n',
        "f.py": 'os.environ.setdefault("HYPERSMART_F", "1")\n',
        "g.yaml": "HYPERSMART_G: 1\n",
    })
    manquants = {"HYPERSMART_%s" % c for c in "ABCDEFG"} - set(poses)
    assert not manquants, "syntaxe(s) de pose non reconnue(s) : %r -- l'audit accusera a tort" % manquants


def test_le_VRAI_lanceur_du_projet_est_reconnu():
    """Non-regression sur le cas exact qui m'a fait accuser 4 flags vivants."""
    fichiers = {"src/hl_observer/collection/microstructure_recorder.py":
                'import os\nA = os.environ.get("HYPERSMART_RECORD_MICROSTRUCTURE", "0")\n'}
    lanceurs = {"tools/start_hypersmart_simulation.ps1":
                '[Environment]::SetEnvironmentVariable('
                '"HYPERSMART_RECORD_MICROSTRUCTURE", "1", "Process")\n'}
    i = next(x for x in auditer_les_interrupteurs(fichiers, lanceurs)
             if x.nom == "HYPERSMART_RECORD_MICROSTRUCTURE")
    assert i.pose_par == ("tools/start_hypersmart_simulation.ps1",)
    assert i.mort is False, "le flag EST pose par le vrai lanceur -- le declarer mort est un mensonge"


def test_le_prefixe_filtre_les_flags_du_systeme():
    """PATH, HOME, PYTHONPATH ne sont pas NOS interrupteurs. Les lister, c'est noyer le signal."""
    fichiers = {"src/hl_observer/x.py":
                'import os\nA = os.environ.get("PATH", "")\nB = os.environ.get("HYPERSMART_K", "0")\n'}
    noms = [i.nom for i in auditer_les_interrupteurs(fichiers, {}, prefixes=("HYPERSMART_",))]
    assert noms == ["HYPERSMART_K"]


def test_deux_lectures_contradictoires_gardent_la_plus_PERMISSIVE():
    """Si un chemin lit le flag avec un defaut "0" et un autre avec "1", la capacite EST
    allumee quelque part : on ne doit pas crier "mort"."""
    fichiers = {
        "src/hl_observer/a.py": 'import os\nA = os.environ.get("HYPERSMART_D", "0")\n',
        "src/hl_observer/b.py": 'import os\nB = os.environ.get("HYPERSMART_D", "1")\n',
    }
    i = next(x for x in auditer_les_interrupteurs(fichiers, {}) if x.nom == "HYPERSMART_D")
    assert i.mort is False


def test_le_rapport_est_serialisable():
    v = auditer_les_modules({"src/hl_observer/mort.py": "x = 1\n"})
    d = v.as_dict()
    assert d["orphelins"] == ["hl_observer.mort"]
    assert d["real_execution"] is False


def test_flags_lus_ignore_un_get_de_dictionnaire_ordinaire():
    """`config.get("X", "0")` n'est PAS une variable d'environnement. Le confondre remplirait
    le rapport de faux positifs -- et un rapport bruyant ne se lit plus."""
    fichiers = {"src/hl_observer/x.py": 'cfg = {}\nA = cfg.get("HYPERSMART_FAUX", "0")\n'}
    assert "HYPERSMART_FAUX" not in flags_lus(fichiers)


def test_un_interrupteur_se_rend_en_dict():
    i = Interrupteur("X", "0", ("a.py",), ())
    assert i.as_dict()["mort"] is True
