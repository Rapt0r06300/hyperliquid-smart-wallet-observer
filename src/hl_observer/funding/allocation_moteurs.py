"""ALLOCATION DYNAMIQUE MULTI-MOTEURS — le capital va au meilleur edge NET PROUVÉ (23/07, tâche 65).

Le cap de Flo : « une fois un edge net prouvé, construis une allocation dynamique où le capital va au
meilleur moteur disponible, tout en gardant une réserve et des limites de risque séparées. »

LA PORTE DE PREUVE (le cœur, non négociable). Un moteur ne reçoit du capital QUE s'il est ÉLIGIBLE :
  1. `prouve_oos = True`  — son edge net a tenu HORS ÉCHANTILLON (live-forward, pas la 2ᵉ moitié
     in-sample). Un edge « prometteur mais extrapolé » (cross-venue au 23/07) = **PAS** éligible.
  2. `edge_net_apr_pct > HLP_APR_MIN` — il bat l'ALTERNATIVE (le vault HLP, ~15-30 % APR). Positif ne
     suffit pas : un carry à 5 %/an est DOMINÉ (leçon `benchmark-cash-et-outil-qui-se-tait`). Battre
     le cash n'est pas battre le meilleur usage sûr du capital.
  3. `qualite_data ≥ MIN_QUALITE` — un edge mesuré sur des données douteuses n'est pas un edge.

Tant qu'AUCUN moteur n'est éligible (l'état HONNÊTE au 23/07 : carry dominé, cross-venue
NEED_MORE_DATA, arb dominé, copy réfuté, overshoot shadow), **tout le déployable reste en RÉSERVE**.
L'allocateur n'invente pas un gagnant pour occuper le capital — ne rien risquer bat perdre.

RÉSERVE & LIMITES SÉPARÉES. Une réserve intouchable (`RESERVE_FRAC`) ; un plafond de capital PAR
MOTEUR (`PLAFOND_PAR_MOTEUR`) ET par sa capacité mesurée (les mid-caps ne scalent pas) : les accidents
d'un carry delta-neutre sont COIN/ENGINE-spécifiques, donc concentrer les concentre. L'allocation aux
éligibles est ∝ edge net **ajusté du risque** (÷ (1+drawdown)), jamais au levier.

PAPER only : répartir une simulation n'est pas passer un ordre.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

HLP_APR_MIN = 15.0          # l'alternative à battre : le vault HLP. En dessous, un moteur est DOMINÉ.
MIN_QUALITE = 0.6           # sous ça, la donnée ne permet pas de croire l'edge
RESERVE_FRAC = 0.20         # réserve intouchable
PLAFOND_PAR_MOTEUR = 0.40   # limite de risque SÉPARÉE : au plus 40 % du déployable sur un moteur


@dataclass(frozen=True)
class MoteurEtat:
    """L'état économique d'un moteur, tel que MESURÉ (jamais supposé)."""
    nom: str
    edge_net_apr_pct: float | None   # APR net APRÈS tous les coûts ; None = non mesurable
    prouve_oos: bool                 # l'edge a-t-il tenu en OOS LIVE-FORWARD (pas la 2ᵉ moitié in-sample) ?
    drawdown_max_pct: float = 0.0    # pour l'ajustement au risque
    capacite_usd: float = 1e9        # capital max absorbable (mid-caps : petit)
    qualite_data: float = 1.0        # 0..1
    note: str = ""

    def eligible(self, *, hlp_apr_min: float = HLP_APR_MIN, min_qualite: float = MIN_QUALITE) -> bool:
        return (self.prouve_oos and self.edge_net_apr_pct is not None
                and self.edge_net_apr_pct > hlp_apr_min and self.qualite_data >= min_qualite)

    def raison_exclusion(self, *, hlp_apr_min: float = HLP_APR_MIN) -> str:
        if self.edge_net_apr_pct is None:
            return "EDGE_NON_MESURABLE"
        if not self.prouve_oos:
            return "NON_PROUVE_OOS_LIVE"                 # prometteur ≠ prouvé
        if self.edge_net_apr_pct <= hlp_apr_min:
            return "DOMINE_PAR_HLP"                      # positif mais pas mieux que l'alternative
        if self.qualite_data < MIN_QUALITE:
            return "DONNEE_INSUFFISANTE"
        return ""


def allouer_capital(moteurs: list[MoteurEtat], *, capital_usd: float,
                    reserve_frac: float = RESERVE_FRAC,
                    plafond_par_moteur: float = PLAFOND_PAR_MOTEUR,
                    hlp_apr_min: float = HLP_APR_MIN) -> dict[str, Any]:
    """{allocation par moteur, réserve, exclusions}. Capital SEULEMENT aux moteurs éligibles.
    Aucun éligible -> tout en réserve (l'état honnête tant qu'aucun edge n'est prouvé)."""
    cap = max(0.0, float(capital_usd))
    reserve_min = cap * max(0.0, min(0.9, reserve_frac))
    deployable = cap - reserve_min
    eligibles = [m for m in moteurs if m.eligible(hlp_apr_min=hlp_apr_min)]
    exclus = {m.nom: m.raison_exclusion(hlp_apr_min=hlp_apr_min) for m in moteurs if not m.eligible(hlp_apr_min=hlp_apr_min)}
    if not eligibles or deployable <= 0:
        return {"reserve_usd": round(cap, 2), "allocation": {}, "exclus": exclus,
                "note": "aucun moteur éligible (edge net prouvé OOS ET > HLP) -> tout en réserve. "
                        "Ne rien risquer bat perdre.", "real_execution": False}
    # poids ∝ edge net ajusté du risque (÷ (1+drawdown)). Jamais de levier ici.
    poids = {m.nom: max(0.0, m.edge_net_apr_pct) / (1.0 + max(0.0, m.drawdown_max_pct) / 100.0)
             for m in eligibles}
    total = sum(poids.values()) or 1.0
    plaf = max(0.05, min(1.0, plafond_par_moteur))
    alloc: dict[str, float] = {}
    for m in eligibles:
        part = poids[m.nom] / total
        montant = min(deployable * part, deployable * plaf, m.capacite_usd)   # plafond risque ET capacité
        alloc[m.nom] = round(montant, 2)
    reserve = round(cap - sum(alloc.values()), 2)                              # le non-déployé rejoint la réserve
    return {"reserve_usd": reserve, "allocation": alloc, "exclus": exclus,
            "note": "capital ∝ edge net ajusté du risque, plafonné par moteur ET capacité ; "
                    "réserve conservée.", "real_execution": False}


def etats_courants() -> list[MoteurEtat]:
    """L'état HONNÊTE des moteurs au 23/07 (mesuré cette session). Aucun n'est encore éligible :
    l'allocateur mettra donc tout en réserve — c'est le résultat vrai, pas un échec de l'outil."""
    return [
        MoteurEtat("carry", edge_net_apr_pct=5.0, prouve_oos=True, qualite_data=0.9,
                   note="delta-neutre mesuré ~5 %/an net -> DOMINÉ par HLP 15-30 %"),
        MoteurEtat("cross_venue", edge_net_apr_pct=20.0, prouve_oos=False, qualite_data=0.7,
                   capacite_usd=500.0,
                   note="7 mid-caps net-positifs après coûts IN+OOS-2e-moitié, MAIS net EXTRAPOLÉ "
                        "(fenêtre courte) -> pas encore prouvé LIVE-FORWARD -> NEED_MORE_DATA"),
        MoteurEtat("arbitrage", edge_net_apr_pct=None, prouve_oos=False, qualite_data=0.7,
                   note="dominé au coût réel (16 bps > 3,4 de convergence) ; edge = sélection à re-tester"),
        MoteurEtat("copy", edge_net_apr_pct=None, prouve_oos=False, qualite_data=0.5,
                   note="réfuté (signal 62 s, anti-persistant) ; frontière = vaults, non testée"),
        MoteurEtat("overshoot", edge_net_apr_pct=None, prouve_oos=False, qualite_data=0.4,
                   note="SHADOW : proxy forced-flow, overshoots ne réversent pas encore (marché calme)"),
    ]


def rapport(capital_usd: float = 1000.0) -> dict[str, Any]:
    """L'allocation courante, lisible — pour le dashboard/audit. Aujourd'hui : tout en réserve."""
    r = allouer_capital(etats_courants(), capital_usd=capital_usd)
    r["capital_usd"] = capital_usd
    r["moteurs_eligibles"] = [m.nom for m in etats_courants() if m.eligible()]
    return r


__all__ = ["HLP_APR_MIN", "MIN_QUALITE", "RESERVE_FRAC", "PLAFOND_PAR_MOTEUR",
           "MoteurEtat", "allouer_capital", "etats_courants", "rapport"]
