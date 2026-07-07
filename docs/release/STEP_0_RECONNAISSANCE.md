# STEP 0 — Reconnaissance du projet HyperSmart Observer

_Généré le 2026-06-26. Lecture seule, paper-only. Aucune suppression._

## Verdict d'architecte (lis ça d'abord)
Ce projet **n'est pas un chantier vierge** : c'est une base **mature et très étendue**. Toutes
les zones de la « structure cible » du prompt **existent déjà** dans le runtime. Donc la bonne
décision (que le prompt exige lui-même : « ne crée pas une 3e architecture, renforce l'existant »)
est de **mapper les 16 STEP sur le code existant et combler les vrais trous**, pas de reconstruire.

**Le vrai problème n'est PAS un module manquant** — c'est, mesuré sur les logs réels :
1. **Latence des données gratuites (~10–22 s)** → entrées en retard → pas d'edge fiable (winrate 30–57 %).
2. **Le moteur temps réel (WS persistant) vient seulement d'être réparé** (NameError + log mojibake) et
   n'a pas encore prouvé une latence sub-seconde en run réel.
3. **L'IA est affamée** (pas assez de trades clôturés à issues mixtes pour s'entraîner).
Ces trois points sont le cœur du travail restant, pas la ré-écriture de modules déjà présents.

## Runtime actif
- **`src/hl_observer`** = runtime actif (confirmé : `cli.py` 121 commandes, `__main__.py`, ~80 sous-paquets).
- Lancement : `LANCER_HYPERSMART.cmd` → `tools/start_hypersmart_simulation.ps1` (UI :8794 + poller) +
  `tools/ia_train_loop.ps1` (IA) + `tools/stream_loop.ps1` (moteur temps réel V16).
- Tests : **421 fichiers** dans `tests/`.

## Legacy identifié (à isoler, PAS supprimer)
- **`hyper_smart_observer/`** — ancien paquet, gardé en compat (cf. CLAUDE.md « legacy bridge »).
- **`src/hl_observer/cli_pkg_DISABLED/`** — ancien package CLI neutralisé (renommé, pas supprimé).
- **dYdX dormant** — présent, mockable, non lancé (Hyperliquid = défaut).
- Détail dans `docs/LEGACY_ISOLATION_PLAN.md` (existant).

## Mapping structure proposée → existante (tout existe déjà)
| Zone prompt | Répertoire réel | Fichiers |
|---|---|---|
| core | `core/` | config, logging_config, error_handler, circuit_breaker, retry, state_manager, main |
| monitor read-only | `hyperliquid/`, `realtime/`, `collection/` | info/ws clients, source_health, backoff, proxy, rate_limiter |
| scoring | `scoring/` (11) | wallet_score_v2, smart_money_gate, shortlist_quality_filter… |
| copy wallet | `copy_wallet/` (12), `wallets/` (42), `copy_fidelity/` (8) | mirror runtime, sizing, journal, balance_replication |
| decision/risk | `signals/` (41), `risk/` (48), `edge/` (11) | copy_decision, gate_promotion, reason codes, risk_engine |
| arbitrage | `arbitrage/` (17) | cross-exchange, spread, opportunity_ranker, triangular |
| simulation PnL | `paper_trading/` (20), `simulation/` (34) | paper_engine, paper ledger, exec_model, sl_tp, funding_payment_tracker, pnl_reconciliation |
| backtest | `backtest/` (18), `backtesting/` (12) | replay, book_replay, no_lookahead, report_charts, optimize |
| dashboard | `ui/` (25), `dashboard/` (8) | routes, simulation_v2.html, panels, charts |
| audit/safety | `audit/`, `security/` | safety_audit, fake_data_scanner, mainnet_guard, simulation_realism_audit |
| funding | `funding/` | scanner, history window |

## Risques immédiats
- **Arbre git énorme** : ~978 fichiers non commités (working tree très chargé). Risque de confusion ;
  recommandation : commit/point de sauvegarde avant gros refactor. **Ne rien supprimer.**
