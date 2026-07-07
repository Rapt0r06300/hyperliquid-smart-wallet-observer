# AUDIT — Inspection repos GitHub pour ROADMAP V26 (2026-07-03)

Règle appliquée : ne jamais prétendre avoir lu un fichier non lu. Ci-dessous, la liste exacte des lectures ayant fondé `docs/HYPERSMART_FUSION_ROADMAP_V26.md`.
Méthode : `LU` = fichier lu intégralement ou en larges sections ; `EXTRAIT` = lignes ciblées via grep/head (signatures, seuils) ; `LISTÉ` = arborescence + README seulement.

## Lectures par repo (racine : `runtime/research/github_repos_v24/`)

| Repo | Fichiers | Mode |
|---|---|---|
| 32_gajesh2007_funding_arb_bot | `src/strategy/engine.ts` (231 l.), `src/strategy/funding-history.ts` (182 l.) | LU |
| | `src/execution/risk.ts` (520 l.) | EXTRAIT (kill-switch, liq distance, drift, seuils l.78-130, 263-284) |
| | README, arborescence src/ complète | LISTÉ |
| 30_rustjesty_hyperliquid_drift_arbitrage_bot | `strategies/funding.py` (126 l.) | LU |
| | `strategies/basis.py` (110 l.) | LU (110 premières lignes, hors fin de fichier) |
| | README, arborescence | LISTÉ |
| 35_enarjord_passivbot | `passivbot-rust/src/trailing.rs` (183 l.) | LU |
| | `docs/risk_management.md` (l.1-80 : WE/WEL/auto-unstuck/enforcers), `docs/equity_hard_stop_loss.md` (l.1-60) | LU (sections) |
| | arborescence `passivbot-rust/src/` + `docs/` + README | LISTÉ |
| 33_hummingbot | `strategy_v2/executors/position_executor/data_types.py` (59 l.) | LU |
| | `strategy_v2/controllers/directional_trading_controller_base.py` | EXTRAIT (cooldown/max_executors l.37-195) |
| | arborescence executors/ | LISTÉ |
| 22_freqtrade | `plugins/protections/stoploss_guard.py`, `low_profit_pairs.py`, `max_drawdown_protection.py`, `cooldown_period.py` | EXTRAIT (paramètres + logique de refus) |
| | arborescence `plugins/pairlist/` (22 filtres) | LISTÉ |
| | Note : `freqtrade/edge/` absent du clone (supprimé upstream) — constaté, non inventé. |
| 25_djienne_polymarket_bot | `core/kelly.py` (l.1-200 : formule, garde-fous) | LU |
| | `core/auto_optimizer.py` | EXTRAIT (classes, bornes params l.1-192) |
| | arborescence core/ + README | LISTÉ |
| 17_rezzecup_whale_wallet_mirror_copy_trader | `core/scorer.py` (47 l.), `core/risk_gate.py` (65 l.), `execution/mirror_engine.py` (60 l.) | LU |
| 38_chainstacklabs_hyperliquid_trading_bot | `src/core/risk_manager.py` | EXTRAIT (RiskRule, ROE signé, max_drawdown l.4-265) |
| | arborescence src/ + learning_examples/ | LISTÉ |
| 28_jackhuang166_hyberliquid_arbitrage_bot | `src/spread/comparePrice.ts` (42 l.) | LU |
| 29_jackhuang166_hyberliquid_arbitrage | diff structurel vs 28 (mêmes fichiers) | LISTÉ |
| 31_notlelouch_arbibot | `internal/arbitrage/arbitrage.go` | EXTRAIT (signatures FindBestPrices, CalculateNetProfitPercentage) |
| 15 / 16 (Solana copy bots) | arborescence (5 fichiers TS identiques) + README | LISTÉ |
| 20_warp_id_solana_trading_bot | arborescence filters/ + README | LISTÉ |
| 21_tony_42069_trader_tony_v4 | arborescence src/ + README | LISTÉ |
| 24_jlowo_gengar_polymarket_bot | arborescence + README (oracle lag) | LISTÉ |
| 26_jonmaa_btc_polymarket_bot | arborescence + README | LISTÉ |
| 27_carlosibcu_polymarket_kalshi | arborescence backend/ + README | LISTÉ |
| 34_drakkar_triangular_arbitrage | arborescence + README | LISTÉ |
| 36_pydevtop | contenu complet (README + LICENSE, zéro code) | LISTÉ |
| 37_ramilexe_crypto_arbitrage_bot | arborescence src/ + README | LISTÉ |
| 23_octobot | racine + recherche de code trading (absent du clone : packages pip séparés) | LISTÉ |

