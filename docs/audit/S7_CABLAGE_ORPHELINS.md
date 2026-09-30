# S7 — AUDIT « CÂBLÉ vs ORPHELIN vs TESTÉ-SEULEMENT » de TOUS les modules

**Date : 2026-07-18.** Demande de Flo : *« un audit "câblé vs orphelin vs testé" de TOUS les
modules ».* Outil : `tools/audit_cablage_modules.py` (importable, testé). 100 % lecture, aucun ordre.

> **La maladie du projet, mesurée.** « Capacité présente, interrupteur éteint, personne ne se
> plaint. » On la chiffre au lieu de la deviner. Un module *importé* par une porte de production
> est **atteignable** ; un module importé *seulement par ses tests* est une **capacité morte** tant
> qu'on ne l'a pas branché sur le chemin de décision.

## Méthode

Pour chaque `.py` de `src/hl_observer` (hors `__init__`), on cherche son chemin pointé
(`hl_observer.x.y`) dans deux ensembles de fichiers :

- **Portes de production** = `src/hl_observer/**` (hors soi-même) **+** `tools/**` (lancés par les
  `.cmd`) **+** les `.py` racine. Un import depuis là ⇒ **CÂBLÉ**.
- **Tests** = `tests/test_*.py`. Import *uniquement* depuis là ⇒ **TESTÉ-SEULEMENT**.
- Aucun import ⇒ **ORPHELIN** (code mort franc).

