# HyperSmart Observer — CLAUDE_CODE_STEP_PROGRESS

_Mis à jour 2026-06-26. Runtime actif = `src/hl_observer`. Paper-only / read-only. Ne rien supprimer._

## Mise a jour Codex 2026-07-01 - audit PnL/ledger

Cette passe a traite le point critique observe dans la simulation: un PnL positif pouvait apparaitre alors que les logs de decisions et le snapshot portefeuille ne convergeaient pas. Le resultat est volontairement strict:

- **Ledger/SLTP**: correction des fermetures paper dupliquees. Une meme position paper (`matched_position_key` + `source_delta_key`/instance) ne peut plus etre fermee deux fois avec PnL additionnel. Les positions stale rechargees sont nettoyees sans ajouter de gain/perte.
- **Dashboard fast status**: les fermetures dupliquees sont ignorees dans les compteurs `closed_trades`, `winning_trades`, `losing_trades` et dans le PnL realise.
- **Audit PnL**: ajout de `pnl_reliability_status` et `pnl_reliability_findings`. Si les sources sont trop vieilles ou si snapshot/logs divergent, le rapport marque explicitement `STALE`, `DIVERGENT` ou `STALE_AND_DIVERGENT`.
- **Etat observe initial**: le `pnl-audit` local lisait un ancien PnL stale/divergent. Conclusion initiale: **ne pas conclure sur le PnL tant que le launcher n'a pas produit des logs frais convergents**.
- **Safety**: `python -m hl_observer.cli doctor`, `safety-audit`, `audit-safety` passent; aucune execution reelle, aucune cle, aucune signature, aucun ordre.
- **Reduce proportionnel**: correction d'un bug ou un `REDUCE` leader pouvait fermer 100% d'une petite position paper, car la taille leader etait appliquee en absolu au lieu d'etre convertie en fraction de reduction. La position paper reduit maintenant proportionnellement a la baisse de taille leader.
- **Clusters frais**: correction du replay consensus quand les deltas bruts avaient deja ete marques traites. Le delta synthetique `fresh_opportunity_cluster_local_simulation` peut reparer/rejouer l'entree locale sans dupliquer les deltas sources.
- **Edge dollar explicite**: si `HYPERSMART_SIMULATION_MIN_EXPECTED_EDGE_USDT` est defini, le rejet `EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS` reste autoritaire, meme pour un cluster frais. Sans seuil explicite, le garde poussiere par defaut est plus bas pour ne pas affamer une simulation 1000 USDT.
- **Seuil micro-reduce**: `HYPERSMART_MIN_REDUCE_NOTIONAL_USDT` reste disponible, mais le defaut est 0.0 afin que les reductions leader restent visibles dans une petite simulation paper.
- **Lanceur aligne**: `LANCER_HYPERSMART.cmd` et `tools/start_hypersmart_simulation.ps1` ne forcent plus `HYPERSMART_MIN_REDUCE_NOTIONAL_USDT=10`. Le runtime expose aussi `min_reduce_notional_usdt` dans `hypersmart_engine_status.json`, donc un mauvais override devient visible.
- **Audit PnL session complete**: `pnl-audit` lit desormais `simulation_decisions_append_only.jsonl` pour l'historique comptable complet, au lieu de se limiter a `simulation_decisions_latest.jsonl` qui est une fenetre roulante. Le latest reste utilisable pour les vues rapides.
- **Reconciliation latent**: l'audit compare maintenant `snapshot portfolio` a `logs realises + unrealized_pnl`. Une position ouverte qui bouge au vrai prix marche ne declenche plus de faux `DIVERGENT_PNL`.
- **Tolerance live export**: une petite tolerance de synchronisation est appliquee entre snapshot/logs append-only. Les grosses divergences restent signalees comme bugs comptables.

Tests passes pendant cette passe:

- `python -m pytest -q tests/test_v9_sltp_runtime.py tests/test_ui_simulation_status_fast.py` -> 44 passed.
- `python -m pytest -q tests/test_hypersmart_v19_negative_pnl_audit.py` -> 7 passed.
- `python -m pytest -q tests/test_hypersmart_v19_risk_engine_v3.py tests/test_hypersmart_v19_negative_pnl_audit.py` -> 12 passed.
- `python -m pytest -q tests/test_pnl_reconciliation.py tests/test_paper_ledger.py tests/test_paper_engine_ledger_wiring.py tests/test_simulation_v2_normal_pnl_ledger_ui.py tests/test_hypersmart_v19_negative_pnl_audit.py` -> 15 passed.
- `python -m pytest -q tests/test_ui_simulation_persistence.py` -> 36 passed.
- `python -m pytest -q --maxfail=20` -> 2080 passed, 19584 warnings.
- `python -m pytest -q tests/test_hypersmart_v19_negative_pnl_audit.py tests/test_launcher_guards_match_runtime.py tests/test_hypersmart_single_launcher.py` -> 19 passed.
- `python -m pytest -q tests/test_ui_simulation_persistence.py::test_ui_simulation_reduce_is_partial_and_visible_in_fast_status tests/test_ui_simulation_v9_filters.py::test_simulation_skips_orphan_reduce_without_ledger_noise` -> 2 passed.

Controles apres correction:

- `python -m hl_observer.cli doctor` -> OK.
- `python -m hl_observer.cli safety-audit` -> OK.
- `python -m hl_observer.cli audit-safety` -> OK.
- `python -m hl_observer.cli archive-audit` -> rapport genere dans `docs/release/HYPERSMART_ARCHIVE_AUDIT.md`.
- `python -m hl_observer.cli pnl-audit` -> `pnl_reliability_status=OK`, `Divergence equity apres latent=0.000000 USDC` sur les logs frais. Le PnL reste negatif (`-0.468568 USDC`) pour des raisons de strategie/couts, pas pour une divergence ledger.

Prochaine verification obligatoire: redemarrer `LANCER_HYPERSMART.cmd` pour charger le nouveau `HYPERSMART_MIN_REDUCE_NOTIONAL_USDT=0`, laisser tourner 10-20 minutes, puis verifier que `pnl_reliability_status=OK`, que `duplicate_full_closes_ignored` reste stable, et que chaque pic du metagraphe correspond a un evenement ledger unique. Si le PnL reste negatif, la cause dominante actuelle est `FEE_DRAG_TOO_HIGH` + `LOSS_STREAK_HALT`, donc il faut travailler le sizing/TP-SL/filtrage, pas la comptabilite.

## Jugement d'architecte
Le projet **implémente déjà l'essentiel** des 16 STEP. Les 34 repos GitHub sont **installés**
(`runtime/research/github_repos_v24/`, 549 Mo) et **mappés** (`docs/research/HYPERSMART_V24_MODULE_PORTAGE_MATRIX.md`
+ `..._SOURCE_TO_TARGET_FILE_MAP.md` + `..._LICENSE_AND_PORTAGE_AUDIT.md`) : 77 idées classées
(52 PORT_BEHAVIOR, 18 COPY_ADAPTED, 1 COPY_DIRECT, 6 INSPIRE_ONLY). **Donc le travail restant n'est
PAS « porter plus de GitHub » — c'est rendre le tout FONCTIONNEL en live** : remplacer les fixtures
par la donnée Hyperliquid read-only réelle, et régler latence/edge/IA (le vrai frein au PnL).