- **Gotcha mount/编码** : les gros fichiers (`routes.py` 4300+, `cli.py` 3100+) sont sensibles ;
  éditer par petits patches vérifiés (déjà documenté).
- **Latence donnée gratuite** : plafonne la performance ; c'est un fait structurel, pas un bug.

## Statut des 16 STEP (voir CLAUDE_CODE_STEP_PROGRESS.md)
Résumé : STEP 0-5, 7, 13, 15 largement **DONE** (code+tests existants) ; STEP 6, 9, 14 **DONE/à re-vérifier** ;
STEP 8, 10, 11, 12 **PARTIAL** (modules présents, câblage/tests E2E à confirmer) ; STEP 16 = rapport à produire.
Le focus intelligent = les vrais trous (latence/edge, IA, E2E arbitrage/funding), pas la ré-écriture.

---

## Reconnaissance — session 2026-07-02 (architecte senior, vérification honnête)

### Runtime actif (confirmé par le launcher)
- **Actif** : `src/hl_observer` — lancé par `tools/start_hypersmart_simulation.ps1` → `python -m hl_observer ui -Port 8794`, `PYTHONPATH=src`. 702 modules `.py`, 472 fichiers de test, `cli.py` = 3433 lignes.
- **Legacy/bridge** : `hyper_smart_observer/` — 285 modules `.py`. Contient `dydx_v4/` (dont `live_observer.py`, 99 Ko).

### Anomalie prioritaire détectée
Les 3 derniers commits (`04a6d27`, `ba6266e`, `6502fab`) modifient `hyper_smart_observer/dydx_v4/live_observer.py`, **du code legacy**, alors que `CLAUDE.md` déclare `src/hl_observer` comme runtime actif et `dydx_v4` comme dormant. → Divergence runtime réel vs runtime documenté = cause probable du désordre. **Décision d'architecture requise** (voir STEP 2) avant tout nouveau développement, pour ne pas empiler une 3ᵉ trajectoire.

### Mapping structure cible proposée → existant (ne PAS recréer)
| Proposé (prompt §8) | Réalité dans `src/hl_observer` | Action |
|---|---|---|
| `core/` | `core/` | renforcer |
| `monitor/` | `hyperliquid/` + `realtime/` + `collection/` | **ne pas créer** — mapper/adapter |
| `scoring/` | `scoring/` | renforcer |
| `copy_wallet/` | `copy_wallet/` (+ `copy_mode/`, `copying/`, `following/`) | consolider |
| `decision/` | `signals/` + `risk/` + `edge/` | **ne pas créer** — mapper |
| `arbitrage/` | `arbitrage/` | renforcer |
| `simulation/` | `simulation/` + `paper_trading/` + `ledger/` | consolider |
| `backtesting/` | `backtesting/` + `backtest/` | consolider |
| `dashboard/` | `dashboard/` + `ui/` | renforcer |
| `audit/` | `audit/` + `security/` | renforcer |

### Risques immédiats
1. Double runtime (`src/hl_observer` vs `hyper_smart_observer`) → risque de corriger le mauvais côté.
2. Doublons de dossiers dans le runtime actif (`backtest/`+`backtesting/`, `copy_wallet/`+`copy_mode/`+`copying/`+`following/`, `simulation/`+`paper_trading/`) → dette à documenter, pas à supprimer.
3. Gros fichiers tronqués par le mount sandbox (`cli.py`, `ui/routes.py`) → tests/ruff faux positifs en sandbox ; vérifier côté Windows.

### Prochaine étape
STEP 2 — trancher la question du runtime canonique (garder `src/hl_observer`, isoler `hyper_smart_observer` en legacy read-only) et écrire/mettre à jour `docs/LEGACY_ISOLATION_PLAN.md`. STEP 1 (CLAUDE.md) est déjà en place et cohérent.
