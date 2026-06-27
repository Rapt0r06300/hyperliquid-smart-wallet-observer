# Audit session Hyperliquid-first — 2026-06-16

Statut: **SIMULATION ONLY**. Read-only, paper/mock USDC, deny-by-default. Aucun ordre réel.

## 0. Contexte & décision de direction

Le brief de cette session demande **Hyperliquid-first** (dYdX secondaire/mockable).
Or le code *actif* du dépôt est **dYdX v4** (`hyper_smart_observer/dydx_v4/`, ~78 fichiers,
~19k LOC), et `CODEX_GOAL.txt` (créé le jour même) pilote une optimisation du PnL paper dYdX,
avec du travail **non commité en cours** sur ces fichiers.

Décision validée avec l'utilisateur :
- **Direction de session = Hyperliquid-first** : auditer / vérifier / renforcer la stack
  Hyperliquid déjà présente, sans toucher au travail dYdX.
- **Le travail dYdX en cours est préservé** (backups + à committer côté Windows).

Constat clé : la « vertical slice » demandée par le brief **existe déjà** en grande partie sous
`hyper_smart_observer/`. Cette session est donc **audit + vérification + durcissement**, pas un
greenfield.

## 1. État Git initial

- Branche `main` @ `04a6d27` (« LEADER_EXIT désactivé pour positions démo + min_hold 60s »).
- 45 entrées non commitées (modifs `dydx_v4/`, `src/hl_observer/ui`, docs/release, tests) + 7 fichiers
  non suivis (CODEX_GOAL.txt, 2 handoffs, 4 tests dydx_v4).
- `data/` (23 Go), `runtime/` (7,2 Go), `logs/` (3 Go) sont **non suivis** (gitignore OK) — aucun
  risque de les committer.

## 2. Protection du travail local (non destructif)

- Archive source complète (suivi + non suivi) : `projet-invest-SOURCE-backup-*.tar.gz` (~4 Mo, 2480 fichiers).
- Patch des modifs suivies : `uncommitted-changes-*.patch` (~476 Ko, restaurable via `git apply`).
- Stockées dans le dossier outputs de la session.

## 3. Contrainte d'environnement (importante)

Le dossier projet est monté en **bindfs FUSE** dans le sandbox Linux : `create`, `write` et `rename`
sont autorisés, mais **`unlink`/`rm` est refusé** (« Operation not permitted »).

Conséquence : les **écritures git** (`commit`, `add`) corrompent l'index (`.git/index`) car git
remplace des fichiers existants via unlink. L'index a été corrompu puis **reconstruit proprement**
(`git read-tree HEAD`) — historique et arbre de travail intacts. **Le commit doit être fait côté
Windows.** Les éditions de code de cette session passent par l'outil fichier (fiable côté hôte).

Résidus inertes laissés dans `.git/` (à supprimer côté Windows) : `index.lock.STALE-*`,
`index.lock.junk-*`, `index.corrupt-*`, et quelques `objects/*/tmp_obj_*` (nettoyables via `git gc`).

## 4. Verdict sécurité (preuve 0 ordre réel)

| Contrôle | Résultat |
|---|---|
| `--safety-check` | **OK** |
| `--status` | Mainnet: forbidden · Execution: disabled by default · Mode: RESEARCH_ONLY |
| Scan source `/exchange` (`exchange_path`) | **0** |
| Scan source signatures (`sign_call`) | **0** |
| `place_order(` | **1** — uniquement `hyperliquid_client/testnet_exchange_client.py` (stub verrouillé qui lève toujours `SafetyViolation`) |
| `sensitive_key_material` | **None** |
| `allow_mainnet` / `execution_enabled` / `testnet_execution_enabled` | **False** |
| `ws_monitor_enabled` / `explorer_observer_enabled` | **False** (off par défaut) |

`hyperliquid_client/info_client.py` est **verrouillé en read-only** : il lève
`SafetyViolation("MAINNET_FORBIDDEN")` si l'URL contient « exchange » ou ne se termine pas par
`/info`, et refuse tout payload contenant « exchange » ou « signature ».

Tests sécurité passants : `test_hypersmart_audit_safety`, `test_hypersmart_dashboard_readonly`,
`test_hypersmart_collector_readonly` (+ 47 autres du lot sécurité/copy/dashboard).

## 5. Baseline de tests

Sandbox = Python 3.10 ; le projet cible 3.11. Lot Hyperliquid `tests/test_hypersmart_*.py` :
**211 passés / 10 échoués**.

Triage des 10 échecs :
- **9 = artefacts sandbox uniquement** (passent sur Windows + Py3.11) :
  - `datetime.UTC` (ajouté en Py3.11) utilisé dans les tests `test_hypersmart_copy_network_read` (2) ;
  - tests CLI qui codent en dur le `cwd` Windows `C:\Users\flo\Desktop\Projet invest` pour `subprocess`
    (absent sous Linux) : `test_hypersmart_code_first_cli` (4), `local_scan_performance_contract` (1),
    `scale_benchmark` (1).
- **1 = vraie régression dans le WIP non commité** : `test_hypersmart_single_launcher` — `LANCER_HYPERSMART.cmd`
  ne contient plus `HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=6000` (garde-fou de fraîcheur), retiré par
  le travail démo dYdX. À traiter avec le commit dYdX (hors périmètre HL).

## 6. Gap analysis — vertical slice Hyperliquid du brief