## Checklist (statut honnête vs code réel)
| STEP | Zone | Code existant | Statut |
|---|---|---|---|
| 0 | Reconnaissance | `docs/release/STEP_0_RECONNAISSANCE.md` | **DONE** |
| 1 | CLAUDE.md + règles | `CLAUDE.md` (2.3 Ko), `AGENTS.md` | **DONE** (à garder à jour) |
| 2 | Archi + legacy | `docs/ARCHITECTURE_PHASE_0.md`, `docs/LEGACY_ISOLATION_PLAN.md` | **DONE** |
| 3 | Fondations core | `core/` (config, logging, error_handler, circuit_breaker, retry, state_manager, main) | **DONE** |
| 4 | HL read-only monitor | `hyperliquid/`, `realtime/`, `collection/` (info+ws, source_health, backoff, dedupe) | **DONE** |
| 5 | Simulation PnL (ledger) | `paper_trading/` (paper_engine, ledger, exec_model, sl_tp, funding_payment_tracker, pnl_reconciliation), `simulation/` | **DONE** |
| 6 | Audit PnL / réalisme | `audit/simulation_realism_audit.py`, `simulation/` pnl audit, `security/fake_data_scanner.py` | **PARTIAL** (re-vérifier réconciliation dashboard↔audit) |
| 7 | Mapping GitHub | `docs/research/GITHUB_*` + `HYPERSMART_V24_*` (34 repos, 77 idées) | **DONE** |
| 8 | Wallet scoring + copy | `scoring/`, `copy_wallet/`, `wallets/` — E2E présent | **DONE** (functional live à confirmer) |
| 9 | Decision/Risk/NoTrade | `signals/` (copy_decision, gate_promotion, reason codes), `risk/`, `edge/` | **DONE** |
| 10 | Arbitrage cross-exchange | `arbitrage/` (17), `features/basis.py`, `signals/source_reconcile.py` — E2E présent | **PARTIAL** (souvent fixture-labeled sans 2e source live) |
| 11 | Funding / basis / hedge | `funding/`, `paper_trading/delta_neutral_position.py`, `hedge_reconciliation.py`, `risk/loss_halts.py` | **PARTIAL** (E2E présent, live à brancher) |
| 12 | Backtest réaliste | `backtest/` (book_replay, no_lookahead_guard, report_charts), `backtesting/` | **DONE** |
| 13 | Dashboard local | `ui/` (routes, simulation_v2.html, /api/v12/panels, /metrics), `dashboard/` | **DONE** |
| 14 | Safety audit | `security/` (safety_audit, mainnet_guard, fake_data_scanner), `audit/` — distingue mot vs action | **DONE** |
| 15 | CLI | 121 commandes (`audit-safety`, `runtime-check`, `simulation-report`, `arbitrage-scan`, `funding-scan`, `live-user-fills-stream`…) | **DONE** |
| 16 | Tests globaux + rapport | 421 fichiers de test ; `FINAL_CLAUDE_CODE_REPORT.md` à régénérer | **PARTIAL** |

## Le vrai travail restant (pour « totalement fonctionnel »)
1. **Live > fixtures** : là où l'arbitrage/funding tombent en `fixture-labeled` faute de 2e source,
   brancher la donnée Hyperliquid read-only réelle ou afficher un **état vide honnête** (jamais de fake).
2. **Latence temps réel** : le moteur WS persistant (`tools/stream_loop.ps1` + `live-user-fills-stream`)
   vient d'être réparé (NameError + log mojibake) — le **prouver en run** (latence ~1-2 s) puis resserrer
   la fenêtre fraîche à ~4 s. C'est LE frein au PnL, pas un module manquant.
3. **IA** : accumuler assez de trades clôturés à issues mixtes pour l'entraînement (elle filtre, elle
   n'invente pas de profit).
4. **Métrique honnête** : juger au **profit factor** (gains/pertes), pas au winrate brut (30 % + PF>1 = rentable).

## Portage GitHub — priorités déjà décidées (V24 matrix)
P0 (fait/à fiabiliser) : Rezzecup (mirror), tony-42069 (SL/TP/flags), terauss (hot/research split),
freqtrade (backtest discipline), ChainInsighter (session/latence), Jackhuang (arbitrage HL),
rustjesty (delta-neutral), hummingbot (connector). P1 : ArbiBot (low-latency), gajesh (funding),
Drakkar (triangular), CloddsBot (VaR/calibration), Harrier (OBI/depth), MrFadiAi (smart-money),
evan-kolberg (backtest), lightweight-charts. P2/P3 : incrémental. Détail + fichiers cibles :
`docs/research/HYPERSMART_V24_MODULE_PORTAGE_MATRIX.md`.

