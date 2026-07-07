# HyperSmart - audit runtime des GitHub externes

Date: 2026-06-29

## Résumé factuel

- Repos demandés dans le bridge: 37.
- Repos présents dans le manifest local: 37.
- Repos clonés/installés localement avec `.git`: 34.
- Repos non clonables depuis cette machine: 3.
- Profils paper activés: 34.
- Profils paper indisponibles: 3.
- Tous les profils installés sont maintenant appelés par le bus de simulation `external_simulation_bus`.
- Le bus est non bloquant: un `NO_TRADE` de diagnostic ne neutralise pas les réglages/profils GitHub qui produisent déjà une décision paper acceptée.

## Ce que signifie "fonctionnel" dans HyperSmart

HyperSmart ne lance pas les bots upstream en mode natif, car plusieurs repos contiennent ou peuvent contenir de l'exécution réelle, des dépendances incompatibles, des secrets ou des connecteurs d'échanges externes. La version sûre et testée est:

1. le repo upstream est installé sous `runtime/research/github_repos_v24`;
2. le bridge `external_github_bridge` déclare son profil paper;
3. le runtime `fusion_runtime` charge ce profil en priorité;
4. le bus `external_simulation_bus` appelle le profil à chaque run de fusion;
5. le profil produit soit un ordre paper local, soit un diagnostic non bloquant;
6. la simulation UI peut matérialiser les ordres paper compatibles `LONG/SHORT` avec prix réel.

## Repos installés et branchés

| Id | Repo | Statut install | Profil runtime | Fonctionnel simulation |
|---|---|---:|---|---|
| 01 | alsk1992/CloddsBot | OK | `ext_cloddsbot_agentic_research_loop` | Oui, diagnostic/research path non bloquant |
| 02 | HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits | OK | `ext_harrier_toolkit_decision_stack` | Oui, decision stack paper |
| 03 | MrFadiAi/Polymarket-bot | OK | `ext_mrfadiai_copy_rules` | Oui, copy rules paper |
| 04 | lihanyu81/polymarket_lp_tool | OK | `ext_polymarket_lp_liquidity_guard` | Oui, liquidity guard paper |
| 05 | yangyuan-zhen/PolyWeather | OK | `ext_polyweather_context_features` | Oui, context features research |
| 06 | Composio-HQ/polymarket-kalshi-arbitrage-bot | 404 | `ext_composio_cross_market_arb_pending` | Non, upstream indisponible |
| 07 | aarora4/Awesome-Prediction-Market-Tools | OK | `ext_awesome_prediction_tools_index` | Oui, index/research |
| 08 | NYTEMODEONLY/polyterm | OK | `ext_polyterm_terminal_ops` | Oui, terminal/status ops |
| 09 | txbabaxyz/mlmodelpoly | OK | `ext_mlmodelpoly_shadow_score` | Oui, shadow model |
| 10 | txbabaxyz/polyrec | OK | `ext_polyrec_shadow_recommender` | Oui, shadow recommender |
| 11 | evan-kolberg/prediction-market-backtesting | OK | `ext_prediction_market_backtesting_guard` | Oui, backtest guard |
| 12 | ent0n29/polybot | OK | `ext_polybot_lightweight_rules` | Oui, lightweight rules |
| 13 | Polymarket/agents | OK | `ext_polymarket_agents_research_path` | Oui, research path |
| 14 | tradingview/lightweight-charts | OK | `ext_tradingview_chart_runtime` | Oui, chart runtime |
| 15 | ChainInsighter/Solana-Copy-trading-bot | OK | `ext_chaininsighter_priority_copy_session` | Oui, copy session |
| 16 | Immutal0/Solana-CopyTrading-Bot | OK | `ext_immutal0_wallet_filter_caps` | Oui, wallet filters/caps |
| 17 | Rezzecup/whale-wallet-mirror-copy-trader | OK | `ext_rezzecup_whale_mirror_primary` | Oui, priority whale mirror |
| 18 | Neron888/Polymarket-copy-trading-bot | 404 | `ext_neron888_copy_loop_pending` | Non, upstream indisponible |
| 19 | terauss/Polymarket-Copy-Trading-Bot | 404 | `ext_terauss_hot_path_pending` | Non, upstream indisponible |
| 20 | warp-id/solana-trading-bot | OK | `ext_warp_risk_process_caps` | Oui, risk process caps |
| 21 | tony-42069/trader-tony-v4 | OK | `ext_tony_autonomous_sltp_priority` | Oui, SL/TP priority |
| 22 | freqtrade/freqtrade | OK | `ext_freqtrade_backtest_discipline` | Oui, backtest discipline |
| 23 | drakkar-software/octobot | OK | `ext_octobot_framework_priority` | Oui, strategy framework |
| 24 | JLowo/gengar_polymarket_bot | OK | `ext_jlowo_structured_decision` | Oui, structured decisions |
| 25 | djienne/Polymarket-bot | OK | `ext_djienne_resilience_logging` | Oui, resilience/logging |
| 26 | Jonmaa/btc-polymarket-bot | OK | `ext_jonmaa_single_market_rules` | Oui, single-market rules |
| 27 | CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot | OK | `ext_carlos_cross_source_reconcile` | Oui, source reconcile |
| 28 | Jackhuang166/hyberliquid-arbitrage-bot | OK | `ext_jack_hl_arbitrage_spread` | Oui, Hyperliquid arbitrage paper |
| 29 | Jackhuang166/hyberliquid-arbitrage | OK | `ext_jack_hl_arbitrage_alt` | Oui, Hyperliquid arbitrage alt |
| 30 | rustjesty/hyperliquid-drift-arbitrage-bot | OK | `ext_hl_drift_funding_spread` | Oui, funding/spread paper |
| 31 | notlelouch/ArbiBot | OK | `ext_arbibot_cross_exchange_spread` | Oui, cross-exchange spread |
| 32 | gajesh2007/funding-arb-bot | OK | `ext_funding_arb_basis` | Oui, funding arb basis |
| 33 | hummingbot/hummingbot | OK | `ext_hummingbot_market_making_framework` | Oui, market-making framework |
| 34 | Drakkar-Software/Triangular-Arbitrage | OK | `ext_drakkar_triangular_arbitrage` | Oui, triangular arb diagnostic |
| 35 | enarjord/passivbot | OK | `ext_passivbot_grid_risk` | Oui, grid/DCA risk |
| 36 | pydevtop/interexchange-arbitrage-bot | OK | `ext_interexchange_arbitrage` | Oui, interexchange spread |
| 37 | ramilexe/crypto-arbitrage-bot | OK | `ext_crypto_arbitrage_spread` | Oui, crypto spread model |

