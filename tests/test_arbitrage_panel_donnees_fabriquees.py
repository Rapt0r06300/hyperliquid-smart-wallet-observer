"""#145 — 🔴 le panneau d'arbitrage affichait un spread INVENTÉ sans le dire.

CE QU'ON A TROUVÉ (2026-07-13)
------------------------------
`refactor_fusion/runner.py:88` fait :

    arbitrage_results = (_fixture_arbitrage(),)

et `_fixture_arbitrage()` construit un carnet Hyperliquid à **100,00** et un carnet « CEX » à
**101,40** — **+140 bps de spread, écrits en dur**. Le panneau publiait `accepted: 1`.

Le mot « fixture » figurait bien quelque part : dans un champ `source`, enfoui dans
`spread.hyperliquid.source`. Autant dire nulle part.

Et la cause profonde : **aucun collecteur de prix CEX n'existe dans ce projet.** Le seul fichier
qui mentionne Binance/Bybit/OKX est la liste des paquets *interdits*. Ce scanner n'a donc jamais
rien pu mesurer de réel — il ne pouvait être nourri que de fiction.

> *« Aucune donnée fabriquée, aucune démo présentée comme réelle. »* — CLAUDE.md

Ce n'est pas un problème de malhonnêteté : c'est un problème de **mémoire**. Six mois plus tard,
« on avait trouvé 140 bps d'arbitrage » survit — et plus personne ne se souvient que c'était une
fixture.
"""

from __future__ import annotations

from hl_observer.arbitrage import OrderBookSnapshot, scan_hyperliquid_cex_spread
from hl_observer.dashboard.arbitrage_panel import build_arbitrage_panel

FRAIS = {"fee_bps": 6.0, "slippage_bps": 4.0, "latency_penalty_bps": 2.0, "funding_rate": 0.0}


def _opportunite(source_hl: str, source_cex: str):
    return scan_hyperliquid_cex_spread(
        hyperliquid_book=OrderBookSnapshot(source_hl, "HYPE-PERP", 99.90, 100.00, 200_000, 200_000),
        cex_book=OrderBookSnapshot(source_cex, "HYPE-USDT", 101.40, 101.60, 200_000, 200_000),
        **FRAIS,
    )


def test_une_ligne_FIXTURE_est_DECLAREE_comme_fabriquee():
    """🔴 L'INVARIANT. Un prix inventé doit être annoncé comme tel, en haut, en toutes lettres."""
    panneau = build_arbitrage_panel([_opportunite("fixture:hyperliquid", "fixture:cex")])

    assert panneau["donnees_fabriquees"] is True
    assert panneau["n_lignes_fabriquees"] == 1
    assert "DONNEES FABRIQUEES" in panneau["avertissement"]
    assert "INVENTE" in panneau["avertissement"]


def test_un_ACCEPT_sur_de_la_FICTION_ne_compte_pas_comme_une_vraie_acceptation():
    """+140 bps de spread inventé produisent un `ACCEPT`. Il ne doit pas passer pour un résultat.

    `accepted_reels` vaut 0 tant qu'aucun prix CEX n'est réellement collecté — c'est-à-dire :
    toujours, aujourd'hui.
    """
    panneau = build_arbitrage_panel([_opportunite("fixture:hyperliquid", "fixture:cex")])
    assert panneau["accepted_reels"] == 0, (
        "une opportunite construite sur des prix inventes est comptee comme une VRAIE acceptation"
    )


def test_le_detecteur_ne_crie_pas_AU_LOUP_sur_des_sources_reelles():
    """Un faux positif coûte aussi cher qu'un faux négatif : il apprend à ignorer l'avertissement."""
    panneau = build_arbitrage_panel([_opportunite("hyperliquid:l2Book", "binance:depth")])

    assert panneau["donnees_fabriquees"] is False
    assert "avertissement" not in panneau
    assert panneau["n_lignes_reelles"] == 1


def test_le_RUNNER_de_refactor_fusion_est_bien_celui_qui_fabrique():
    """On nomme le coupable, pour qu'il ne se cache pas derrière une abstraction.

    Tant que ce test PASSE, c'est que le runner alimente encore le panneau avec des fixtures —
    et donc que #145 reste BLOQUÉE sur des données qu'on ne collecte pas. Le jour où un vrai
    collecteur CEX existera, ce test échouera : ce sera le signal que la situation a changé,
    et il faudra alors le mettre à jour EN CONNAISSANCE DE CAUSE.
    """
    from hl_observer.refactor_fusion.runner import _fixture_arbitrage

    panneau = build_arbitrage_panel([_fixture_arbitrage()])
    assert panneau["donnees_fabriquees"] is True, (
        "le runner ne fabrique plus ses prix : un vrai collecteur CEX existe-t-il enfin ? "
        "Si oui, tant mieux -- et il faut mettre a jour #145 (et ce test)."
    )