## Rattachement des blocs A→K aux STEP principaux (anti-désordre, 2026-07-01)
| Bloc | Étapes | STEP principal rattaché |
|---|---|---|
| A (stabilisation/hygiène) | A1-A4 | STEP 3 + STEP 16 |
| B (données live > fixtures) | B1-B5 | STEP 4 + STEP 10/11 |
| C (edge/décisions) | C1-C5 | STEP 9 + STEP 6 |
| D (audit fonctionnel) | D3-D15 | STEP 3-15 (un par STEP) |
| E (livrables) | E1-E5 | STEP 1 + STEP 16 |
| F (exploitation GitHub) | F1-F4 | STEP 7 |
| G (qualité pro) | G1-G6 | STEP 3 (transversal) |
| H (câblage total) | H1-H3 | STEP 2 |
| I (réalisme HL) | I1-I4 | STEP 5 |
| J (observabilité/ops) | J1-J4 | STEP 13 + STEP 15 |
| K (finition/preuve) | K1-K3 | STEP 14 + STEP 16 |
| Contrats de données internes | — | STEP 2 |
| Persistence / DB / migrations | — | STEP 2/5 |
| Règle de provenance (source/freshness/evidence/INSUFFICIENT_DATA) | — | STEP 4 (transversal) |
| PositionLifecycle / DeltaDetector | — | STEP 8 |
| MarketFeatures / Microstructure | — | STEP 9 |
| Sizing / Portfolio Risk Budget | — | STEP 9 |
| Parité live↔replay↔backtest | — | STEP 12 |
| Preuve de lecture GitHub (matrice enrichie) | — | STEP 7 |
| Definition of Done (PARTIAL_NOT_WIRED) | — | transversal |
| Mini-run réaliste (ledger=audit=dashboard=exports) | — | STEP 6 |

## Avancement — étapes 30-35 (F1-F4 + G1-G2), 2026-07-01
- **F1 (idée par idée des 34 GitHub)** : **DONE**. 51/51 modules cibles de la matrice V24
  existent dans `src/hl_observer` (le seul « manquant » `risk/depth_guard.py` est en fait
  `signals/depth_guard.py` — chemin erroné dans la matrice). Preuve : `docs/research/GITHUB_COVERAGE.md`.
- **F2 (anti-orphelin)** : **DONE**. 0 orphelin — chaque module porté est importé ailleurs
  (REFS≥1). 34/34 profils externes s'exécutent via le bus (`ui/fusion_persistent_adapter.py`,
  trace `ENGINE_EVALUATION`), code upstream intact.
- **F3 (couverture)** : **DONE** (câblage) / **PARTIAL** (colonnes « test cible » + « visible
  dashboard » à croiser) — `docs/research/GITHUB_COVERAGE.md`.
- **F4 (INSPIRE_ONLY à gain réel)** : **PARTIAL** — idées clés déjà portées (freqtrade,
  hummingbot, ArbiBot, Harrier, CloddsBot) ; reste à réévaluer les P3 mineurs. Pas de portage
  urgent requis.