## Repos indisponibles (constaté le 2026-07-03)
- 18 Neron888/Polymarket-copy-trading-bot — clone refusé (auth requise = supprimé/privé), page GitHub vide.
- 19 terauss/Polymarket-Copy-Trading-Bot — idem.
- 39 RuggedJar/hyperliquid-trader — idem (retesté avec GIT_TERMINAL_PROMPT=0).
- Résidus : dossiers `18_*`, `19_*`, `39_*` contiennent un `.git` husk non supprimable via le mount (locks Windows). Sans impact ; à nettoyer côté Windows si souhaité.

## Nouveau repo ajouté
- `38_chainstacklabs_hyperliquid_trading_bot` cloné (depth 1, .git retiré), copié dans `github_repos_v24/`. `EXTERNAL_REPOS_MANIFEST.json` non modifié (généré par un outil PowerShell externe).

## Vérifications côté `src/hl_observer` (pour le constat « modules dormants »)
- `risk/atr_trailing_stop.py` : aucun import trouvé (grep sur tout src/hl_observer, hors __pycache__).
- `funding/*` importé par : `arbitrage/hyperliquid_cex_spread_scanner.py`, `cli.py`, `paper_trading/funding_payment_tracker.py`, `refactor_fusion/runner.py`, `strategies/external_simulation_bus.py`, `strategies/fusion_runtime.py`.
- Kelly présent : `risk/kelly_sizer.py`, `copying/kelly_sizing.py`, `risk/tiered_copy_sizing.py`.
- `unstuck` : zéro occurrence dans src/hl_observer → comportement manquant confirmé.
- Reason V25 `EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS` localisée dans `ui/routes.py` (gros fichier — ne pas éditer directement).

## Sécurité
Session 100 % lecture + rédaction de docs. 0 ordre réel, 0 argent réel, 0 clé privée, 0 signature, 0 dépôt/retrait, 0 appel privé.

---

# ANNEXE — Implémentation V26-L1 (2026-07-04)

## Fichiers créés
- `src/hl_observer/signals/v26_entry_vetos.py` — EdgeTrendRecorder (clé COIN|SIDE, NaN/Inf-safe), `funding_sanity` (warmup/spike z-score 2σ), `apply_v26_entry_vetos` (hook scorer, opt-in `HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE`, sous-flags `HYPERSMART_V26_FUNDING_VETO` / `HYPERSMART_V26_EDGE_TREND_VETO`).
- `src/hl_observer/funding/funding_runtime_cache.py` — cache rolling thread-safe {coin → (ts, rate)}, fenêtre 24 h, état vide honnête.
- `tests/test_v26_l1_entry_vetos.py` — 23 tests.

## Fichiers modifiés (additif)
- `signals/no_trade_taxonomy.py` : +3 codes (`FUNDING_SPIKE` BLOCK, `FUNDING_HISTORY_WARMUP` WARN, `EDGE_TRENDING_DOWN` BLOCK).
- `signals/copy_decision.py` : +3 champs optionnels neutres (None ne bloque jamais) + checks 9 (funding sain) et 10 (edge stable).
- `copying/realtime_magic_score.py` : +champ `coin: str = ""` (optionnel) + hook V26 fail-safe avant dédup des raisons. Flag OFF ⇒ comportement V25 strictement inchangé (testé).
- `signals/shadow_wiring.py` : exposition read-only `shadow_edge_trend`, `shadow_funding_ok/code/z`.
- `tests/test_v12_no_trade_taxonomy.py` : bloc `_V26_L1` déclaré, total 60 → 63.

