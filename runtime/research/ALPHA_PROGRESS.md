# ALPHA PROGRESS — reprise en <2 min

CURRENT_TASK : (aucune en cours)
LAST_COMMIT  : 4f535e3 (CI P11/P64)
TESTS        : suite recherche verte (~118 tests) ; test de couverture P58 garde 48 modules Factory
RESULT       : LABORATOIRE COMPLET (P65 acceptance = DONE_GLOBAL : 0 critere manquant, 3 blocages DONNEES documentes). 0 candidat alpha net-positif PROUVE : la decouverte attend la DONNEE (collecte cote user).
NEXT_TASK    : DECOUVERTE des que la data HF simultanee existe -> relancer run_factory + modules par famille. CI (P11/P64) livree: deplacer tools/ci/alpha-factory.yml -> .github/workflows/ (chemin protege).
BLOCKERS     : data_hf, wallets_scalables (node_fills), l4 = collecte cote user (pas de reseau ici). Interfaces pretes (hf_recorder, multi_venue, order_intent, wallet_population streaming).

## Etat des TASKS
- DONE : 55   MORE_DATA : 6   BLOCKED_EXTERNAL : 5   TODO : 0  (tout le finissable est fait ; reste = collecte data + discovery)
- Acceptance P65 : DONE_GLOBAL | satisfaits: factory_exhaustive/twap/maker/couts/oos/forward/adverse/capacity/capital ; bloques documentes: data_hf, wallets_scalables, l4

## Couche complete livree (toutes testees)
Discipline: cost_model, validation_gates(cost-aware/early-stop/multiple-testing), basis_vs_latency, recette_economique,
  search_space, alpha_decay, research_backlog, factory coverage, reproducibility.
Metriques/logique: deconfliction, meta_gate, wallet_info_ratio, capital_efficiency, daily_report, drift_detector.
Execution/liquidite: fee_regime, liquidity_consumption, capacity_curve, exit_factory, maker_toxicity, queue_model,
  book_resiliency, spread_transition.
Familles recherche: price_discovery, cross_asset_leadlag, universal_micro, nonlinear_challenger, metaorder_hazard,
  liquidation_flow, cascade_warning, clock_regimes, wallet_fingerprint, abnormal_regime, hidden_vs_twap, trigger_map.
Data/infra (interface, capture BLOCKED cote user): hf_recorder, multi_venue/NBBO, lineage.
Validation/runtime/portfolio: forward_frozen, purged_cv, sizing, portfolio, feature_cache, replay_consistency,
  runtime_loop, parallel_factory, factory_families, acceptance.

## Deja PROUVE (ne pas refaire sans nouvelle donnee/hypothese)
- BTC lead-lag taker: KILL | OFI/microprice L1: gross<cout (KILL) | MLOFI: math prete, data-limited
- cross-venue gap<cout / basis persistant (autocorr 0.63-0.94): KILL / DISABLED_BY_SCOPE
- wallet '+58bps' 0x1e9b: PUMP artefact (3 votes, conc 0.79) | population 27: 0 candidat | P2 anticipation: MORE_DATA (27min overlap)

## Regles actives
- 1 task = 1 commit (batches thematiques quand tests partages) ; JAMAIS push (l'user pousse) ; commit via plomberie git (mount interdit unlink index.lock)
- PROMOTE seulement si net>0 & LCB>0 & OOS>0 & forward>0 & couts complets & survit ADVERSE_P95 & passe multiple-testing & capacity/concentration OK
- carry/funding = DISABLED_BY_SCOPE ; PAPER/READ-ONLY (0 ordre reel) ; jamais fabriquer du vert
