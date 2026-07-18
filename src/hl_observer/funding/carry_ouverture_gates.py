"""PORTE DE RISQUE À L'OUVERTURE D'UN CARRY — sur le chemin qui TOURNE VRAIMENT.

POURQUOI CE MODULE EXISTE (constat mesuré du 2026-07-18, pas une intuition)
--------------------------------------------------------------------------
J'avais branché 7 filtres de risque sur `pipeline/v12_decision_pipeline.py` (chantier X1-X4) en
croyant tenir « la porte de décision LIVE ». L'audit de câblage a répondu, chiffres en main :

    pipeline.v12_decision_pipeline  ->  MORT
    gating.filter_pipeline          ->  MORT
    funding.carry_*                 ->  VIVANT

Personne, en production, n'appelle `run_v12_decision_pipeline`. Mes 7 gardes protégeaient donc
une porte que le bot ne franchit jamais : la maladie exacte du projet (« mention ≠ porte »),
commise par moi. Ce module corrige ça en posant les gardes **là où une position s'ouvre pour de
vrai** : le cycle de vie du carry.

CE QU'IL FAIT
-------------
Une seule fonction, appelée juste avant d'ouvrir une position carry. Elle compose les garde-fous
de `risk/` qui étaient en limbe (testés, appelés par personne) :

  * `margin_reserve`      -> refuse si l'ouverture entame la réserve de marge intouchable ;
  * `carry_risk_gates`    -> dé-risque continûment quand le tampon de liquidation se réduit,
                             et refuse si le budget de funding payé est dépassé ;
  * `safety_gates_mm`     -> KILL-SWITCH : marks de plusieurs sources qui divergent = donnée
                             douteuse -> NO_TRADE (M6), et plafond de levier selon le régime (M7) ;
  * `portfolio_risk_limits` -> CVaR des PnL réalisés récents : si la queue de perte dépasse une
                             fraction du capital, on n'ajoute pas de risque ;
  * `drawdown_scaling`    -> en drawdown, la taille rétrécit continûment ;
  * `kelly_sizing`        -> plafonne la fraction de capital par l'edge/variance réels.

RÈGLE ANTI-« GARDE AFFAMÉ » (leçon du 13/07)
--------------------------------------------
Une entrée ABSENTE ne fait jamais refuser : le garde concerné **s'abstient** et le dit dans
`gardes`. Un garde nourri de `None` ne protège de rien, il rassure — et c'est pire que rien.
Seule une entrée PRÉSENTE et MAUVAISE refuse.

PAPER only : rien ici n'envoie d'ordre. Un refus est un NO_TRADE, une autorisation est une
autorisation d'écrire une ligne de simulation. Aucune clé, aucune signature, aucun /exchange.
"""
from __future__ import annotations

from typing import Any, Sequence

from hl_observer.risk.carry_risk_gates import budget_funding_depasse, fraction_derisk
from hl_observer.risk.drawdown_scaling import facteur_capital
from hl_observer.risk.kelly_sizing import fraction_capital_continu
from hl_observer.risk.margin_reserve import respecte_reserve
from hl_observer.risk.portfolio_risk_limits import cvar_historique
from hl_observer.risk.safety_gates_mm import levier_max_regime, mode_sur

#: part du capital que la queue de perte (CVaR) ne doit pas dépasser avant qu'on arrête d'ajouter.
CVAR_MAX_FRAC_CAPITAL = 0.25
#: plancher/plafond du facteur de taille — on ne multiplie jamais la taille par ce garde.
FACTEUR_MIN, FACTEUR_MAX = 0.0, 1.0

MOTIF_RESERVE = "RESERVE_DE_MARGE_ENTAMEE_NO_TRADE"
MOTIF_TAMPON = "TAMPON_LIQUIDATION_TROP_MINCE_NO_TRADE"
MOTIF_BUDGET_FUNDING = "BUDGET_FUNDING_DEPASSE_NO_TRADE"
MOTIF_DIVERGENCE = "SOURCES_DIVERGENTES_DONNEE_DOUTEUSE_NO_TRADE"
MOTIF_CVAR = "QUEUE_DE_PERTE_TROP_LOURDE_NO_TRADE"
MOTIF_LEVIER = "LEVIER_AU_DESSUS_DU_PLAFOND_DE_REGIME_NO_TRADE"


