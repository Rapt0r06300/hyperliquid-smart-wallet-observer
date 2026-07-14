from __future__ import annotations

import json
from typing import Any

from hl_observer.arbitrage.hyperliquid_cex_spread_scanner import CrossExchangeOpportunity

#: Jetons qui trahissent une donnee FABRIQUEE. Si l'un d'eux apparait dans une ligne, le panneau
#: doit le CRIER -- pas le murmurer dans un champ `source` enfoui a trois niveaux de profondeur.
JETONS_FABRIQUES = ("fixture", "mock", "demo", "sample", "dummy", "fake")

AVERTISSEMENT = (
    "DONNEES FABRIQUEES -- ces prix ne viennent d'AUCUN marche reel. "
    "Aucun collecteur CEX n'existe dans ce projet : le spread affiche est INVENTE. "
    "Ne jamais le lire comme une opportunite, ni le citer comme un resultat."
)


def _est_fabriquee(ligne: dict[str, Any]) -> bool:
    """On cherche les jetons dans la ligne SERIALISEE, pas dans un champ precis.

    Pourquoi : le `source` d'un carnet est enfoui dans `spread.hyperliquid.source`. Un lecteur
    presse ne le verra jamais. Et si la structure change demain, un controle couple a un chemin
    exact casserait en silence -- alors qu'une recherche sur le texte serialise, elle, tient.
    """
    texte = json.dumps(ligne, default=str).lower()
    return any(jeton in texte for jeton in JETONS_FABRIQUES)


def build_arbitrage_panel(opportunities: list[CrossExchangeOpportunity]) -> dict[str, Any]:
    """🔴 CORRIGE le 2026-07-13 (#145) — CE PANNEAU AFFICHAIT UN ARBITRAGE INVENTE.

    Ce qu'on a trouve : `refactor_fusion/runner.py` appelle `_fixture_arbitrage()`, qui construit
    un carnet Hyperliquid a 100,00 et un carnet « CEX » a 101,40 -- **+140 bps de spread, ecrits
    en dur**. Le panneau publiait alors `accepted: 1` sans jamais dire que les prix etaient
    inventes. Le mot « fixture » existait bien... dans un champ `source` enfoui, que personne ne lit.

    Et la cause profonde : **il n'existe AUCUN collecteur de prix CEX dans tout le projet.**
    (Le seul fichier qui mentionne Binance/Bybit/OKX est la liste des paquets INTERDITS.)
    Ce scanner n'a donc jamais rien pu mesurer de reel -- il ne pouvait etre nourri que de fiction.

    La regle du projet est explicite : *« Aucune donnee fabriquee, aucune demo presentee comme
    reelle. »* Un chiffre invente qui s'affiche a cote de chiffres reels finit toujours par etre
    cite comme s'il etait reel -- pas par malhonnetete, mais parce que six mois plus tard, plus
    personne ne se souvient lequel etait lequel.

    Le panneau DECLARE donc desormais ses donnees fabriquees, en haut, en toutes lettres.
    """
    rows = [item.as_dict() for item in opportunities]
    fabriquees = [ligne for ligne in rows if _est_fabriquee(ligne)]

    panneau: dict[str, Any] = {
        "title": "Cross-source paper arbitrage",
        "accepted": sum(1 for item in opportunities if item.decision == "ACCEPT_PAPER_ARBITRAGE"),
        "no_trade": sum(1 for item in opportunities if item.decision != "ACCEPT_PAPER_ARBITRAGE"),
        "rows": rows,
        "paper_only": True,
        "real_execution": False,
        # VERITE DES DONNEES : on DIT d'ou viennent les prix. Toujours. Meme quand c'est genant.
        "donnees_fabriquees": bool(fabriquees),
        "n_lignes_fabriquees": len(fabriquees),
        "n_lignes_reelles": len(rows) - len(fabriquees),
    }
    if fabriquees:
        panneau["avertissement"] = AVERTISSEMENT
        # Un `accepted` calcule sur de la fiction n'est pas un `accepted`. On expose donc le
        # decompte des acceptations REELLES -- qui vaut zero tant qu'aucun prix CEX n'est collecte.
        panneau["accepted_reels"] = sum(
            1
            for item, ligne in zip(opportunities, rows)
            if item.decision == "ACCEPT_PAPER_ARBITRAGE" and not _est_fabriquee(ligne)
        )
    return panneau


__all__ = ["AVERTISSEMENT", "JETONS_FABRIQUES", "build_arbitrage_panel"]
