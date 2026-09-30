"""H1 (article Sammy) — PORTE DE SURVIE UNIFIÉE d'une stratégie.

Toute stratégie doit répondre OUI aux 4 questions AVANT de mériter la suite :
  1. survit-elle HORS ÉCHANTILLON (OOS) ?
  2. survit-elle à un AUTRE RÉGIME de marché ?
  3. survit-elle à une LIQUIDITÉ RÉDUITE (ex. /2 -> coûts qui montent) ?
  4. survit-elle à des COÛTS RÉALISTES (stress 1,5-2x) ?

Un SEUL non -> NE_SURVIT_PAS. Deny-by-default : donnée manquante = échec (on ne survit pas dans le
doute). Cette porte PRODUIT le `survit` que consomme F30 (promotion paper->testnet). PAPER only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

SURVIT = "SURVIT"
NE_SURVIT_PAS = "NE_SURVIT_PAS"


@dataclass(frozen=True, slots=True)
class VerdictSurvie:
    survit: bool
    echecs: tuple[str, ...] = field(default_factory=tuple)


def porte_de_survie(*, oos_ok: bool | None, regime_ok: bool | None,
                    liquidite_reduite_ok: bool | None, couts_realistes_ok: bool | None) -> VerdictSurvie:
    """Compose les 4 verdicts. Chaque None/False = un échec. Tout doit passer pour SURVIT."""
    echecs: list[str] = []
    if not oos_ok:
        echecs.append("ECHOUE_HORS_ECHANTILLON")
    if not regime_ok:
        echecs.append("ECHOUE_AUTRE_REGIME")
    if not liquidite_reduite_ok:
        echecs.append("ECHOUE_LIQUIDITE_REDUITE")
    if not couts_realistes_ok:
        echecs.append("ECHOUE_COUTS_REALISTES")
    return VerdictSurvie(not echecs, tuple(echecs))


# ── Helpers : calculer chaque verdict depuis des données (deny-by-default) ──

def survit_oos(pnl_oos: float | None, *, min_pnl: float = 0.0) -> bool:
    return pnl_oos is not None and float(pnl_oos) > float(min_pnl)


def survit_regime(pnl_par_regime: Mapping[str, float] | None, *, min_pnl: float = 0.0) -> bool:
    """Survit si le PIRE régime reste au-dessus du seuil (pas seulement la moyenne)."""
    if not pnl_par_regime:
        return False
    return min(float(v) for v in pnl_par_regime.values()) > float(min_pnl)


def survit_liquidite_reduite(pnl_liquidite_reduite: float | None, *, min_pnl: float = 0.0) -> bool:
    return pnl_liquidite_reduite is not None and float(pnl_liquidite_reduite) > float(min_pnl)


def survit_couts_stresses(pnls_par_multiplicateur: Sequence[float] | None, *, min_pnl: float = 0.0) -> bool:
    """Survit si le PnL reste positif au multiplicateur de coûts le PLUS DUR (le pire)."""
    if not pnls_par_multiplicateur:
        return False
    return min(float(v) for v in pnls_par_multiplicateur) > float(min_pnl)


__all__ = ["SURVIT", "NE_SURVIT_PAS", "VerdictSurvie", "porte_de_survie",
           "survit_oos", "survit_regime", "survit_liquidite_reduite", "survit_couts_stresses"]
