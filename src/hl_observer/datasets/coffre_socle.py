"""Socle du certificateur : familles, décisions et petites validations pures.

Partagé par ``coffre_certifie`` et les modules de familles ; ne dépend d'aucun d'eux.
"""
from __future__ import annotations

import math
from typing import Any


try:  # réutilise la normalisation canonique du symbole (déjà éprouvée)
    from hl_observer.normalization.instrument_identity import (
        preserve_native_instrument_symbol as _canonical_coin,
    )
except Exception:  # pragma: no cover - repli robuste (ne jamais planter l'import)
    def _canonical_coin(value: Any) -> str:
        return str(value or "").strip()

# Fraîcheur causale carnet<->réception (même borne que le book_loader SAFE).
try:
    from hl_observer.backtesting.copy_vault_book_loader import MAX_TARGET_LAG_MS
except Exception:  # pragma: no cover
    MAX_TARGET_LAG_MS = 60_000


#: Familles reconnues. La valeur est le préfixe de nom de fichier caractéristique.
FAMILLE_FILLS_FORWARD = "fills_forward"   # LIVE_POLL + LIVE_WS + LIVE_TWAP (causaux)
FAMILLE_FILLS_BACKFILL = "fills_backfill"  # REST backfill + NODE_FILLS (mesure, non causal)
FAMILLE_BOOK_L2 = "book_l2"                # carnets L2 copy-vault
FAMILLE_BBO = "bbo"                        # BBO / trades venues (repli)
FAMILLE_SNAPSHOT = "snapshot"             # snapshots vault
FAMILLE_TRADES = "trades_marche"          # trades marché publics (exécution réaliste)
FAMILLE_CANDLE = "candle"                 # bougies OHLCV (volatilité)
FAMILLE_POSITION = "position"             # positions leaders (clearinghouseState)
FAMILLE_ALLMIDS = "allmids"               # prix allMids tous-coins (contexte d'exécution)
FAMILLE_ASSET_CTX = "asset_ctx"           # OI / funding / mark / oracle / premium par coin
FAMILLE_LIQUIDATION = "liquidation"       # liquidations confirmées (événements réels)
FAMILLE_OVERSHOOT = "overshoot"           # overshoots oracle↔mid + réversion mesurée
FAMILLE_VENUE = "venue_book"              # carnet cross-venue (HL vs Binance, top-of-book)
FAMILLE_DISPERSION = "venue_dispersion"   # dispersion de prix cross-venue (bps)
FAMILLE_EXPLORER_TX = "explorer_tx"       # transactions observées sur l'explorer (activité de tous)
FAMILLE_VAULT_LEDGER = "vault_ledger"     # dépôts / retraits des vaults (flux de capital)
FAMILLE_MICRO_BBO = "micro_bbo"           # BBO Hyperliquid dense (WS public, séquence + checksum)
FAMILLE_MICRO_L2 = "micro_l2"             # carnets L2 Hyperliquid pleine profondeur (WS public)
FAMILLE_MICRO_TRADES = "micro_trades"     # transactions Hyperliquid (WS public)

#: Sources JAMAIS certifiables : données ESTIMÉES/inférées (non observées directement).
#: Elles ne doivent JAMAIS entrer dans le coffre comme du SAFE — intégrité du labo.
#: Reconnues par la sous-chaîne (comparaison en majuscules).
SOURCES_NON_CERTIFIABLES = ("INFERRED", "ESTIM", "SHADOW", "RECONSTRUIT")


def _source_certifiable(record: Any) -> bool:
    """False si l'enregistrement est une estimation/inférence (jamais SAFE)."""
    if isinstance(record, dict):
        if record.get("certifie") is False or record.get("inferred") is True:
            return False
        src = str(record.get("source") or "").upper()
        if any(marqueur in src for marqueur in SOURCES_NON_CERTIFIABLES):
            return False
    return True

# Décisions de certification (ordre = gravité croissante côté « non déposé »).
PASS = "PASS"              # valide tel quel -> déposé
REPARE = "REPARE"          # réparé (champ dérivé/normalisé) -> déposé
QUARANTAINE = "QUARANTAINE"  # irréparable -> NON déposé, mis de côté avec raison

#: tolérance de « futur » d'horloge (ms) : un léger dépassement n'est pas causal-faux.
_FUTUR_TOLERANCE_MS = 5_000


def _nombre_fini(value: Any) -> float | None:
    """Convertit en float fini > rien ; accepte str/num. None si impossible."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _entier_positif(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        i = int(value)
    except (TypeError, ValueError):
        return None
    return i if i > 0 else None


_SIDE_ACHAT = {"b", "buy", "bid", "long", "a_buy"}
_SIDE_VENTE = {"a", "s", "sell", "ask", "short"}


def _signe_depuis_side(value: Any) -> int | None:
    """+1 (achat) / -1 (vente) depuis un champ ``side``/``fill_side``/``dir`` libre."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in _SIDE_ACHAT or s.startswith(("open long", "close short", "buy")):
        return 1
    if s in _SIDE_VENTE or s.startswith(("open short", "close long", "sell")):
        return -1
    return None


def _niveaux(side: Any, *, descendant: bool) -> list[list[float]] | None:
    if not isinstance(side, list) or not side:
        return None
    sortie: list[list[float]] = []
    precedent: float | None = None
    for entree in side[:5]:
        px = sz = None
        if isinstance(entree, dict):
            px, sz = _nombre_fini(entree.get("px")), _nombre_fini(entree.get("sz"))
        elif isinstance(entree, (list, tuple)) and len(entree) >= 2:
            px, sz = _nombre_fini(entree[0]), _nombre_fini(entree[1])
        if px is None or sz is None or px <= 0 or sz <= 0:
            return None
        if precedent is not None and ((px >= precedent) if descendant else (px <= precedent)):
            return None
        sortie.append([px, sz])
        precedent = px
    return sortie or None


def _adresse(value: Any) -> str | None:
    texte = str(value or "").strip().lower()
    return texte if texte.startswith("0x") and len(texte) >= 10 else None