def _nombre(v: Any) -> float | None:
    """Un nombre exploitable, ou None. `None` veut dire ABSENT -> le garde s'abstiendra."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return None if f != f else f          # NaN == donnée absente, pas donnée nulle


def porte_risque_ouverture(
    *,
    marge_demandee_usd: float,
    marge_utilisee_usd: float | None = None,
    capital_usd: float | None = None,
    distance_tampon_frac: float | None = None,
    funding_paye_cumule_bps: float | None = None,
    budget_funding_bps: float | None = None,
    marks_multi_sources: Sequence[float] | None = None,
    pnls_realises_recents: Sequence[float] | None = None,
    drawdown_frac: float | None = None,
    levier_demande: float | None = None,
    regime: str | None = None,
    edge_attendu: float | None = None,
    variance_attendue: float | None = None,
) -> dict[str, Any]:
    """Autorise (ou non) l'ouverture d'un carry, et donne le facteur de taille à appliquer.

    Retour : {"autorise": bool, "motif": str, "facteur_taille": float, "gardes": [str, ...]}
    `facteur_taille` <= 1.0 : ce garde ne peut que RÉDUIRE la taille, jamais l'augmenter.
    """
    gardes: list[str] = []
    facteur = 1.0

    # --- 1) KILL-SWITCH divergence de sources (M6) : donnée douteuse -> on ne touche à rien.
    if marks_multi_sources and len([m for m in marks_multi_sources if _nombre(m) is not None]) >= 2:
        propres = [float(m) for m in marks_multi_sources if _nombre(m) is not None]
        if not mode_sur(propres):
            return {"autorise": False, "motif": MOTIF_DIVERGENCE, "facteur_taille": 0.0,
                    "gardes": gardes + ["divergence_sources:REFUS"]}
        gardes.append("divergence_sources:OK")
    else:
        gardes.append("divergence_sources:ABSTENTION_donnee_absente")

    # --- 2) RÉSERVE DE MARGE : l'ouverture ne doit pas manger le coussin intouchable.
    cap = _nombre(capital_usd)
    utilisee = _nombre(marge_utilisee_usd)
    demandee = _nombre(marge_demandee_usd) or 0.0
    if cap is not None and cap > 0 and utilisee is not None:
        if not respecte_reserve(utilisee + demandee, cap):
            return {"autorise": False, "motif": MOTIF_RESERVE, "facteur_taille": 0.0,
                    "gardes": gardes + ["reserve_marge:REFUS"]}
        gardes.append("reserve_marge:OK")
    else:
        gardes.append("reserve_marge:ABSTENTION_capital_inconnu")

    # --- 3) BUDGET DE FUNDING PAYÉ : un carry qui paie plus qu'il n'encaisse n'est plus un carry.
    paye = _nombre(funding_paye_cumule_bps)
    budget = _nombre(budget_funding_bps)
    if paye is not None and budget is not None and budget > 0:
        if budget_funding_depasse(paye, budget_bps=budget):
            return {"autorise": False, "motif": MOTIF_BUDGET_FUNDING, "facteur_taille": 0.0,
                    "gardes": gardes + ["budget_funding:REFUS"]}
        gardes.append("budget_funding:OK")
    else:
        gardes.append("budget_funding:ABSTENTION_budget_absent")

    # --- 4) TAMPON DE LIQUIDATION : dé-risquage CONTINU (pas un on/off) ; 0 -> refus net.
    tampon = _nombre(distance_tampon_frac)
    if tampon is not None:
        f = fraction_derisk(tampon)
        if f <= 0.0:
            return {"autorise": False, "motif": MOTIF_TAMPON, "facteur_taille": 0.0,
                    "gardes": gardes + ["tampon_liquidation:REFUS"]}
        facteur = min(facteur, f)
        gardes.append("tampon_liquidation:facteur=%.2f" % f)
    else:
        gardes.append("tampon_liquidation:ABSTENTION_tampon_inconnu")

    # --- 5) CVaR des PnL réalisés : si la QUEUE de perte est déjà lourde, on n'empile pas.
    pnls = [float(x) for x in (pnls_realises_recents or []) if _nombre(x) is not None]
    if cap is not None and cap > 0 and len(pnls) >= 5:
        # CONVENTION (vérifiée dans portfolio_risk_limits) : `cvar_historique` rend la perte en
        # POSITIF. J'avais d'abord écrit `abs(min(0.0, cvar))` -> le garde n'aurait JAMAIS pu se
        # déclencher : un verrou mort de plus. C'est le test qui l'a trouvé, pas moi.
        cvar = cvar_historique(pnls)
        if cvar is not None and cvar > CVAR_MAX_FRAC_CAPITAL * cap:
            return {"autorise": False, "motif": MOTIF_CVAR, "facteur_taille": 0.0,
                    "gardes": gardes + ["cvar:REFUS"]}
        gardes.append("cvar:OK")
    else:
        gardes.append("cvar:ABSTENTION_historique_trop_court")

    # --- 6) DRAWDOWN : en perte, la taille rétrécit continûment (S5).
    dd = _nombre(drawdown_frac)
    if dd is not None:
        f = facteur_capital(max(0.0, dd))
        facteur = min(facteur, f)
        gardes.append("drawdown:facteur=%.2f" % f)
    else:
        gardes.append("drawdown:ABSTENTION_drawdown_inconnu")

    # --- 7) LEVIER selon le RÉGIME (M7) : vol haute -> moins de levier. Au-dessus = refus.
    lev = _nombre(levier_demande)
    if lev is not None and regime:
        plafond = levier_max_regime(str(regime))
        if lev > plafond:
            return {"autorise": False, "motif": MOTIF_LEVIER, "facteur_taille": 0.0,
                    "gardes": gardes + ["levier_regime:REFUS(%.1f>%.1f)" % (lev, plafond)]}
        gardes.append("levier_regime:OK")
    else:
        gardes.append("levier_regime:ABSTENTION_regime_inconnu")

    # --- 8) KELLY : plafonne la fraction de capital par l'edge/variance RÉELS (E22).
    edge = _nombre(edge_attendu)
    var = _nombre(variance_attendue)
    if edge is not None and var is not None and var > 0:
        frac = fraction_capital_continu(edge, var)
        if frac <= 0.0:                      # Kelly dit « pas d'edge » -> on ne parie pas
            return {"autorise": False, "motif": "KELLY_SANS_EDGE_NO_TRADE", "facteur_taille": 0.0,
                    "gardes": gardes + ["kelly:REFUS"]}
        # HONNÊTETÉ : Kelly rend une fraction DE CAPITAL. La convertir en « facteur de taille »
        # supposerait une taille de référence que nous n'avons pas (notre sizing est une marge
        # FIXE de 50 $). On refuse donc de fabriquer un multiplicateur : Kelly sert ici de PORTE
        # (edge <= 0 -> pas de pari) et sa fraction est journalisée pour l'audit. Rien d'inventé.
        gardes.append("kelly:frac_capital=%.4f" % frac)
    else:
        gardes.append("kelly:ABSTENTION_edge_ou_variance_absent")

    facteur = max(FACTEUR_MIN, min(FACTEUR_MAX, facteur))
    return {"autorise": True, "motif": "", "facteur_taille": facteur, "gardes": gardes}


__all__ = ["porte_risque_ouverture", "CVAR_MAX_FRAC_CAPITAL",
           "MOTIF_RESERVE", "MOTIF_TAMPON", "MOTIF_BUDGET_FUNDING", "MOTIF_DIVERGENCE",
           "MOTIF_CVAR", "MOTIF_LEVIER"]
