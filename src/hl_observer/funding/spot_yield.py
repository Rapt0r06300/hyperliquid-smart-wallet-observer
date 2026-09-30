"""A6 — JAMBE SPOT PRODUCTIVE : faire travailler le spot detenu, AVEC ses risques (honnete).

Verifie le 18/07 (web) : sur Hyperliquid, le spot HYPE detenu peut etre STAKE nativement
(~2,3 % APY ; HyperCore : spot balance -> staking balance -> delegation a un validateur).
HyperLend (sur HyperEVM) prete aussi le spot, mais c'est un protocole DeFi SEPARE (hors de notre
perimetre read-only HL-core + risque smart-contract) -> INSPIRE_ONLY, pas porte.

⚠️ RISQUE HONNETE — pourquoi c'est OFF par defaut :
  * Staker le spot le VERROUILLE (delai d'unstaking, plusieurs jours).
  * Or notre carry doit pouvoir SORTIR VITE (liquidation de la jambe perp, funding<=0).
  * Compter le rendement de staking n'est donc SUR que pour un carry TENU JUSQU'A MATURITE.
  * La plupart des coins n'ont PAS de staking natif -> rendement spot = 0.

Deny-by-default : `rendement_spot_bps_h` renvoie 0 sauf si le staking est explicitement DISPONIBLE
pour le token ET qu'on declare tenir la position jusqu'a maturite. On n'invente aucun rendement.
"""
from __future__ import annotations

APY_HYPE_STAKING = 0.023            # ~2,3 % APY natif (mesure 18/07 ; A RE-MESURER avant usage)
HEURES_PAR_AN = 365.0 * 24.0


def apy_vers_bps_h(apy: float) -> float:
    """APY (fraction/an) -> bps/heure. 2,3 %/an ≈ 0,026 bps/h."""
    return float(apy) / HEURES_PAR_AN * 10_000.0


def rendement_spot_bps_h(apy_staking: float, *, disponible: bool = False,
                         tenu_jusqu_a_maturite: bool = False) -> float:
    """Rendement du spot (bps/h) A AJOUTER au carry. 0 SAUF si le staking est DISPONIBLE pour ce
    token ET qu'on tient la position jusqu'a maturite (sinon le delai d'unstaking casse la sortie
    rapide du carry). Deny-by-default : on ne compte jamais un rendement qu'on ne peut pas realiser."""
    if not disponible or not tenu_jusqu_a_maturite or float(apy_staking) <= 0.0:
        return 0.0
    return round(apy_vers_bps_h(apy_staking), 6)


__all__ = ["APY_HYPE_STAKING", "HEURES_PAR_AN", "apy_vers_bps_h", "rendement_spot_bps_h"]