**Borne haute assumée** : « câblé » = *atteignable par import*, pas forcément *appelé sur le chemin
edge→décision→ledger*. C'est la couche que S7 mesure honnêtement ; le « vraiment appelé » se
prouve par test de bout en bout (cluster V) et par `TEST-AUDIT-complet.cmd` sous **Windows**
(le sandbox n'a ni réseau ni UTF-8 fiable — la vérité complète tourne côté Windows).

## Résultat global (954 modules)

| Catégorie | Nombre | Part |
|---|---:|---:|
| **CÂBLÉ** (atteignable prod) | 604 | 63,3 % |
| **TESTÉ-SEULEMENT** (la maladie) | 273 | 28,6 % |
| **ORPHELIN** (code mort) | 77 | 8,1 % |

**Lecture honnête** : près d'**un module sur trois** est testé mais jamais atteint en production.
Ce n'est pas un bug isolé, c'est le mode de défaillance structurel du projet — désormais chiffré,
donc pilotable. Manifeste machine : `tools/audit_cablage_manifest.json` (rejoué à chaque audit).

## Les briques de CETTE session (54 repérées)

| Catégorie | Nombre |
|---|---:|
| CÂBLÉ | 9 |
| TESTÉ-SEULEMENT | 44 |
| ORPHELIN | 1 |

**Aveu net, sans maquillage** : sur ~50 modules construits cette session, seuls **9 sont déjà
atteignables en production**. Les 44 autres sont des **blocs de valeur latente** — corrects,
testés, mais inertes tant qu'ils ne sont pas câblés dans le noyau de décision. C'est *attendu*
pour des briques quant (on construit la boîte à outils avant de la monter), mais ça ne doit
JAMAIS être présenté comme « fait ». **Une capacité testée n'est pas un PnL.**

### Déjà CÂBLÉ (9) — le cluster carry surtout
`funding/funding_persistence` (A1), `funding/funding_zscore` (A4), `funding/base_convergence`
(A5), `funding/carry_position_lifecycle`, `funding/carry_positions_store`,
`backtesting/maker_rebate_decision` (D17), `backtesting/perf_metrics` (Q1), plus les jumeaux
pré-existants `copying/kelly_sizing` et `simulation/pnl_attribution` (voir collisions ci-dessous).

### Backlog de câblage — priorisé par SERVICE À L'OBJECTIF (PnL net)

Le tri n'est pas « par ordre alphabétique » mais **par ce qui rend les trades plus propres sans
fabriquer d'edge** :

**Priorité 1 — FILTRES (peuvent seulement refuser de mauvais trades → « moins, plus propres »,
risque quasi nul, alignés doctrine).** À câbler dans la porte de décision :
`execution/freshness_cut` (L5), `realtime/tick_quality_guard` (G4), `market/universe_guard` (S2),
`risk/portfolio_risk_limits` (M1/M2), `risk/carry_risk_gates` (M4/M5), `risk/safety_gates_mm`,
`risk/drawdown_scaling` (S5), `risk/margin_reserve` (S6), `signals/crowding` (S4),
`signals/session_conditioning` (G3), `copy_wallet/structural_wallet_filter` (G5),
`copy_wallet/leader_markout` (C12/13), `risk/budget_turnover` (E24).

**Priorité 2 — SIGNAUX candidats (peuvent AJOUTER de l'edge, mais à PROUVER OOS avant de câbler —
notre loi : jamais brancher un signal non validé).** `signals/microstructure_signals`,
`signals/cross_sectional_momentum`, `signals/funding_reversal`, `signals/vol_regime_signal`,
`backtesting/post_liquidation_direction`, `backtesting/residual_alpha`, `signals/orthogonalize`.

**Priorité 3 — MODÉLISATION (n'a de sens qu'APRÈS que le feature-store coule en prod).**
`features/feature_store`, `features/feature_normalize`, `features/feature_multitimeframe`,
`features/feature_drift`, `modeling/linear_baseline`, `modeling/ridge_regression`,
`modeling/probability_calibration`, `modeling/model_refit`.

**Priorité 4 — ANALYTIQUE / SUPERVISION (à brancher sur dashboard+audit, faible risque).**
`analysis/pnl_attribution`, `ops/strategy_monitoring`, `ops/clock_integrity`,
`backtesting/monte_carlo`, `backtesting/promotion_gate` (H1→F30 via `survival_gate`),
`backtesting/survival_gate`, `risk/allocator`, `risk/kelly_sizing`,
`execution/maker_taker`, `execution/anti_gaming`, `execution/execution_passive_agressive`,
`copy_wallet/wallet_consensus`.

**Intentionnellement NON câblé (correct)** : `funding/spot_yield` (A6) est **gaté OFF** par design
(staker verrouille le spot vs carry exit-rapide) — orphelin *volontaire*, deny-by-default.
`funding/carry_rotation` (A7) : la logique de rotation vit déjà dans `carry_positions_store`
(hysteresis inlined) ; le module reste comme référence testée → à fusionner ou marquer.

## Collisions de nom (29 stems partagés) — dette de déduplication

L'audit a trouvé **29 noms de fichier portés par ≥ 2 modules**. Deux familles :

**(a) Doublons que J'AI introduits cette session** (contraire à CLAUDE.md « pas de doublons ;
renforcer l'existant ») — **à réconcilier, pas à supprimer brutalement** :
- `kelly_sizing` : `copying/` (pré-existant, CÂBLÉ) vs `risk/` (neuf, testé) → vérifier
  recouvrement, garder un seul.
- `pnl_attribution` : `simulation/` (CÂBLÉ) vs `analysis/` (neuf) → idem.
- `promotion_gate` : `ml/` (pré-existant) vs `backtesting/` (neuf) → idem.
- `monte_carlo` : `backtest/` (vieux, ORPHELIN) vs `backtesting/` (neuf).

**(b) Deux paquets backtest parallèles** : `backtest/` (vieux : `monte_carlo`, `replay_engine`,
`cost_model`, `runtime_parity` — tous ORPHELINS) vs `backtesting/` (vivant). C'est le « ne pas
introduire de 3ᵉ architecture » qui se rejoue au niveau paquet. **Décision recommandée** :
`backtest/` (vieux) est candidat à l'enterrement documenté (git garde tout) une fois vérifié
qu'aucune porte ne l'atteint (il est déjà classé ORPHELIN ici).

Les autres collisions (`circuit_breaker`×4, `models`×5, `slippage_model`×4…) sont probablement
légitimes (même rôle, paquets distincts) — à confirmer au cas par cas, hors urgence.

## Verdict S7

1. **La maladie est réelle et mesurée** : 28,6 % du code est testé-mais-non-branché. Chiffre de
   référence à faire **baisser**, audit après audit.
2. **Cette session a ajouté 44 briques latentes.** Honnêtes, testées — mais **la valeur n'existera
   qu'au câblage**. Le prochain gros levier n'est pas « coder plus », c'est **brancher les filtres
   Priorité 1 dans la porte de décision** et **valider OOS les signaux Priorité 2 avant de les
   brancher**.
3. **Dette de doublons à solder** (kelly/pnl_attribution/promotion_gate/monte_carlo + paquet
   `backtest/` orphelin), proprement, sans suppression brutale.
4. **Vérité complète = Windows** (`TEST-AUDIT-complet.cmd`). S7 mesure l'atteignabilité par import ;
   le « vraiment appelé sur le chemin edge→ledger » se prouve par le cluster V.

*Rappel doctrine : une capacité testée n'est pas un PnL ; un import n'est pas un appel ; « mention
≠ porte ». On ne se ment pas sur ce qui tourne.*

---

## MàJ 2026-07-18 (soir) — 1re vague de câblage (X1) : la maladie recule, mesurée

Suite à « tout brancher / 100 % câblé » : création du **pipeline de filtres composable**
`src/hl_observer/gating/filter_pipeline.py`, branché à UN point de la porte LIVE
`pipeline/v12_decision_pipeline.py` (helper `_appliquer_gardes`, appelé sur chaque entrée).

**7 gardes P1 passés TESTÉ-SEULEMENT → CÂBLÉ-ET-CONSOMMÉS** (leur refus dégrade l'edge sous le
plancher → NO_TRADE par le même chemin que l'edge) : `universe_guard` (S2), `session_conditioning`
(G3), `freshness_cut` (L5), `structural_wallet_filter` (G5), `tick_quality_guard` (G4),
`margin_reserve` (S6), `crowding` (S4) — plus `filter_pipeline` lui-même.

**Compteur global : TESTÉ-SEULEMENT 273 (28,6 %) → 266 (27,9 %) ; CÂBLÉ 604 → 612.** Briques de
session câblées : 9 → 16. Mesure rejouée par `tools/audit_cablage_modules.py`.

**Honnêteté sur l'ACTIF vs l'ARMÉ** (un garde câblé n'est actif que si son entrée arrive) :
- **ACTIF maintenant** au seam v12 : `freshness_cut` (âge = observed_at − source_ts venue) et
  `session_conditioning` (permissif par défaut). Un signal > 120 s → NO_TRADE `SIGNAL_TROP_VIEUX`,
  prouvé par test.
- **ARMÉ** (abstient jusqu'à ce que son entrée soit plombée — X2) : `structural_wallet_filter`
  (wallet_stats), `tick_quality_guard` (prix de référence), `margin_reserve` (marge/capital),
  `crowding` (historique d'edge). `universe_guard` est présent mais redondant à ce seam (un coin
  sans mid est déjà NO_TRADE) — il mordra sur d'autres seams.

Anti-régression : **invariant AST** (`tests/test_v12_pipeline_gardes_cablees.py`) — la porte DOIT
importer et appeler `appliquer_filtres`/`_appliquer_gardes`, sinon le test casse.

**Cap honnête vers 100 %** : X2 (plomber les entrées → activer les 4 armés), X3 (brancher le
sizing drawdown/vol DANS apply_delta — sortie consommée, pas jetée), puis signaux (validés OOS
d'abord) et modélisation (après le feature-store). On fait BAISSER le 27,9 % vague après vague,
sans jamais gonfler le compte par un import non appelé.

---

## MàJ 2026-07-18 (soir, 2) — X2 (activer les armés) + X3 (sizing consommé)

- **X2** : la porte alimente désormais le `ContexteDecision` avec des entrées RÉELLES —
  `wallet_stats`, `reference_mids`, `edge_history_by_coin` (nouveaux champs optionnels de
  `V12DecisionPipelineInput`) + **capital / marge utilisée / drawdown dérivés de l'état RÉEL du
  moteur** (`_etat_moteur` : `cash_usdt`, `realized_pnl_usdt`, `_high_water_equity`,
  `config.leverage`, `config.max_total_exposure_usdt`, `positions[].notional_usdt`). `margin_reserve`
  (S6) est maintenant ACTIF depuis l'état moteur ; `structural_wallet`, `stale-tick`, `crowding`
  s'activent dès que le caller fournit leur entrée. Absente → abstention (jamais fabriqué).
- **X3** : `_facteur_sizing` = `drawdown_scaling.facteur_capital(drawdown)` passé en **`margin_scale`**
  à `apply_delta` (hook existant, clampé [0,1]) → en drawdown la taille rétrécit continûment. Sortie
  CONSOMMÉE (anti « mesuré puis jeté », V5). drawdown 0 → 1.0 (rétro-compatible).

Compteur : TESTÉ-SEULEMENT **266 → 265 (27,7 %)** ; CÂBLÉ **612 → 613** (`drawdown_scaling`).
Invariant AST étendu : la porte doit appeler `_etat_moteur` ET `_facteur_sizing`. Tests : 30 verts
(gardes+sizing+non-régression v12) ; paper_ledger/reconciliation verts. PAPER only, 0 ordre.
