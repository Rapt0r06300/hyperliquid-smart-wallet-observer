"""FUNDING CROSS-VENUE (idées #6/#8) — le funding du MÊME coin diffère entre venues (HL, Binance,
Bybit…). Cette dispersion est une vraie structure exploitable, delta-neutre.

  * Y6 arb_funding_cross_venue : long le perp où le funding est le PLUS BAS, short où le PLUS HAUT.
    Même coin sur 2 venues -> exposition prix ~annulée (moins la base inter-venue) ; on encaisse
    l'écart de funding |f_a - f_b| par heure. Deny-by-default : funding manquant -> INCONNU ;
    écart sous le coût -> pas de trade.
  * Y8 funding_predit_bps_h : le funding tend à suivre la PRIME perp/spot. On PRÉDIT le prochain
    funding depuis la prime courante. ⚠️ PRÉDICTION NON VALIDÉE : à prouver hors-échantillon AVANT
    de la brancher sur une décision (loi du projet : on ne trade pas un signal non prouvé).

PAPER only, lecture seule. Aucun ordre. Un signal n'est pas un ordre.
"""
from __future__ import annotations

from dataclasses import dataclass

SEUIL_DISPERSION_BPS_H = 0.02       # sous cet écart de funding, la dispersion ne paie pas le coût
HORIZON_DEFAUT_H = 720.0            # 30 j : le carry cross-venue se tient, il ne se scalpe pas


@dataclass(frozen=True)
class ArbCrossVenue:
    coin: str
    long_venue: str
    short_venue: str
    capture_bps_h: float            # |f_a - f_b| encaissé par heure
    cout_entree_bps: float
    break_even_h: float | None
    gain_net_horizon_bps: float | None
    viable: bool
    motif: str

    def as_dict(self) -> dict:
        return {"coin": self.coin, "long_venue": self.long_venue, "short_venue": self.short_venue,
                "capture_bps_h": self.capture_bps_h, "cout_entree_bps": self.cout_entree_bps,
                "break_even_h": self.break_even_h, "gain_net_horizon_bps": self.gain_net_horizon_bps,
                "viable": self.viable, "motif": self.motif, "paper_only": True, "real_execution": False}


def arb_funding_cross_venue(coin: str, funding_a_bps_h: float | None, funding_b_bps_h: float | None,
                            *, venue_a: str, venue_b: str, cout_entree_bps: float,
                            horizon_h: float = HORIZON_DEFAUT_H,
                            seuil_bps_h: float = SEUIL_DISPERSION_BPS_H) -> ArbCrossVenue:
    """Arb de dispersion de funding entre 2 venues (delta-neutre, même coin)."""
    if funding_a_bps_h is None or funding_b_bps_h is None:
        return ArbCrossVenue(coin, venue_a, venue_b, 0.0, float(cout_entree_bps), None, None,
                             False, "FUNDING_INCONNU_SUR_UNE_VENUE")
    fa, fb = float(funding_a_bps_h), float(funding_b_bps_h)
    capture = abs(fa - fb)
    # on LONG là où le funding est le plus bas (on paie le moins / on est payé), SHORT où il est haut
    long_v, short_v = (venue_a, venue_b) if fa <= fb else (venue_b, venue_a)
    if capture <= float(seuil_bps_h):
        return ArbCrossVenue(coin, long_v, short_v, round(capture, 6), float(cout_entree_bps), None,
                             None, False, "DISPERSION_TROP_FAIBLE")
    break_even = float(cout_entree_bps) / capture
    gain = capture * float(horizon_h) - float(cout_entree_bps)
    viable = gain > 0.0
    return ArbCrossVenue(coin, long_v, short_v, round(capture, 6), float(cout_entree_bps),
                         round(break_even, 2), round(gain, 3), viable,
                         "CROSS_VENUE_VIABLE" if viable else "GAIN_HORIZON_NON_POSITIF")


# --- Y8 : prédicteur de funding (NON VALIDÉ — ne jamais brancher sans preuve OOS) ---
PLANCHER_PROTOCOLAIRE_BPS_H = 0.125     # plancher HL (cf. delta_neutral_carry)
CAP_PREMIUM_BPS_H = 5.0                 # borne prudente sur la contribution de la prime


def funding_predit_bps_h(premium_perp_spot_bps: float | None, *,
                         plancher_bps_h: float = PLANCHER_PROTOCOLAIRE_BPS_H,
                         cap_bps_h: float = CAP_PREMIUM_BPS_H) -> float | None:
    """PRÉDICTION du prochain funding ≈ plancher + composante de prime (bornée). None si prime absente.
    ⚠️ Heuristique NON VALIDÉE : sortie à confronter au funding RÉEL (backtest OOS) avant tout câblage."""
    if premium_perp_spot_bps is None:
        return None
    prime = max(-float(cap_bps_h), min(float(cap_bps_h), float(premium_perp_spot_bps)))
    return round(float(plancher_bps_h) + prime, 6)


__all__ = ["ArbCrossVenue", "arb_funding_cross_venue", "funding_predit_bps_h",
           "SEUIL_DISPERSION_BPS_H", "HORIZON_DEFAUT_H", "PLANCHER_PROTOCOLAIRE_BPS_H"]