- **G1 (lint ruff + typage)** : **PARTIAL**. Baseline ruff = 2569 findings (≈2059 E501 longueur
  de ligne + 148 I001 tri d'imports = cosmétique). Bug réel corrigé : F821 `CollectionRecorder`
  (forward-ref) → `TYPE_CHECKING` ajouté dans `hyperliquid/rest_info_client.py`. Les 3
  « invalid-syntax » (`routes.py`, `log_metrics.py`, `microstructure_guard.py`) sont des **faux
  positifs de troncature du mount sandbox** (fichiers complets/valides côté Windows, cf. run
  Windows `pytest -q` = 2080 passed). Corrections cosmétiques de masse à faire **côté Windows**
  (ne pas lancer `ruff --fix` dans le sandbox : risque d'écrire du tronqué).
- **G2 (logging/erreurs cohérents)** : **DONE**. Runtime = **0 `except:` nu** ; seuls
  6 sites `try/except: pass|continue` (ruff S110/S112), tous des boucles best-effort
  légitimes (résolveurs DoH, chargement de panneau optionnel, candidats de fichiers).
  Fondations d'erreur centralisées (`error_handler`/`circuit_breaker`/`retry`) déjà en place.
- **G3 (tests edge-cases ledger/PnL)** : **DONE**. Sous-ensemble ledger/PnL fiable au vert
  en sandbox (`test_paper_ledger` + `test_pnl_reconciliation` + `test_winrate_per_position`
  = 6 passed) ; long/short couverts dans `test_paper_ledger` ; suite complète verte côté
  Windows (2080 passed). Les tests important les gros fichiers tronqués échouent **en
  sandbox seulement** (artefact mount), pas sur Windows.
- **G4 (couverture de tests)** : **PARTIAL**. Outil `pytest-cov` opérationnel ; la couverture
  par module vient des tests dédiés de chaque module. La **couverture globale** reste bloquée
  en sandbox par la troncature des gros fichiers → à mesurer côté Windows.
- **G5 (profil perf hot-path)** : **DONE (spot-check)**. Fonctions pures chaudes rapides
  (`compute_obi` ≈ 23 µs/appel) → le vrai frein de latence est **l'I/O/WS** (bloc B), pas le CPU.
- **G6 (warnings + compat 3.10)** : **DONE**. **Bug réel corrigé** : `copy_mode/copy_session_controller.py`
  importait `StrEnum` sans garde (ImportError sur Python 3.10) → pattern gardé ajouté
  (comme `config/settings.py`). Re-scan : **0 import `StrEnum` non gardé restant**.
- **H1 (carte de flux end-to-end)** : **DONE**. `docs/ARCHITECTURE_FLOW.md` (chaîne
  collecte→normalisation→features→signaux→gate/risk→sizing→paper→ledger→dashboard),
  ancrée sur les tests E2E existants (`test_copy_run_fake_rest_broad_scan_end_to_end`,
  `test_refactor_fusion_*_e2e`). Réserve : « câblé » ≠ « autoritaire » (shadow → suivi H3).

### Bugs réels corrigés (30-40)
1. Import circulaire `risk↔signals` (lazy import dans `microstructure_guard`).
2. Forward-ref `CollectionRecorder` non résolu → `TYPE_CHECKING` (`rest_info_client.py`).
3. `StrEnum` non gardé → crash Python 3.10 (`copy_session_controller.py`).

### Limite d'outillage documentée
Le **mount du sandbox tronque plusieurs gros fichiers** (`ui/routes.py`,
`simulation/log_metrics.py`, `risk/microstructure_guard.py`, `hyperliquid/rest_info_client.py`) :
ruff/py_compile/pytest y donnent des **faux positifs** (invalid-syntax EOF, F821 en fin de
fichier). Les fichiers sont **complets et valides côté Windows** (run `pytest -q` = 2080 passed).
→ Vérifier ces fichiers **sur Windows**, ne pas lancer `ruff --fix` dans le sandbox.

## Session 2026-07-02 — reprise architecte senior (STEP 0)

**STEP 0 — Reconnaissance : DONE (cette session).**
- Objectif : vérifier l'état réel avant toute modification.
- Fichiers lus : `LANCER_HYPERSMART.cmd`, `tools/start_hypersmart_simulation.ps1`, arborescence `src/hl_observer/` et `hyper_smart_observer/`, `git log/status`.
- Décision : runtime canonique = `src/hl_observer` (confirmé par le launcher). `hyper_smart_observer/` = legacy/bridge à isoler (ne pas supprimer).
- Constat critique : les 3 derniers commits ont modifié le legacy (`hyper_smart_observer/dydx_v4/live_observer.py`) alors que l'actif est `src/hl_observer` → à trancher en STEP 2.
- Structure cible du prompt déjà présente à ~90 % sous d'autres noms (mapping écrit dans `STEP_0_RECONNAISSANCE.md`) → ne pas recréer `monitor/` ni `decision/`.
- Fichiers créés/modifiés : `docs/release/STEP_0_RECONNAISSANCE.md` (append daté), ce fichier.
- Tests lancés : aucun (étape d'analyse pure).
- Statut : **DONE**. Prochaine étape : STEP 2 (runtime canonique + `LEGACY_ISOLATION_PLAN.md`).

## Session 2026-07-02 (suite) — STEP 2→16 en autonomie

**Décision d'architecture (STEP 2)** : runtime canonique = `src/hl_observer` ; moteur PnL runtime = `hyper_smart_observer/dydx_v4` (engine + live_observer) reclassé ACTIVE_BRIDGE (il produit le PnL affiché) ; source de vérité comptable = PaperLedger de `src/hl_observer` (garde-fou de réconciliation). Docs : `LEGACY_ISOLATION_PLAN.md`, `ARCHITECTURE_PHASE_0.md`, `STEP_0_RECONNAISSANCE.md`.

**Bugs réels corrigés (compat Python 3.10, règle G6)** :
1. `src/hl_observer/refactor_fusion/runner.py` — `from datetime import UTC` non gardé → pattern try/except (UTC=timezone.utc).
2. `src/hl_observer/dashboard/refactor_fusion_panel.py` — idem.
3. `tests/test_hypersmart_copy_network_read.py` — `__import__("datetime").UTC` → `.timezone.utc` (portable).
4. `hyper_smart_observer/dydx_v4/wallet_harvester.py` — docstring ASCII-art → raw string (supprime DeprecationWarning escape).
Code PRODUIT vérifié : 0 usage non portable de `datetime.UTC` restant dans `src/hl_observer` et `hyper_smart_observer`.

**Vérification par step (tests lancés cette session, PYTHONPATH=src, sandbox py3.10)** :
| STEP | Preuve tests | Résultat |
|---|---|---|
| 3 Core | test_error_handler + circuit_breaker + retry_policy + state_manager + no_real_trade_foundations | 10 passed |
| 4 Monitor RO | dydx test_dydx_rest_and_ws_mocked (dans suite) | vert |
| 5 Ledger PnL | test_paper_ledger + pnl_reconciliation + orderbook_execution_simulator | vert |
| 6 Audit | test_simulation_realism_audit + dashboard_truth_audit | vert |
| 8/9 Copy/Décision/Risk | dydx suite (lifecycle, pnl_and_paper, risk_policy, safety_and_config) | vert |
| 10 Arbitrage | arbitrage_opportunity_ranker + spread_formula + refactor_fusion_arbitrage_e2e | vert (fixtures) |
| 11 Funding/basis/hedge | funding_* (5) + basis_funding_model + dual_venue_hedge_sim + refactor_fusion_funding_e2e | vert (fixtures) |
| 12 Backtest | backtest_fee_slippage_model + replays_fills_deltas_books + refactor_fusion_backtest_e2e | vert |
| 13 Dashboard | dashboard_* (payload/pnl/equity/decision_ledger/readonly) + refactor_fusion_dashboard_e2e | vert |
| 14 Safety | dydx safety_and_config + hypersmart_v19_no_real_trade + copy_cli_and_safety + no_real_trade_foundations | vert |
| Moteur dydx complet | tests/dydx_v4/ (56 fichiers) + 5 E2E refactor_fusion | 356 passed |

**Réserve honnête (PARTIAL_NOT_WIRED)** : STEP 10 (arbitrage) et STEP 11 (funding) sont **verts sur fixtures** ; le branchement d'une **2ᵉ source live réelle** (CEX pour l'arb, historique funding live) reste à faire — sinon état vide honnête, jamais de fake. Idem latence WS live (bloc B) = frein PnL réel, hors périmètre sandbox (nécessite run Windows).

**Limite d'outillage** : suite complète `pytest -q` non exécutable en sandbox (mount tronque `cli.py`/`routes.py`, limite 45s). Vérité complète = run Windows (référence historique : 2080 passed).
