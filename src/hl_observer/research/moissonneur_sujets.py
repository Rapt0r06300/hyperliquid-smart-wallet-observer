r"""LES SUJETS ET LES REQUÊTES — *la surface de recherche, en un seul endroit.*

*Une liste dupliquée dans trois fichiers finit par diverger dans trois directions.*
(C'est ce qui est arrivé au nombre de frais : **6 fichiers, 4 valeurs**, dont un **2,5 bps
inexistant** chez Hyperliquid.)

PUR : des listes. Aucun réseau.
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LES SUJETS (topics GitHub).
# ═══════════════════════════════════════════════════════════════════════════════════════════════
SUJETS: list[str] = [
    # --- notre venue et ses voisines
    "hyperliquid", "hyperliquid-bot", "hyperliquid-sdk", "perp-dex", "perpetual-futures",
    "perpetuals", "dydx", "gmx", "drift-protocol", "vertex-protocol", "aevo", "paradex",
    # --- les stratégies qui nous concernent
    "funding-rate-arbitrage", "funding-rate", "basis-trading", "delta-neutral",
    "market-neutral", "statistical-arbitrage", "pairs-trading", "cointegration",
    "triangular-arbitrage", "cross-exchange-arbitrage", "crypto-arbitrage",
    "carry-trade", "cash-and-carry",
    # --- market making et microstructure
    "market-making", "market-maker", "market-maker-bot", "avellaneda-stoikov",
    "market-microstructure", "order-book", "orderbook", "orderflow", "order-flow-imbalance",
    "limit-order-book", "matching-engine", "queue-position", "microprice",
    # --- haute fréquence et exécution
    "high-frequency-trading", "hft", "low-latency-trading", "algorithmic-trading",
    "execution-algorithms", "smart-order-routing", "vwap", "twap", "market-impact",
    # --- validation : là où on a le plus péché
    "backtesting", "backtesting-engine", "backtest", "walk-forward", "cross-validation",
    "quantitative-finance", "quantitative-trading", "quant", "alpha-research",
    "overfitting", "purged-cross-validation",
    # --- le flux pré-exécution
    "mev", "mempool", "front-running", "liquidation-bot", "liquidations",
    # --- les cartes au trésor
    "awesome-quant", "awesome-trading",
]

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LE TEXTE LIBRE — *beaucoup d'excellents repos n'ont AUCUN topic.*
# Les chercher par topic seul, **c'est les rater**.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
TEXTE: list[str] = [
    "hyperliquid market maker", "hyperliquid arbitrage", "hyperliquid funding",
    "hyperliquid liquidation", "hyperliquid mempool", "hyperliquid node",
    "hyperliquid python sdk", "hyperliquid rust",
    "perpetual funding arbitrage bot", "delta neutral funding bot",
    "queue position backtest", "adverse selection market making",
    "limit order book simulator", "market impact model crypto",
    "orderbook imbalance signal", "maker taker fee optimizer",
    "cash and carry crypto", "basis trade perpetual",
    "liquidation cascade detection", "forced liquidation flow",
    "kappa fill intensity estimation", "order arrival intensity",
    "markout post trade drift", "toxic flow detection",
    "walk forward optimization crypto", "deflated sharpe ratio",
    "backtest live divergence", "paper trading ledger",
    # 🌐 LES CARTES AU TRÉSOR — *200 repos sans aucun topic*
    "awesome quant", "awesome market making", "awesome algorithmic trading",
    "awesome high frequency trading", "awesome crypto trading bots",
]

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔑 LA CARTE DES DOMAINES — *branchée ici pour que TOUT le moissonneur en profite.*
#
# Flo : *« 14 catégories, c'est trop peu »*. Il avait raison, et la faute n'était pas le NOMBRE :
#
#     ***Mes 14 catégories couvraient le côté ALPHA (comment gagner). Elles ne couvraient presque
#        RIEN du côté SURVIE (comment ne pas mourir), ni la MÉCANIQUE de l'exchange.***
#
# 🔴 Et en refaisant cette carte, j'ai trouvé **un trou dans NOTRE bot : le LEG RISK.**
#    *Notre carry a **deux jambes**. Si le spot passe et pas le perp — **on est À NU**.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
from hl_observer.research.domaines import (  # noqa: E402
    tous_les_sujets,
    toutes_les_requetes,
)

for _s in tous_les_sujets():
    if _s not in SUJETS:
        SUJETS.append(_s)

for _q, _d, _p in toutes_les_requetes():
    if _q not in TEXTE:
        TEXTE.append(_q)

__all__ = ["SUJETS", "TEXTE"]