## Incident technique (résolu, gotcha connu)
Les fichiers modifiés via Edit sont apparus tronqués côté sandbox pytest (vue mount périmée : `copy_decision.py` coupé l.101, taxonomie l.182, scorer l.313). Remède mémoire appliqué : réécriture write-through intégrale via heredoc bash + purge `__pycache__`. Vérité Windows jamais corrompue (contrôlée par lecture complète avant réécriture).

## Tests lancés (sandbox, PYTHONPATH=src)
- `tests/test_v26_l1_entry_vetos.py` : **23 passed**.
- Non-régression fichiers touchés (`test_realtime_magic_score`, `test_v12_copy_decision`, `test_v12_no_trade_taxonomy`, `test_v13_shadow_wiring`, `test_realtime_liquidity_market_gate`, `test_simulation_live_filters`, `test_strict_md_accept_path` + L1) : **91 passed**.
- Sous-ensemble sécurité CLAUDE.md (error_handler, circuit_breaker, retry_policy, state_manager, no_real_trade_foundations, paper_ledger, pnl_reconciliation, orderbook_execution_simulator, simulation_realism_audit) : **19 passed**.
- Pré-existant non lié : `tests/test_fresh_opportunity.py` ne collecte pas dans le sandbox (`ModuleNotFoundError: websockets` — artefact d'environnement, cf. gotcha socksio).

## PARTIAL_NOT_WIRED — 2 branchements à faire côté Windows (routes.py interdit d'édition ici)
Dans `src/hl_observer/ui/routes.py`, construction de `RealtimeCopyScoreInput(...)` (~l.1090-1113) :
```python
    coin=str(row.coin),   # V26 L1 : active le veto tendance d'edge par marché
```
Alimentation funding (au point où le funding est déjà fetché, ou via le scanner funding) :
```python
from hl_observer.funding.funding_runtime_cache import push as funding_push
funding_push(coin, funding_rate)  # taux public réel uniquement
```
Activation (après ces 2 lignes) : `HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE=1` dans le launcher. Sans le flag : zéro changement de comportement (prouvé par test).

## Constat L1 — walk-the-book
Le chemin autoritatif (`RealtimeCopyRiskConfig`) coûte le slippage/spread en CONSTANTES (2.5/3.0 bps) ; `arbitrage/orderbook_depth_pricer.py` reste hors du hot path. → planifié L2.

## Sécurité L1
0 ordre réel, 0 endpoint privé, 0 clé, 0 signature. Nouveaux modules purs (aucun import réseau — vérifié par test `test_no_real_trade_surface_in_new_modules`). Un veto = NO_TRADE simulé, jamais un ordre.

---

# ANNEXE 2 — Branchements L1 + Implémentation V26-L2 (2026-07-04, suite « les deux »)

## Branchements L1 (désormais CÂBLÉ, plus de PARTIAL)
- `ui/routes.py` l.1113 : `coin=str(row.coin),` ajouté dans `RealtimeCopyScoreInput(...)` par patch chirurgical python (ancre unique vérifiée, +1 ligne, py_compile OK). Backup : `runtime/backups/routes_py_avant_v26_branchement_20260704.bak`. Dérogation assumée à la règle « ne pas éditer routes.py » : demande explicite de l'utilisateur, méthode write-through anti-troncature (le gotcha venait des edits via l'outil Edit, pas des écritures python complètes).
- `funding/funding_poller.py` (nouveau) : poller PUBLIC `/info metaAndAssetCtxs` → `funding_runtime_cache`. Opt-in strict `HYPERSMART_V26_FUNDING_POLLER=1` (défaut : aucun thread, aucun réseau). Démarrage paresseux depuis `apply_v26_entry_vetos` (flag maître requis). Parse défensif : forme inattendue ⇒ 0 push (état vide honnête).

