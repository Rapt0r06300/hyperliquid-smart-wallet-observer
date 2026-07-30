"""P9.2 (§11.2) — coût de ROUND-TRIP cross-venue : entrée 2 jambes + SORTIE 2 jambes contre carnet causal futur.

Estimer le round-trip avec la seule ENTRÉE est faux : il faut aussi débaucler les deux jambes. Ce module
compose `executable_legs.jambe_executable` (VWAP, refus si profondeur insuffisante) sur QUATRE jambes :

  BUY_HL_SELL_BINANCE → entrée : ACHAT HL (asks) + VENTE Binance (bids)
                         sortie : VENTE HL (bids futurs) + ACHAT Binance (asks futurs)
  (symétrique pour SELL_HL_BUY_BINANCE).

La SORTIE est simulée contre un carnet CAUSAL FUTUR fourni par l'appelant — jamais supposée au mid. Coût
total = slippage de profondeur des 4 jambes + 4 frais taker (2 HL + 2 Binance). Le coût de spread est,
lui, déjà porté par l'edge (prix bid/ask exécutables) : on ne le recompte pas ici (cf. contrat P1B).

Deny-by-default : si une seule jambe n'est pas exécutable (profondeur insuffisante), le round-trip est
`UNMEASURABLE` et la jambe fautive est nommée. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any, Sequence

from hl_observer.arbitrage.executable_legs import ACHAT, VENTE, jambe_executable
from hl_observer.arbitrage.cross_venue_capacity import (
    BUY_HL_SELL_BINANCE,
    SELL_HL_BUY_BINANCE,
    DIRECTION_INCONNUE,
)

SCHEMA_VERSION = "hypersmart.cross_venue_roundtrip.v1"


def _plan(direction: str):
    """(sens_entree_hl, sens_entree_bin, sens_sortie_hl, sens_sortie_bin) ou None."""
    d = str(direction).strip().upper()
    if d == BUY_HL_SELL_BINANCE:
        return (ACHAT, VENTE, VENTE, ACHAT)      # entre long HL / short BIN ; sort en vendant HL / rachetant BIN
    if d == SELL_HL_BUY_BINANCE:
        return (VENTE, ACHAT, ACHAT, VENTE)
    return None


def _niv(sens: str, cote: str, books: dict) -> list:
    """Niveaux à traverser selon le sens : ACHAT→asks, VENTE→bids, sur la venue `cote` ('hl'/'bin')."""
    if sens == ACHAT:
        return list(books.get(f"{cote}_asks", ()))
    return list(books.get(f"{cote}_bids", ()))


def cout_round_trip(
    direction: str,
    *,
    entree: dict,
    sortie: dict,
    notional_usd: float,
    fee_bps_hl: float = 3.5,
    fee_bps_binance: float = 4.5,
) -> dict[str, Any]:
    """Coût de round-trip complet (4 jambes + 4 frais). `entree`/`sortie` = {hl_bids,hl_asks,bin_bids,bin_asks}."""
    plan = _plan(direction)
    if plan is None:
        return {"schema_version": SCHEMA_VERSION, "statut": DIRECTION_INCONNUE,
                "cout_round_trip_bps": None, "real_execution": False}
    s_ent_hl, s_ent_bin, s_sor_hl, s_sor_bin = plan

    jambes = {
        "entree_hl": jambe_executable(_niv(s_ent_hl, "hl", entree), sens=s_ent_hl, notional_usd=notional_usd),
        "entree_binance": jambe_executable(_niv(s_ent_bin, "bin", entree), sens=s_ent_bin, notional_usd=notional_usd),
        "sortie_hl": jambe_executable(_niv(s_sor_hl, "hl", sortie), sens=s_sor_hl, notional_usd=notional_usd),
        "sortie_binance": jambe_executable(_niv(s_sor_bin, "bin", sortie), sens=s_sor_bin, notional_usd=notional_usd),
    }
    non_executables = [nom for nom, j in jambes.items() if not j.executable]
    if non_executables:
        return {
            "schema_version": SCHEMA_VERSION, "statut": "UNMEASURABLE",
            "direction": str(direction).strip().upper(),
            "jambes_non_executables": non_executables,
            "cout_round_trip_bps": None,
            "jambes": {n: j.as_dict() for n, j in jambes.items()},
            "real_execution": False,
        }

    slippage_total = sum(float(j.slippage_bps or 0.0) for j in jambes.values())
    frais_total = 2.0 * float(fee_bps_hl) + 2.0 * float(fee_bps_binance)   # HL entrée+sortie, Binance entrée+sortie
    cout = round(slippage_total + frais_total, 6)
    return {
        "schema_version": SCHEMA_VERSION, "statut": "OK",
        "direction": str(direction).strip().upper(),
        "cout_round_trip_bps": cout,
        "slippage_4_jambes_bps": round(slippage_total, 6),
        "frais_4_jambes_bps": round(frais_total, 6),
        "detail_slippage_bps": {n: round(float(j.slippage_bps or 0.0), 6) for n, j in jambes.items()},
        "jambes": {n: j.as_dict() for n, j in jambes.items()},
        "note": "spread deja dans l'edge (prix executables) - non recompte ici",
        "real_execution": False,
    }


__all__ = ["SCHEMA_VERSION", "cout_round_trip"]
