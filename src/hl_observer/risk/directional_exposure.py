"""Garde-fou d'exposition DIRECTIONNELLE et de CONCENTRATION (2026-07-11).

POURQUOI CE MODULE EXISTE. Une session live a ete observee avec **9 positions ouvertes, presque
toutes SHORT**, pour ~4 500 $ de notionnel sur 1 000 $ de capital. Le garde-fou de portefeuille
existant (`_portfolio_open_refusal`) ne regardait que l'exposition **BRUTE** : il additionne des
`abs()`, donc 6 shorts et 1 long lui paraissent aussi diversifies que 7 paris opposes. Or ce n'est
pas un portefeuille : c'est **le meme pari, repete 9 fois**.

Consequence mesuree sur le run precedent : **97 % de la perte venait des shorts** (-62,63 $ contre
-1,36 $ pour les longs), parce que le book etait short a 73 % dans un marche haussier. Un mouvement
de +1 % du marche fait alors perdre 2,5 % du capital d'un coup, sur toutes les positions a la fois.

Ce module ajoute les deux limites qui manquaient :
  1. **exposition NETTE directionnelle** : |somme signee des notionnels| plafonnee en % du capital ;
  2. **concentration par COIN** : on ne peut pas empiler N positions sur le meme marche.

Il ne PREDIT rien et ne cherche pas a gagner : il empeche de tout perdre sur un seul pari.
Pur, sans I/O, sans effet de bord. Paper-only. Aucun ordre.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# % du capital autorise en exposition NETTE directionnelle (100 % = 1x le capital)
NET_EXPOSURE_PCT_ENV = "HYPERSMART_MAX_NET_DIRECTIONAL_PCT"
# notionnel maximum cumule sur UN SEUL marche, en % du capital
COIN_CONCENTRATION_PCT_ENV = "HYPERSMART_MAX_COIN_NOTIONAL_PCT"

DEFAULT_NET_EXPOSURE_PCT = 100.0        # exposition nette <= 1x le capital
DEFAULT_COIN_CONCENTRATION_PCT = 60.0   # un seul marche <= 60 % du capital


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_pct(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    v = _f(raw, default)
    return v if v > 0 else default          # une valeur <= 0 est INVALIDE, pas "illimite"


@dataclass(frozen=True, slots=True)
class ExposureSnapshot:
    gross_usdt: float          # somme des |notionnels|
    net_usdt: float            # somme SIGNEE (positif = net long)
    long_usdt: float
    short_usdt: float
    by_coin: dict[str, float]  # notionnel BRUT par marche

    @property
    def net_bias(self) -> str:
        if abs(self.net_usdt) < 1e-9:
            return "NEUTRAL"
        return "LONG" if self.net_usdt > 0 else "SHORT"


def snapshot_exposure(positions: Mapping[Any, Any] | Iterable[Any]) -> ExposureSnapshot:
    """Photographie de l'exposition, a partir des positions virtuelles du ledger."""
    rows = positions.values() if isinstance(positions, Mapping) else positions
    gross = net = longs = shorts = 0.0
    by_coin: dict[str, float] = {}
    for p in rows:
        if not isinstance(p, dict):
            continue
        size = abs(_f(p.get("size")))
        price = _f(p.get("avg_price")) or _f(p.get("entry_price"))
        if size <= 0 or price <= 0:
            continue
        notional = size * price
        side = str(p.get("direction") or p.get("side") or "").upper()
        if side not in {"LONG", "SHORT"}:
            # dernier recours : le SIGNE de la taille brute porte le sens
            side = "SHORT" if _f(p.get("size")) < 0 else "LONG"
        sign = 1.0 if side == "LONG" else -1.0
        gross += notional
        net += sign * notional
        if sign > 0:
            longs += notional
        else:
            shorts += notional
        coin = str(p.get("coin") or "?").upper()
        by_coin[coin] = by_coin.get(coin, 0.0) + notional
    return ExposureSnapshot(round(gross, 8), round(net, 8), round(longs, 8),
                            round(shorts, 8), by_coin)


def directional_refusal(
    positions: Mapping[Any, Any] | Iterable[Any],
    *,
    coin: str,
    side: str,
    new_notional_usdt: float,
    equity_usdt: float,
    max_net_pct: float | None = None,
    max_coin_pct: float | None = None,
) -> str:
    """Retourne un motif de REFUS, ou "" si l'ouverture est acceptable.

    Deux verrous, tous deux relatifs au CAPITAL (et non au notionnel, qui est deja leverage) :

    * ``NET_DIRECTIONAL_EXPOSURE_TOO_HIGH`` -- la nouvelle position pousserait le pari
      directionnel net au-dela du plafond. C'est le verrou qui manquait : sans lui, le bot
      empile 9 shorts et se retrouve avec 250 % du capital dans un seul sens.
    * ``COIN_CONCENTRATION_TOO_HIGH`` -- on empilerait trop de notionnel sur UN marche
      (deux positions ETH SHORT simultanees ont ete observees en live).

    Une position qui REDUIT le desequilibre net est toujours autorisee : on ne bloque jamais le
    trade qui reequilibre le portefeuille.
    """
    equity = abs(_f(equity_usdt))
    notional = abs(_f(new_notional_usdt))
    if equity <= 0 or notional <= 0:
        return ""                          # rien a juger : les autres gates s'en chargent

    side_up = str(side or "").upper()
    if side_up not in {"LONG", "SHORT"}:
        return ""

    snap = snapshot_exposure(positions)
    sign = 1.0 if side_up == "LONG" else -1.0

    net_cap = equity * _env_pct(NET_EXPOSURE_PCT_ENV, max_net_pct or DEFAULT_NET_EXPOSURE_PCT) / 100.0
    coin_cap = equity * _env_pct(COIN_CONCENTRATION_PCT_ENV, max_coin_pct or DEFAULT_COIN_CONCENTRATION_PCT) / 100.0

    # --- 1. exposition nette directionnelle
    net_apres = snap.net_usdt + sign * notional
    if abs(net_apres) > net_cap:
        # exception : si le trade RAPPROCHE de la neutralite, on l'accepte (il diversifie)
        if abs(net_apres) < abs(snap.net_usdt):
            pass
        else:
            return "NET_DIRECTIONAL_EXPOSURE_TOO_HIGH"

    # --- 2. concentration sur un seul marche
    coin_up = str(coin or "?").upper()
    coin_apres = snap.by_coin.get(coin_up, 0.0) + notional
    if coin_apres > coin_cap:
        return "COIN_CONCENTRATION_TOO_HIGH"

    return ""


__all__ = [
    "COIN_CONCENTRATION_PCT_ENV",
    "DEFAULT_COIN_CONCENTRATION_PCT",
    "DEFAULT_NET_EXPOSURE_PCT",
    "ExposureSnapshot",
    "NET_EXPOSURE_PCT_ENV",
    "directional_refusal",
    "snapshot_exposure",
]