## V26-L2 livré
- `paper_trading/vol_adjusted_barriers.py` : MidVolEstimator (range bps par coin sur marks réels, fenêtre 15 min, min 5 obs), `vol_factor_for_coin` (clamp [0.5, 2.5], réf 40 bps), `adjust_config` (SL/TP/trailing/activation × facteur, plancher SL 12 bps), `apply_sltp_exits_vol_adjusted` (wrapper drop-in, flag OFF = passthrough exact — testé). Les événements ledger portent les barrières AJUSTÉES + `vol_factor` (traçabilité audit=dashboard).
- Câblage par alias d'import (import inchangé au site d'appel) : `ui/status_routes.py` (chemin FAST_STATUS_MARK_TO_MARKET actif) et `ui/routes.py` l.2159. Backups : `runtime/backups/*_avant_v26_L2_20260704.bak`.
- `.env.example` : bloc V26 complet ajouté (tous flags OFF par défaut).

## Walk-the-book (scorer) — DEFERRED_WITH_PLAN (vérifié, pas simulé)
- Confirmé : `l2Book` fetché dans `collection/collector.py`, `copying/simulation_pipeline.py`, `copying/runtime_v9_adapter.py`, `autoscan.py`, `cli.py` ; le côté exécution paper consomme des niveaux (`exec_model.py`, `liquidity_route_simulator.py`, `orderbook_depth_pricer.py`).
- Manquant : aucun snapshot carnet dans la boucle de scan de `routes.py` (spread/slippage du scorer = constantes de `RealtimeCopyRiskConfig`). Plan : router un snapshot par coin dans la boucle → `orderbook_depth_pricer` → `spread_bps`/`slippage_bps` dynamiques. Lot dédié.

## Tests (sandbox, PYTHONPATH=src)
- `test_v26_l1_entry_vetos.py` (26 dont 3 poller mockés, sans réseau) + `test_v26_l2_vol_barriers.py` (12) + non-régression (magic_score, copy_decision, taxonomie, shadow_wiring, liquidity_gate, live_filters, strict_md) : **106 passed**.
- Sous-ensemble sécurité CLAUDE.md : **19 passed**. SLTP existants (`test_v9_sl_tp`, `test_v9_sltp_runtime`, `test_trailing_stop_local`) : **25 passed**.

## Note opérationnelle
Des `.pyc` de `ui/` étaient verrouillés côté Windows pendant la session → le moteur tournait probablement. **Redémarrer le launcher** pour charger les patchs routes/status_routes. Activation : `HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE=1` + `HYPERSMART_V26_FUNDING_POLLER=1` (L1) et `HYPERSMART_V26_VOL_BARRIERS=1` (L2). Tous OFF par défaut = comportement V25 inchangé.

## Sécurité (les deux lots)
0 ordre réel, 0 argent réel, 0 clé privée, 0 signature, 0 dépôt/retrait. Seul ajout réseau : lecture PUBLIQUE opt-in du funding (`/info`), jamais une action. Un close vol-ajusté est un événement paper du ledger, pas un ordre.

---

# ANNEXE 3 — Lots L3→L9 + reliquat (2026-07-04, fin de roadmap V26)

