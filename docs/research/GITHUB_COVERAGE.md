# HyperSmart — Couverture GitHub (F1/F2/F3)

_Généré 2026-07-01. Read-only / paper-only. Preuve de câblage, pas de promesse de PnL._

## Méthode
Pour chaque idée de `HYPERSMART_V24_MODULE_PORTAGE_MATRIX.md`, on vérifie que le
module cible **existe** dans `src/hl_observer` ET qu'il est **référencé/importé
ailleurs** que dans son propre fichier (preuve de câblage, anti-orphelin). Le
comptage `REFS` = nombre de fichiers `.py` du runtime qui importent/citent le module.

## Résultat global
- Modules cibles vérifiés : **51**
- Présents : **51/51** (le seul « manquant » de la matrice, `risk/depth_guard.py`,
  existe en réalité sous `signals/depth_guard.py` + `signals/depth_spread_gate.py`
  — erreur de chemin dans la matrice, corrigée ici).
- **Orphelins : 0** — chaque module porté est appelé dans au moins un autre module.
- Repos externes installés : **34/37** (3 en 404 GitHub), et **34/34 exécutés**
  par le bus de simulation (`ui/fusion_persistent_adapter.py`, trace
  `ENGINE_EVALUATION`, code upstream intact sous `runtime/research/github_repos_v24`).

## Table de câblage (extrait, REFS = fichiers qui l'importent)
| Idée / repo source | Module cible | REFS | Statut |
|---|---|---|---|
| Rezzecup mirror / Immutal0 | wallets/leader_hotness.py | 2 | WIRED |
| Rezzecup smart-money | scoring/wallet_score_v2.py | 4 | WIRED |
| tony-42069 SL/TP/flags | signals/entry_quality_gate.py | 3 | WIRED |
| tony-42069 SL/TP | paper_trading/sltp_runtime.py | 4 | WIRED |
| terauss hot/research split | copying/simulation_pipeline.py | 3 | WIRED |
| terauss dedupe/ledger | evidence/decision_ledger.py | 5 | WIRED |
| freqtrade hyperopt | optimization/profit_optimizer.py | 14 | WIRED |
| freqtrade lookahead | backtest/no_lookahead_guard.py | 4 | WIRED |
| ChainInsighter latence | realtime/latency_report.py | 4 | WIRED |
| ChainInsighter session | runtime/session_logs.py | 4 | WIRED |
| Jackhuang arb HL / pydevtop | features/basis.py | 1 | WIRED |
| Jackhuang / Composio / Carlos | signals/source_reconcile.py | 2 | WIRED |
| rustjesty ConnectorBase | connectors/base.py | 3 | WIRED |
| rustjesty reconciliation | normalization/reconcile.py | 3 | WIRED |
| hummingbot connector | connectors/hyperliquid_readonly.py | 2 | WIRED |
| hummingbot / passivbot | strategies/paper_registry.py | 3 | WIRED |
| ArbiBot low-latency WS | realtime_monitor/ws_supervisor.py | 1 | WIRED |
| ArbiBot rate budget | scanner/rate_limit_semaphore.py | 1 | WIRED |
| gajesh funding | features/funding.py | 4 | WIRED |
| gajesh kill switch | risk/loss_halts.py | 1 | WIRED |
| Drakkar / octobot | strategies/library.py | 2 | WIRED |
| CloddsBot calibration | calibration/confidence_buckets.py | 4 | WIRED |
| CloddsBot VaR/CVaR | risk/var_cvar.py | 3 | WIRED |
| Harrier OBI | features/orderbook_imbalance.py | 3 | WIRED |
| Harrier depth guard | signals/depth_guard.py (+depth_spread_gate.py) | 7 | WIRED |
| MrFadiAi smart-money | scoring/smart_money_filter.py | 2 | WIRED |
| MrFadiAi adaptive sizing | risk/adaptive_sizing.py | 3 | WIRED |
| lihanyu fill tracker | normalization/fill_inference.py | 2 | WIRED |
| lihanyu cooldown | copy_mode/cooldown.py | 1 | WIRED |
| PolyWeather SSE | ui/sse_events.py | 1 | WIRED |
| PolyWeather freshness | realtime/freshness_audit.py | 2 | WIRED |
| Composio eligibility | signals/eligibility.py | 1 | WIRED |
| aarora wallet labels | scoring/wallet_labels.py | 1 | WIRED |
| polyterm agent-safe | agent_tools/manifest.py | 5 | WIRED |
| polyterm mcp | agent_tools/mcp_readonly.py | 1 | WIRED |
| mlmodelpoly fair value | edge/fair_value.py | 1 | WIRED |
| mlmodelpoly features | features/microstructure.py | 1 | WIRED |
| polyrec scan schema | features/scan_features_schema.py | 3 | WIRED |
| polyrec replay | backtest/ledger_replay_v9.py | 1 | WIRED |
| ent0n29 runtime modes | runtime_mode.py | 2 | WIRED |
| ent0n29 run context | storage/run_context.py | 13 | WIRED |
| Polymarket agents | agent_tools/readonly_inspectors.py | 3 | WIRED |
| Polymarket agents research | research/local_llm_explainer.py | 3 | WIRED |
| Immutal0 / Jonmaa risk | risk/risk_engine_v3.py | 7 | WIRED |
| Neron888 copy loop | copying/signal_detector.py | 4 | WIRED |
| warp-id risk gates | risk/gates.py | 18 | WIRED |
| evan-kolberg Brier | calibration/brier.py | 3 | WIRED |
| evan-kolberg runner | backtest/experiment_runner.py | 2 | WIRED |
| djienne logging | simulation/log_metrics.py | 7 | WIRED |
| passivbot exposure | risk/correlated_exposure.py | 1 | WIRED |
| ramilexe opportunity % | edge/edge_calculator.py | 3 | WIRED |

## Conclusion F1/F2/F3
- **F1 (idée par idée)** : chaque repo de la matrice V24 a son comportement porté
  dans un module réel du runtime. DONE.
- **F2 (anti-orphelin)** : 0 orphelin ; tous les modules portés sont importés
  ailleurs. Les 34 profils externes tournent aussi via le bus (`ENGINE_EVALUATION`). DONE.
- **F3 (couverture)** : ce document. Reste à enrichir par colonne « test cible »
  et « visible dashboard » (croisé avec la suite de tests et les panneaux) — suivi
  dans F3 bis.

## Réserves honnêtes
- REFS ≥ 1 prouve un câblage d'import, pas que le module soit sur le **hot-path**
  autoritatif (certains restent en shadow, cf. bloc H3). La promotion shadow→auto
  n'est PAS supposée par ce tableau.
- Les flux arbitrage/funding restent parfois `fixture-labeled` faute de 2e source
  live — cf. B3/B4.
