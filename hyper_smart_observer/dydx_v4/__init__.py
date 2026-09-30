"""
dYdX v4 module — HyperSmart Observer.

READ-ONLY / PAPER-ONLY / TESTNET-FIRST / DENY-BY-DEFAULT.
Aucun ordre réel, aucune clé privée, aucune signature, aucun dépôt/retrait.

Architecture:
    config          — paramètres sûrs par défaut
    safety          — gates de sécurité globales
    models          — modèles normalisés internes
    normalizer      — normalisation des données brutes dYdX
    rest_client     — client REST Indexer dYdX v4
    ws_client       — client WebSocket Indexer dYdX v4
    storage         — stockage SQLite (WAL, busy_timeout, déduplication)
    indexer         — indexer relançable (backfill + streaming)
    lifecycle       — moteur lifecycle OPEN/ADD/REDUCE/CLOSE/FLIP
    scoring         — scoring account/subaccount
    signals         — moteur de signaux (candidats seulement)
    no_trade        — moteur de refus avec journalisation
    paper           — simulateur paper USDC (jamais de vrais ordres)
    backtest        — backtest/replay séparé du PnL LIVE
    cli             — CLI dYdX
    dashboard_adapter — adaptateur dashboard read-only
"""

from __future__ import annotations

__version__ = "0.1.0"
__exchange__ = "dydx_v4"
__safety__ = "READ_ONLY|PAPER_ONLY|TESTNET_FIRST|DENY_BY_DEFAULT"
