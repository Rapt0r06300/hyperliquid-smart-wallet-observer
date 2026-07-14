"""LES PIERRES TOMBALES DE `backtesting/` — #166/#169/#240/#241 (2026-07-13).

Meme doctrine que T3b (risk/), T3c (paper_trading/), T3e (runtime/) : **BRANCHER OU ENTERRER,
rien entre les deux.** Mais avec une nouveaute qui change la methode.

🔴 LA CLASSE QUE MES AUDITS PRECEDENTS NE POUVAIENT PAS VOIR : LE LIMBE AU NIVEAU DE LA FONCTION
==============================================================================================
T3b/T3c/T3e raisonnaient **par MODULE** : « ce fichier est-il importe par la production ? ».
Ici, la reponse est OUI... et elle ne suffit pas.

    backtesting/regime_detection.py   ->  IMPORTE par regime_label -> regime_wiring
                                                              -> scenario_search  (VIVANT)

Mais le module contient **QUATRE fonctions**, et une SEULE est appelee :

    garch11_variance_causale   VIVANTE   <- regime_label / regime_wiring / scenario_search
    garch11_variance           MORTE     <- et elle **LIT LE FUTUR** (mesure du 13/07)
    kalman_filter_1d           MORTE     <- IDEA-83, jamais appelee
    cusum_change_points        MORTE     <- IDEA-82, marquee « completed »... a tort

*Un module VIVANT peut heberger des fonctions MORTES -- et l'une d'elles peut etre DANGEREUSE.*

🚩 ET LA TASKLIST SE TROMPAIT : #241 disait « GARCH est CODE mais MORT ». **FAUX.** Le GARCH
**causal** est branche depuis #595 et il tourne dans `scenario_search`. Ce qui est mort, c'est son
**JUMEAU QUI FUIT** -- a un import de distance, une lettre d'ecart, dans le meme fichier.

    from ... import garch11_variance_causale   # le bon
    from ... import garch11_variance           # le meme nom, moins 8 caracteres, et il triche

C'est la definition d'une mine. Un jour, quelqu'un (ou moi) laissera l'autocompletion choisir --
et il y aura du **lookahead dans le moteur de recherche**, silencieusement. D'ou l'invariant de
`tests/test_backtesting_no_limbo.py` : *la production ne peut PAS importer `garch11_variance`.*

LES DECISIONS
-------------
  * `kalman_filter_1d`     -> ENTERRE. Redondant : le regime est deja etabli, causalement, par
                              `garch11_variance_causale` (branche, teste, mesure).
  * `garch11_variance`     -> ENTERRE, et **VERROUILLE** : il lit le futur. Le brancher mettrait
                              du lookahead dans le garde-fou anti-lookahead.
  * `cusum_change_points`  -> ENTERRE. Aucun consommateur ; IDEA-82 etait un statut faux de plus.
  * `ml_diagnostics` (SHAP)-> ENTERRE. Il EXPLIQUE un modele qui PERD contre la baseline (P13).
                              Expliquer une perte ne la transforme pas en gain.
  * `microstructure_extras`
    (Hawkes)               -> ENTERRE. Aucun consommateur de flux d'evenements : le seul chemin
                              qui en voudrait (cascades de liquidations) est BLOQUE faute de
                              donnee (IMPROVE-36 / X-11).

« ENTERRE » = le fichier reste sur le disque, sous git (CLAUDE.md : « ne rien supprimer
brutalement »). Ca veut dire : **aucun chemin de production ne l'appelle, et c'est TESTE.**

Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TombeBacktesting:
    cible: str            # "module:nom" ou "fonction:nom"
    motif: str            # LOOKAHEAD_PROUVE | REDONDANT | PAS_DE_CONSOMMATEUR | EXPLIQUE_UNE_PERTE
    pourquoi: str         # une phrase qu'on peut CONTREDIRE (un fait, pas une etiquette)
    preuve: str           # ou verifier, en une ligne
    reouverture: str      # ce qui, precisement, la ferait revivre


TOMBES_BACKTESTING: tuple[TombeBacktesting, ...] = (
    # ------------------------------------------------------------------ LA MINE
    TombeBacktesting(
        cible="fonction:garch11_variance",
        motif="LOOKAHEAD_PROUVE",
        pourquoi=(
            "elle lit le futur DEUX FOIS : elle s'amorce sur la variance de TOUTE la serie (donc "
            "sur des rendements qui n'existent pas encore a l'instant t), et out[i] connait r[i]. "
            "La brancher mettrait du lookahead DANS le garde-fou anti-lookahead"
        ),
        preuve="mesure du 2026-07-13 (IMPROVE-20) ; remplacee par garch11_variance_causale (#595)",
        reouverture=(
            "JAMAIS en l'etat. Seule une reecriture causale (amorcage sur le passe seul, out[i] "
            "ignorant r[i]) pourrait revivre -- et elle existe deja : c'est la version _causale"
        ),
    ),
    # ------------------------------------------------------------------ LES REDONDANTS
    TombeBacktesting(
        cible="fonction:kalman_filter_1d",
        motif="REDONDANT",
        pourquoi=(
            "IDEA-83. Zero appelant de production. Le regime de volatilite est deja etabli, de "
            "facon CAUSALE et TESTEE, par garch11_variance_causale, branche dans scenario_search"
        ),
        preuve="tools/qui_appelle_backtesting.py : importe par PERSONNE (AST, pas un grep)",
        reouverture=(
            "une mesure montrant qu'un etat latent Kalman separe des regimes que le GARCH causal "
            "confond, ET que cette separation change une decision (>= 5 bps, le seuil qui tranche)"
        ),
    ),
    TombeBacktesting(
        cible="fonction:cusum_change_points",
        motif="PAS_DE_CONSOMMATEUR",
        pourquoi=(
            "IDEA-82, marquee « completed »... alors qu'aucun chemin de production ne l'appelle. "
            "C'est un 7e statut faux, trouve par le meme invariant"
        ),
        preuve="tools/qui_appelle_backtesting.py : importe par PERSONNE",
        reouverture="un consommateur reel de ruptures de regime, avec un test qui prouve l'appel",
    ),
    # ------------------------------------------------------------------ LES MODULES MORTS
    TombeBacktesting(
        cible="module:ml_diagnostics",
        motif="EXPLIQUE_UNE_PERTE",
        pourquoi=(
            "IDEA-09 (SHAP). Il explique les decisions d'un modele qui, mesure, PERD contre la "
            "baseline (P13 : la promotion du modele IA est bloquee pour cette raison). Expliquer "
            "une perte ne la transforme pas en gain"
        ),
        preuve="P13 (#300) + tools/qui_appelle_backtesting.py : 0 import de production",
        reouverture=(
            "un modele qui BAT la baseline hors echantillon. A ce moment-la, et seulement la, "
            "savoir POURQUOI il gagne devient utile"
        ),
    ),
    TombeBacktesting(
        cible="module:microstructure_extras",
        motif="PAS_DE_CONSOMMATEUR",
        pourquoi=(
            "IDEA-12 (Hawkes). Un processus auto-excitant modelise des CASCADES d'evenements -- "
            "mais le seul chemin qui en voudrait (les cascades de liquidations) est BLOQUE faute "
            "de donnee : on ne collecte pas les liquidations (IMPROVE-36 / X-11)"
        ),
        preuve="IMPROVE-36 (#143, bloquee) + 0 import de production",
        reouverture=(
            "le jour ou les liquidations sont REELLEMENT collectees (X-11), Hawkes redevient le "
            "bon outil pour mesurer leur auto-excitation. Pas avant : sans donnee, il n'a rien a "
            "modeliser"
        ),
    ),
)

# La production ne doit JAMAIS importer ces symboles.
FONCTIONS_ENTERREES: frozenset[str] = frozenset(
    t.cible.split(":", 1)[1] for t in TOMBES_BACKTESTING if t.cible.startswith("fonction:")
)
MODULES_ENTERRES_BACKTESTING: frozenset[str] = frozenset(
    t.cible.split(":", 1)[1] for t in TOMBES_BACKTESTING if t.cible.startswith("module:")
)

# 🔴 Celle-ci n'est pas seulement morte : elle est DANGEREUSE. Un test dedie la verrouille.
FONCTION_QUI_LIT_LE_FUTUR = "garch11_variance"

__all__ = [
    "FONCTIONS_ENTERREES", "FONCTION_QUI_LIT_LE_FUTUR", "MODULES_ENTERRES_BACKTESTING",
    "TOMBES_BACKTESTING", "TombeBacktesting",
]