## Fichiers créés
- `risk/protections_v26.py` (L5) — StoplossGuard / LowProfitMarket / WindowedMaxDrawdown, ProtectionsBook nourri du ledger.
- `paper_trading/auto_unstuck.py` (L3) — stuck = sous l'eau ≥120 bps ET âge ≥45 min ; moins-sous-l'eau d'abord ; close partiel 10 % ; budget pertes 10 $/24 h strict (part réduite ou skip si dépassement).
- `risk/graded_halt.py` (L4) — machine GREEN/AMBER/RED, escalade immédiate, désescalade 1 palier/cooldown 45 min, force-exit RED une fois par épisode, jamais de close sans mark.
- `risk/kelly_leader_book.py` (L6) — Kelly fractionné par wallet (0.25, lookback 50, min 10, bornes [0.5, 2.0]). Déviation APEX documentée : edge négatif ⇒ ×0.5.
- `edge/tier_cost_budget.py` (L7) — tiers S/A/B/WATCH (85/70/50), budgets 80/50/30/20 bps + WE/WEL passivbot (`check_add_allowed`).
- `signals/market_quality_score.py` (L8) — score composite (range vol, liquidité, PnL marché), univers top-K avec hystérésis, inconnu ne bloque jamais.
- `paper_trading/v26_exit_pipeline.py` — post-exits : marks recorder (L9), ingestion ledger→books, halt L4 + force-exit, unstuck L3. Fail-safe total.
- `collection/l2_snapshot_cache.py` (reliquat) — `compute_book_costs` (walk-the-book repo 30), cache coûts par coin, poller l2Book PUBLIC opt-in (30 s, ≤12 coins récents).
- `backtesting/ab_flag_replay.py` (L9) — bras A (V26 OFF) vs B (ON) sur candidats+marks enregistrés ; PF/WR/DD/net par bras ; UNMEASURABLE exclus des DEUX bras ; CLI `python -m hl_observer.backtesting.ab_flag_replay`.
- `tests/test_v26_l3_to_l9.py` — 26 tests.

## Fichiers modifiés (write-through, py_compile vérifié à chaque patch)
- `signals/no_trade_taxonomy.py` : +7 codes (STOPLOSS_GUARD_ACTIVE, MARKET_LOW_PROFIT_BLOCKED, WINDOWED_DRAWDOWN_HALT, GRADED_HALT_AMBER, GRADED_HALT_RED, COST_BUDGET_EXCEEDED, MARKET_QUALITY_LOW) → 70 codes ; test de couverture mis à jour.
- `signals/v26_entry_vetos.py` : hub réécrit — compose L1+L4+L5+L7+L8 (flags séparés) + snapshot recorder L9 + démarrage paresseux pollers funding/carnet + `coins()`.
- `copying/realtime_magic_score.py` : champ `leader_wallet` ; coûts carnet LIVE (spread/slippage) quand cache frais + flag, sinon constantes V25 ; multiplicateur Kelly L6 ; snapshot L9.
- `paper_trading/vol_adjusted_barriers.py` : façade → `_impl` + `run_v26_exit_pipeline` (fail-safe).
- `ui/routes.py` : +1 ligne `leader_wallet=str(getattr(row, 'wallet_address', ...))` (ancre unique, backup déjà en place).
- `.env.example` : bloc V26 L3→L9 complet (tous OFF).

## Tests (sandbox, PYTHONPATH=src)
- V26 L1+L2+L3→L9 + non-régression fichiers touchés + SLTP existants : **157 passed**.
- Sous-ensemble sécurité CLAUDE.md : **19 passed**.
- Bugs corrigés en cours de route : ligne invalide dans un test L6 (syntaxe), ordre des garde-fous Kelly (perdant prouvé → réduit), fixture unstuck avalée par le SL de base (SL élargi dans le test).

## Limites honnêtes
- L9 nécessite des données ENREGISTRÉES réelles (flag recorder ON puis 24-48 h de collecte) avant de produire un rapport significatif — le harnais est testé sur fixtures, pas encore sur données réelles.
- Le replay L9 mesure les vetos d'entrée + barrières vol ; halt gradué et qualité marché (états runtime) sont OFF par défaut dans le bras B.
- WE/WEL (L7) : librairie + tests livrés ; le cap d'exposition existant du scorer reste la limite active (pas de double comptage).
- Redémarrage du launcher requis pour charger routes.py/scorer patchés.

## Sécurité (fin de roadmap)
0 ordre réel, 0 argent réel, 0 clé privée, 0 signature, 0 dépôt/retrait. Ajouts réseau = 2 pollers PUBLICS opt-in en lecture seule (funding, l2Book). Unstuck/force-exit/closes = événements paper du ledger, jamais des ordres.
