"""LA DETTE DE CÂBLAGE, ÉCRITE NOIR SUR BLANC — 2026-07-18.

POURQUOI CE FICHIER EXISTE
--------------------------
Le cliquet `test_le_nombre_de_modules_MORTS_ne_doit_JAMAIS_remonter` a rougi : 374 modules
testés-non-branchés pour un plafond de 273. Il avait raison, et pour deux causes distinctes qu'il
fallait séparer avant de toucher à quoi que ce soit :

  1. UN ARTEFACT DE MESURE (31 modules) — les lanceurs `.cmd` de recherche ont été déménagés dans
     `outils de test/` le 14/07. Le périmètre de l'audit ne regardait plus ce dossier : du jour au
     lendemain, des moteurs qu'un lanceur démarre (overfit_selection, H-181…) sont passés pour
     morts. Aucune ligne de code n'avait bougé. → CORRIGÉ (le périmètre suit les portes).

  2. UNE VRAIE DETTE (61 modules) — la vague « 150 idées » a produit 80 nouveaux modules `src/`.
     Ils sont écrits et testés ; **61 d'entre eux ne sont appelés par aucun chemin de production.**
     Ce n'est pas un bug de l'audit : c'est la maladie du projet, commise par moi, à grande échelle.

CE QUE CE REGISTRE N'EST PAS
----------------------------
Ce n'est PAS une façon de faire taire le cliquet. Un plafond qu'on relève quand il gêne ne mesure
plus rien — il rassure, exactement comme un garde-fou affamé. Donc :

  * chaque module est nommé, un par un (jamais un joker, jamais un préfixe) ;
  * le plafond des morts NON REGISTRÉS reste à 273 : la dette historique ne peut toujours pas
    grossir en silence ;
  * la taille de CE registre est elle-même un cliquet : `PLAFOND_DETTE` ne remonte jamais. Chaque
    module branché ou enterré le fait baisser. C'est le seul sens autorisé.

CLAUDE.md l'autorise explicitement — « une feature est DONE si : codée, testée, documentée, câblée
(ou marquée PARTIAL_NOT_WIRED) ». Ce fichier EST le PARTIAL_NOT_WIRED, rendu mécanique.

CE QUE ÇA VEUT DIRE, CONCRÈTEMENT, POUR LE BOT
----------------------------------------------
Un module de cette liste **ne protège rien et ne rapporte rien aujourd'hui**. Il ne change ni une
décision, ni un PnL. Quand on juge la performance du bot, il faut le lire comme du code au
frigo — pas comme une capacité active. Le prochain vrai levier n'est pas d'en écrire d'autres :
c'est d'en brancher.
"""
from __future__ import annotations

#: Date de constitution du registre (mesure `tools/auditer_cablage.py`).
DATE_MESURE = "2026-07-18"

#: Les 61 modules ÉCRITS + TESTÉS + NON BRANCHÉS de la vague « 150 idées ».
#: Nommés un par un : un registre au joker ne serait plus un registre.
DETTE_CABLAGE: frozenset[str] = frozenset({
    "analysis.pnl_attribution",
    "backtesting.anti_lookahead_pipeline",
    "backtesting.carry_historical_backtest",
    "backtesting.execution_passive_agressive",
    "backtesting.liquidation_net",
    "backtesting.liquidation_sizing",
    "backtesting.maker_rebate_decision",
    "backtesting.monte_carlo",
    "backtesting.order_split_benefit",
    "backtesting.perf_metrics",
    "backtesting.post_liquidation_direction",
    "backtesting.promotion_gate",
    "backtesting.queue_model",
    "backtesting.replay_doctor",
    "backtesting.replay_science",
    "backtesting.residual_alpha",
    "backtesting.survival_gate",
    "copy_wallet.leader_markout",
    "copy_wallet.structural_wallet_filter",
    "copy_wallet.wallet_consensus",
    "execution.anti_gaming",
    "execution.freshness_cut",
    "execution.maker_taker",
    "features.feature_drift",
    "features.feature_multitimeframe",
    "features.feature_normalize",
    "features.feature_store",
    "fees.fee_tier",
    "funding.carry_entry_gates",
    "funding.carry_portfolio",
    "funding.carry_rotation",
    "funding.cross_venue_funding",
    "funding.cross_venue_position",
    "funding.funding_microstructure",
    "funding.spot_yield",
    "gating.filter_pipeline",
    "market.fill_intensity",
    "market.market_impact",
    "market.universe_guard",
    "modeling.linear_baseline",
    "modeling.model_refit",
    "modeling.probability_calibration",
    "modeling.ridge_regression",
    "ops.clock_integrity",
    "ops.critere_arret",
    "ops.refusal_summary",
    "ops.strategy_monitoring",
    "realtime.tick_quality_guard",
    "research.registre_hypotheses",
    "risk.allocator",
    "risk.budget_turnover",
    "risk.capital_allocation",
    "risk.marginal_risk",
    "risk.order_rejection",
    "signals.cross_sectional_momentum",
    "signals.crowding",
    "signals.funding_reversal",
    "signals.microstructure_signals",
    "signals.orthogonalize",
    "signals.session_conditioning",
    "signals.vol_regime_signal",
})

#: CLIQUET : la dette ne remonte JAMAIS. On la baisse en branchant ou en enterrant.
#: 2026-07-18 : 61 (constitution du registre).
PLAFOND_DETTE = 61

#: Les modules `risk/` de la vague qui étaient de VRAIS garde-fous et qui, eux, ont été BRANCHÉS
#: le 18/07 sur `funding/carry_ouverture_gates.py` — le seul chemin qui ouvre une position.
#: Ils ne sont volontairement PAS dans la dette : ils travaillent.
BRANCHES_LE_18_07: frozenset[str] = frozenset({
    "risk.carry_risk_gates",        # dé-risquage continu quand le tampon de liquidation fond
    "risk.margin_reserve",          # réserve de marge intouchable
    "risk.portfolio_risk_limits",   # CVaR : queue de perte trop lourde -> on n'empile pas
    "risk.safety_gates_mm",         # kill-switch divergence de sources + levier par régime
    "risk.drawdown_scaling",        # en drawdown, la taille rétrécit
    "risk.kelly_sizing",            # edge <= 0 -> pas de pari
})


def est_dette(module: str) -> bool:
    """`module` est-il une dette DÉCLARÉE ? Accepte 'hl_observer.x.y' ou 'x.y'."""
    court = module[len("hl_observer."):] if module.startswith("hl_observer.") else module
    return court in DETTE_CABLAGE


__all__ = ["DETTE_CABLAGE", "PLAFOND_DETTE", "BRANCHES_LE_18_07", "DATE_MESURE", "est_dette"]