| Étape du brief | Module existant | Statut |
|---|---|---|
| Fake HyperliquidAdapter | `hyperliquid_client/` (info_client, ws, models, normalization, payloads) + `FakeInfoClient` de test | DONE |
| CollectionRun / SourceHealth / Cursors / Dedupe | `copy_mode/snapshot_engine`, `realtime_monitor/dedupe`, `storage/` | DONE |
| Normalized models (Fill/Position/OpenOrder/Mid) | `hyperliquid_client/models.py`, `normalization.py` | DONE |
| MarketSignalFeatures (spread/microprice/depth) | `copy_mode/edge.py`, `paper_trading/spread.py` | PARTIAL/DONE |
| Wallet scoring / shortlist | `copy_mode/leaderboard_selector.py`, `sizing.py` | DONE |
| DeltaDetector OPEN/ADD/REDUCE/CLOSE/FLIP/UNKNOWN | `copy_mode/delta_detector.py`, `position_lifecycle/` | DONE |
| SignalCandidate / NoTradeDecision | `copy_mode/signal_candidate.py`, `no_trade_report.py` | DONE |
| EdgeCalculator (fees+spread+slippage+latency+copy degradation) | `copy_mode/edge.py`, `paper_trading/{fees,slippage,latency}` | DONE |
| RiskEngine deny-by-default | `risk_engine/{gates,refusal_reasons,risk_state}` | DONE |
| DecisionLedger (hash SHA-256) | `copy_mode/repository.py`, `dashboard/` | DONE/PARTIAL |
| DashboardPayload read-only | `dashboard/exporter.py` + `dashboard_truth/` | DONE |
| Export CSV/JSON | `dashboard/exporter.py`, `copy_mode/reports.py` | DONE |
| **openOrders seuls ≠ PaperIntent** | `copy_loop.py:140` → `OPEN_ORDERS_CONTEXT_ONLY` | DONE (logique) — **test ajouté cette session** |

Reason codes : présents sur deux enums (`copy_mode.NoTradeReason` + `risk_engine.RiskRefusalReason`),
deny-by-default (`DENY_BY_DEFAULT` en tête).

## 7. Couverture des tests « preuve » exigés par le brief

| Invariant du brief | Couverture existante |
|---|---|
| MarketMid fallback + data_quality | `test_data_acquisition_engine` |
| userFillsByTime truncation / window | `test_hypersmart_info_client`, `test_collection_pipeline`, `test_data_acquisition_engine` |
| WS snapshot `isSnapshot` dedupe | `test_realtime_recovery_engine`, `test_user_fills_live_scan` |
| RiskEngine deny-by-default | `test_hypersmart_risk_gates`, `test_hypersmart_copy_mode` |
| **openOrders seuls ≠ PaperIntent** | **AJOUTÉ : `tests/test_no_open_orders_only_paper_intent.py` (2 tests, PASS)** |

## 8. Test ajouté cette session

`tests/test_no_open_orders_only_paper_intent.py` — exerce la vraie chaîne `run_copy_dry_run` avec un
faux client /info renvoyant des `openOrders` mais **0 fill / 0 position** :
- `test_open_orders_only_emits_context_only_no_trade` : `deltas_seen == 0`, aucun signal,
  NoTradeDecision `OPEN_ORDERS_CONTEXT_ONLY` émise.
- `test_open_orders_only_never_opens_paper_trade` : **aucun paper trade ouvert**.

Compatible Py3.10/3.11 (n'utilise pas `datetime.UTC`). Résultat : **2 passed**.

## 9. Findings (bugs/problèmes réels)

1. **`--audit-safety` ne termine pas** (timeout) : `audit_databases` / `audit_archive_readiness`
   parcourent la racine runtime incluant `data/` (23 Go) et `logs/` (3 Go). La *logique* d'audit est
   correcte (et le scan source, lui, est borné à `hyper_smart_observer/`). Correctif recommandé :
   exclure `data/`, `logs/`, `runtime/` du parcours d'archive/DB. **Impact sécurité : nul** (le verdict
   code-level est déjà prouvé section 4).
2. **Régression launcher (dans le WIP dYdX)** : `LANCER_HYPERSMART.cmd` a perdu
   `HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=6000`. À corriger avec le commit dYdX.

## 10. Limites restantes

- Tests exécutés dans le sandbox en Py3.10 → 9 échecs non représentatifs (cf. §5). Re-run requis sur
  Windows/Py3.11 pour le vert complet.
- Commit non réalisable depuis le sandbox (bindfs no-unlink) → à faire côté Windows.
- Suite complète (214 fichiers de test) non exécutée intégralement (limite 45 s/commande) ; lots
  ciblés exécutés.

## 11. Prochaines étapes recommandées

1. Côté Windows : supprimer les résidus `.git/*.lock*`/`index.corrupt-*`, puis committer le WIP dYdX et
   ce travail HL (commandes fournies dans le rapport de session).
2. Borner `audit_databases`/`audit_archive_readiness` pour exclure `data/`, `logs/`, `runtime/`.
3. Restaurer `HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=6000` dans `LANCER_HYPERSMART.cmd`.
4. Aligner le nom de reason code (`OPEN_ORDERS_CONTEXT_ONLY` ↔ `OPEN_ORDERS_ONLY_NOT_EVIDENCE` du brief)
   ou documenter l'équivalence (fait ici).
