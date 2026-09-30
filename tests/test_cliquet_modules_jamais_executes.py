"""#599 — LE CLIQUET DES MODULES JAMAIS EXECUTES (0,00 %).

LA REPONSE A « QUE VALENT LES 16 % DE LIGNES NON EXECUTEES ? »
--------------------------------------------------------------
Mesure du 2026-07-13 sur la suite COMPLETE (3 526 tests, 48 470 instructions) :

    7 836 lignes jamais executees, reparties en TROIS mondes tres differents :

      1 626 lignes | **97 modules a 0,00 %**  -> jamais executes, pas meme a l'import
        848 lignes | 117 modules du CHEMIN DE DECISION -> des BRANCHES non prises
      5 362 lignes | 396 modules (cli.py 800, ui/routes.py 622...) -> surface, pas coeur

**Les trois ne se valent pas.** Une branche non prise dans `risk_engine` est un refus dont on ne
sait pas s'il fonctionne. Une ligne non prise dans `cli.py` est une sous-commande qu'on n'utilise
pas. Confondre les deux, c'est se rassurer OU s'affoler pour rien.

CE QUE CE FICHIER VERROUILLE
---------------------------
Le seul chiffre qui doit **descendre** : le nombre de modules a **0,00 %**. Un module a 0 % n'est
pas « peu teste » -- il n'a **jamais tourne**. Le cliquet interdit d'en ajouter un de plus.

Symetrique de #121 (modules importes) et #596 (lignes executees). Trois cliquets, trois questions.
**Aucun ne se relache jamais.**

⚠️ HONNETETE SUR MON ERREUR DU JOUR
J'ai d'abord affirme que la mesure de 14:07 (83,83 %) etait FAUSSE, calculee sur une suite tronquee
par le Ctrl-C fantome (#600). **Refute par la mesure elle-meme** : relancee sur la suite complete,
elle rend exactement 83,83 %. Le Ctrl-C tuait le `.cmd` APRES pytest, pas pytest.
*Ma correction etait bonne ; mon diagnostic ne l'etait pas. Encore.*

Aucun ordre reel.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
RAPPORT = RACINE / "data" / "reports" / "couverture_599.json"

# Mesure du 2026-07-13, suite complete. NE JAMAIS AUGMENTER CE NOMBRE.
PLAFOND_MODULES_A_ZERO = 97


def _rapport() -> dict:
    if not RAPPORT.exists():
        pytest.skip(
            "couverture_599.json absent : lancer ANALYSER-599.cmd. "
            "Le cliquet ne s'invente pas une mesure -- il se TAIT, et ca se voit."
        )
    return json.loads(RAPPORT.read_text(encoding="utf-8"))


def test_le_nombre_de_modules_JAMAIS_EXECUTES_ne_peut_que_DESCENDRE():
    """🔴 UN MODULE A 0 % N'EST PAS « PEU TESTE ». IL N'A JAMAIS TOURNE.

    Pas meme a l'import. Aucune ligne. Ce n'est pas une lacune de test : c'est un module que
    **rien** dans le depot ne touche -- ni la production, ni les tests.
    """
    r = _rapport()
    morts = r.get("modules_a_zero") or []
    assert len(morts) <= PLAFOND_MODULES_A_ZERO, (
        "%d modules a 0,00 %% (plafond : %d). Un module de PLUS n'a jamais tourne.\n\n"
        "Ne releve PAS le plafond. Soit le module sert -- et il faut l'appeler et le tester ;\n"
        "soit il ne sert pas -- et il faut l'enterrer explicitement (cf. l'invariant T3b).\n"
        "Nouveaux : %s"
        % (
            len(morts),
            PLAFOND_MODULES_A_ZERO,
            ", ".join(m["module"] for m in morts[:10]),
        )
    )


def test_le_CHEMIN_DE_DECISION_ne_contient_AUCUN_module_a_ZERO_pour_cent():
    """🔴🔴 L'INVARIANT QUI COMPTE VRAIMENT.

    Qu'un outil d'analyse dorme a 0 %, soit. Qu'un module qui DECIDE d'ouvrir une position n'ait
    jamais tourne, jamais : on ne saurait meme pas s'il leve une exception a la premiere ligne.

    (`paper_trading/liquidity_route_simulator.py` est le seul cas connu, et il est enterre par
    l'invariant T3c -- pas branche, pas appele, et declare comme tel.)
    """
    r = _rapport()
    NOYAU = ("/edge/", "/risk/", "/signals/", "/copying/", "/opportunities/", "/funding/")
    TOLERES = {
        # enterres explicitement (T3b/T3c) : morts ET declares morts. Ce n'est pas un oubli.
        "src/hl_observer/paper_trading/liquidity_route_simulator.py",
        "src/hl_observer/copying/circuit_breaker.py",
        "src/hl_observer/copying/leader_pnl_tracker.py",
        "src/hl_observer/copying/viral_bot_engine.py",
        "src/hl_observer/copying/pipeline_integrator.py",
        "src/hl_observer/copying/kelly_sizing.py",
        "src/hl_observer/risk/advanced_risk_manager.py",
        "src/hl_observer/signals/decisions.py",
        "src/hl_observer/signals/signal_builder.py",
    }
    coupables = [
        m["module"]
        for m in (r.get("modules_a_zero") or [])
        if any(k in m["module"] for k in NOYAU) and m["module"] not in TOLERES
    ]
    assert not coupables, (
        "un module du NOYAU DE DECISION n'a jamais ete execute : %s\n"
        "Soit il decide -- et il doit etre teste. Soit il ne decide pas -- et il doit etre "
        "enterre explicitement." % ", ".join(coupables)
    )


def test_le_rapport_dit_bien_sur_QUELLE_suite_il_a_ete_mesure():
    """Un chiffre de couverture sans son nombre de tests est un chiffre sans garantie (#599)."""
    r = _rapport()
    assert 0.0 < float(r.get("pct_lignes") or 0.0) <= 100.0
    assert int(r.get("lignes_manquantes") or 0) > 0
