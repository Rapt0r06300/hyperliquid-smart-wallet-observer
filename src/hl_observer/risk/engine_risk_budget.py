"""BUDGET DE RISQUE PAR MOTEUR — un moteur qui saigne ne doit pas tuer l'autre (2026-07-11).

LE PROBLÈME (piste 81-90 du brief).

Le garde-fou de session existant (`session_pnl_guard`) raisonne sur **UN SEUL** PnL : celui de la
session entière. Conséquence directe, et absurde :

  * le SNIPER perd 40 $ → la session passe en mode protection → **le GRINDER est puni aussi**,
    alors qu'il n'a rien fait de mal, et que son mécanisme (funding delta-neutre) n'a strictement
    rien à voir avec la raison de la perte ;
  * inversement, un GRINDER qui grignoterait +30 $ **masquerait** un SNIPER qui saigne −70 $ :
    la session paraît « à −40 », le garde-fou se déclenche mollement, et le vrai coupable
    continue de tirer.

Un budget commun mélange les responsabilités. **Chaque moteur doit répondre de ses propres pertes.**

CE MODULE :
  * lit le PnL RÉALISÉ **par moteur** (via `engine_pnl`, donc via le ledger — pas un compteur
    parallèle qui pourrait diverger) ;
  * rend un refus qui ne frappe QUE le moteur fautif ;
  * deux paliers : SOFT (le moteur se tait un temps) et HARD (le moteur est coupé pour la session).

RÈGLES DURES :
  * **DENY-BY-DEFAULT** : un plafond invalide (0, négatif, illisible) ne veut PAS dire « illimité ».
    On retombe sur le défaut. Un garde-fou de risque ne se desserre jamais tout seul — c'est le bug
    « fail-open » déjà trouvé dans les gates de portefeuille.
  * **UNKNOWN_LEGACY n'est pas un moteur** : on ne coupe pas un moteur qu'on n'a pas su identifier
    (on ne sait pas ce qu'on couperait). Les autres gates s'en chargent.
  * Un moteur SANS trade n'est jamais coupé : on ne punit pas ce qui n'a rien fait.

Aucun ordre réel. Pur, sans I/O.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from hl_observer.strategies.engine_pnl import attribuer_pnl_par_moteur
from hl_observer.strategies.strategy_mode import GRINDER, SNIPER, UNKNOWN_LEGACY

# Alignés sur les paliers de session du launcher (soft 40 $, hard 150 $ sur 1 000 $ de capital),
# mais exprimés en % du capital : un budget en dur ne suit pas la taille du compte.
ENV_SOFT_PCT = "HYPERSMART_ENGINE_SOFT_LOSS_PCT"
ENV_HARD_PCT = "HYPERSMART_ENGINE_HARD_LOSS_PCT"
DEFAUT_SOFT_PCT = 4.0            # 40 $ sur 1 000 $
DEFAUT_HARD_PCT = 15.0           # 150 $ sur 1 000 $

MOTEURS_BUDGETES = (GRINDER, SNIPER)


def _pct(nom: str, defaut: float) -> float:
    """DENY-BY-DEFAULT : une valeur invalide retombe sur le defaut, JAMAIS sur l'infini."""
    try:
        v = float(os.environ.get(nom, ""))
    except (TypeError, ValueError):
        return defaut
    if not (v > 0.0) or v != v:          # <= 0, NaN : invalide -> defaut (on ne desserre pas)
        return defaut
    return v


@dataclass(frozen=True, slots=True)
class BudgetMoteur:
    moteur: str
    pnl_realise_usdc: float
    trades: int
    seuil_soft_usdc: float
    seuil_hard_usdc: float
    refus: str                     # "" = le moteur peut ouvrir

    @property
    def coupe(self) -> bool:
        return bool(self.refus)


def evaluer_budgets(
    ledger_events: Iterable[Mapping[str, Any]] | None,
    *,
    equity_usdt: float,
) -> dict[str, BudgetMoteur]:
    """Rend un budget par moteur. Le PnL vient du LEDGER, source unique de vérité."""
    capital = abs(float(equity_usdt or 0.0))
    if capital <= 0.0:
        capital = 1000.0             # capital illisible : on ne desactive pas le garde-fou

    soft = capital * _pct(ENV_SOFT_PCT, DEFAUT_SOFT_PCT) / 100.0
    hard = capital * _pct(ENV_HARD_PCT, DEFAUT_HARD_PCT) / 100.0
    if hard < soft:                  # config incoherente : le HARD ne peut pas etre plus laxiste
        hard = soft

    bilans = attribuer_pnl_par_moteur(ledger_events)
    budgets: dict[str, BudgetMoteur] = {}

    for moteur in MOTEURS_BUDGETES:
        b = bilans[moteur]
        pnl = b.pnl_net_usdc
        refus = ""
        # un moteur qui n'a rien fait ne peut pas etre coupe : on ne punit pas le neant
        if b.trades > 0:
            if pnl <= -hard:
                refus = f"{moteur}_HARD_LOSS_BUDGET_EXCEEDED"
            elif pnl <= -soft:
                refus = f"{moteur}_SOFT_LOSS_BUDGET_EXCEEDED"
        budgets[moteur] = BudgetMoteur(
            moteur=moteur,
            pnl_realise_usdc=round(pnl, 6),
            trades=b.trades,
            seuil_soft_usdc=round(soft, 6),
            seuil_hard_usdc=round(hard, 6),
            refus=refus,
        )
    return budgets


def engine_budget_refusal(
    ledger_events: Iterable[Mapping[str, Any]] | None,
    *,
    moteur: str,
    equity_usdt: float,
) -> str:
    """Le moteur `moteur` a-t-il le droit d'ouvrir ? "" = oui.

    **Seul le moteur fautif est frappé.** C'est tout l'intérêt : le Grinder ne doit pas payer
    pour les pertes du Sniper, et un Grinder qui gagne ne doit pas servir d'alibi au Sniper.
    """
    m = str(moteur or "").upper()
    if m not in MOTEURS_BUDGETES:
        # UNKNOWN_LEGACY : on ne coupe pas ce qu'on n'a pas su identifier -- on ne saurait pas
        # ce qu'on coupe. Les autres gates (exposition, session, edge) restent en place.
        return ""
    budgets = evaluer_budgets(ledger_events, equity_usdt=equity_usdt)
    return budgets[m].refus


def rapport_budgets(
    ledger_events: Iterable[Mapping[str, Any]] | None,
    *,
    equity_usdt: float,
) -> dict[str, Any]:
    """Vue sérialisable pour le dashboard et l'audit."""
    budgets = evaluer_budgets(ledger_events, equity_usdt=equity_usdt)
    return {
        "budgets": {
            m: {
                "moteur": b.moteur,
                "pnl_realise_usdc": b.pnl_realise_usdc,
                "trades": b.trades,
                "seuil_soft_usdc": b.seuil_soft_usdc,
                "seuil_hard_usdc": b.seuil_hard_usdc,
                "refus": b.refus,
                "coupe": b.coupe,
            }
            for m, b in budgets.items()
        },
        "moteurs_coupes": sorted(m for m, b in budgets.items() if b.coupe),
        "paper_only": True,
        "real_execution": False,
    }


__all__ = [
    "DEFAUT_HARD_PCT",
    "DEFAUT_SOFT_PCT",
    "ENV_HARD_PCT",
    "ENV_SOFT_PCT",
    "MOTEURS_BUDGETES",
    "BudgetMoteur",
    "engine_budget_refusal",
    "evaluer_budgets",
    "rapport_budgets",
]
