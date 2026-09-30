"""P9.1 (§11.1) — capacité DIRECTIONNELLE cross-venue 2 jambes, sur les BONS côtés du carnet.

Bug visé : la capacité était estimée à partir des tailles BID des deux venues. C'est faux. Pour
`BUY_HL_SELL_BINANCE`, on ACHÈTE sur HL (on subit les **asks HL**) et on VEND sur Binance (on subit
les **bids Binance**). La capacité réelle est donc `min(profondeur asks HL, profondeur bids Binance)` :
la jambe la plus mince BORNE l'autre. Symétriquement pour `SELL_HL_BUY_BINANCE` (bids HL + asks Binance).

Ce module ne duplique pas la traversée de carnet : il COMPOSE `arbitrage.executable_legs.jambe_executable`
(VWAP multi-niveaux, refus si profondeur insuffisante — jamais d'extrapolation). Il publie la capacité
appariée, la jambe contraignante, et le coût d'entrée des deux jambes. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any, Sequence

from hl_observer.arbitrage.executable_legs import (
    ACHAT,
    VENTE,
    jambe_executable,
    profondeur_disponible_usd,
)

SCHEMA_VERSION = "hypersmart.cross_venue_capacity.v1"

BUY_HL_SELL_BINANCE = "BUY_HL_SELL_BINANCE"
SELL_HL_BUY_BINANCE = "SELL_HL_BUY_BINANCE"
DIRECTION_INCONNUE = "DIRECTION_INCONNUE"


def _cotes(direction: str):
    """Renvoie (sens_hl, clef_niveaux_hl, sens_bin, clef_niveaux_bin) ou None si direction inconnue."""
    d = str(direction).strip().upper()
    if d == BUY_HL_SELL_BINANCE:
        return (ACHAT, "hl_asks", VENTE, "bin_bids")     # achat HL sur les asks HL, vente Binance sur les bids
    if d == SELL_HL_BUY_BINANCE:
        return (VENTE, "hl_bids", ACHAT, "bin_asks")     # vente HL sur les bids HL, achat Binance sur les asks
    return None


def capacite_directionnelle(
    direction: str,
    *,
    hl_bids: Sequence = (),
    hl_asks: Sequence = (),
    bin_bids: Sequence = (),
    bin_asks: Sequence = (),
    notional_cible_usd: float = 0.0,
) -> dict[str, Any]:
    """Capacité appariée des DEUX jambes sur les bons côtés + coût d'entrée. Jamais la somme des bids."""
    cotes = _cotes(direction)
    if cotes is None:
        return {"schema_version": SCHEMA_VERSION, "statut": DIRECTION_INCONNUE,
                "capacite_appariee_usd": None, "real_execution": False}
    sens_hl, khl, sens_bin, kbin = cotes
    niveaux = {"hl_bids": list(hl_bids), "hl_asks": list(hl_asks),
               "bin_bids": list(bin_bids), "bin_asks": list(bin_asks)}
    niv_hl, niv_bin = niveaux[khl], niveaux[kbin]

    prof_hl = profondeur_disponible_usd(niv_hl)
    prof_bin = profondeur_disponible_usd(niv_bin)
    capacite = min(prof_hl, prof_bin)                    # la jambe contraignante borne l'autre
    jambe_contraignante = "HL" if prof_hl <= prof_bin else "BINANCE"

    jhl = jambe_executable(niv_hl, sens=sens_hl, notional_usd=notional_cible_usd)
    jbin = jambe_executable(niv_bin, sens=sens_bin, notional_usd=notional_cible_usd)
    executable = bool(jhl.executable and jbin.executable)
    cout_entree_bps = (round(jhl.slippage_bps + jbin.slippage_bps, 6)
                       if (executable and jhl.slippage_bps is not None and jbin.slippage_bps is not None)
                       else None)

    return {
        "schema_version": SCHEMA_VERSION,
        "statut": "OK",
        "direction": str(direction).strip().upper(),
        "cote_hl": sens_hl, "cote_binance": sens_bin,
        "capacite_appariee_usd": round(capacite, 6),
        "jambe_contraignante": jambe_contraignante,
        "profondeur_hl_usd": round(prof_hl, 6),
        "profondeur_binance_usd": round(prof_bin, 6),
        "executable_a_la_cible": executable,
        "cout_entree_bps": cout_entree_bps,
        "jambe_hl": jhl.as_dict(),
        "jambe_binance": jbin.as_dict(),
        "real_execution": False,
    }


__all__ = [
    "SCHEMA_VERSION", "BUY_HL_SELL_BINANCE", "SELL_HL_BUY_BINANCE", "DIRECTION_INCONNUE",
    "capacite_directionnelle",
]