## Corrections de câblage effectuées

- `src/hl_observer/strategies/external_simulation_bus.py` ajouté.
- `fusion_runtime` appelle maintenant ce bus sur tous les profils installés.
- La limite interne qui ne conservait que les 20 premiers profils externes a été supprimée: tous les profils activés sont visibles.
- Les diagnostics de profil sont séparés de `no_trade_reasons`; ils n'interfèrent pas avec les décisions paper acceptées.
- Les ordres paper acceptés restent prioritaires et peuvent être matérialisés dans la simulation si le format est compatible.

## Vérifications exécutées

- `git ls-remote` sur les 3 URLs échouées: 404 / repository not found.
- `Invoke-WebRequest` GitHub API sur les 3 URLs échouées: 404.
- `codeload.github.com` sur les 3 URLs échouées: 404.
- `python -m pytest -q tests\test_external_github_strategy_bridge.py tests\test_fusion_strategy_runtime.py tests\test_connector_standard.py tests\test_ui_simulation_status_fast.py` -> 31 passed.
- `python -m pytest -q tests\test_hypersmart_v19_repo_coverage.py tests\test_hypersmart_v23_portage_docs.py tests\test_hypersmart_github_fusion.py tests\test_no_external_code_copy_license_markers.py tests\test_hypersmart_v19_no_real_trade.py tests\test_refactor_fusion_no_real_trade_e2e.py` -> 17 passed.
- `python -m hyper_smart_observer.app.main --safety-check` -> OK.
- `python -m hyper_smart_observer.app.main --audit-safety` -> OK.

## Garde-fous confirmés

- Aucune exécution native des bots externes.
- Aucun ordre réel.
- Aucun `/exchange`.
- Aucune clé privée.
- Aucune signature.
- Aucun wallet-connect.
- Simulation locale paper uniquement.
- Données réelles ou état vide honnête.

## Correction 2026-06-30 - ecriture independante vers la simulation

Constat: le bus executait bien les profils installes, mais l'adaptateur
persistant ne materialisait en position paper directe qu'une petite liste de
profils d'arbitrage. Cela pouvait donner une UI affichant "34 actifs" sans que
tous les moteurs aient une trace locale visible dans la simulation.

Correction:

- chaque profil externe installe et execute ecrit maintenant une trace locale
  `ENGINE_EVALUATION` dans le ledger de simulation, avec `profile_id`,
  `repo_id`, `decision`, `reason`, `candidate_count` et
  `accepted_paper_orders`;
- tout profil `ext_*` ou `copy_*` peut materialiser une position paper s'il
  produit deja un ordre paper accepte, avec `paper_only=True`,
  `real_execution=False`, `reference_price>0`, `notional_usdt>0` et side
  `LONG/SHORT`;
- les ordres directs issus de `copy_conflict_resolver` ne peuvent pas ouvrir une
  deuxieme position, car ils doivent rester routes par le `PaperEngine`
  existant;
- les profils upstream restent preserves dans `runtime/research/github_repos_v24`;
  le code upstream n'est pas modifie.

Tests ajoutes:

- `tests/test_fusion_persistent_adapter_external_profiles.py`
  - trace ledger pour chaque profil externe execute meme sans ordre;
  - materialisation paper d'un profil externe non-arbitrage valide;
  - refus d'un ordre externe sans prix de reference reel.

## Prochaine action exacte

1. Redémarrer `LANCER_HYPERSMART.cmd` pour charger le nouveau bus.
2. Observer `/api/simulation/status`: le payload `fusion_runtime.runtime.external_profile_execution_summary` doit afficher tous les profils installés comme exécutés.
3. Si les 3 URLs 404 sont nécessaires, fournir une URL corrigée ou un accès GitHub valide; sans cela, elles ne peuvent pas être installées honnêtement.
