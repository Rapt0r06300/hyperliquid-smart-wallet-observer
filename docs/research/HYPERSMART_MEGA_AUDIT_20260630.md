# HyperSmart Mega Audit Runtime - 2026-06-30

## Resume

Cette passe a cible les bugs visibles dans la simulation locale Hyperliquid :

- pics incoherents du metagraphe ;
- ecran qui saute ou semble revenir a un etat precedent ;
- capital/PnL confus entre deux lancements ;
- logs pollues par des tests ;
- positions fantomes dans l'historique du graphe ;
- conflit entre plusieurs writers d'equity ;
- verification des garde-fous paper-only/read-only.

Le but n'est pas de forcer un PnL positif. Le PnL doit rester vrai, calcule sur les prix disponibles et les positions paper locales. La correction consiste a retirer les incoherences qui faussent la lecture ou degradent les decisions.

## Causes trouvees

| Probleme | Cause racine | Impact | Correction |
|---|---|---|---|
| Pics et retours rapides dans le graphe | Deux writers alimentaient l'historique d'equity : l'overview lourd et le fast status mark-to-market | Le graphe pouvait melanger deux sources et afficher des sauts | Fast status devient writer autoritaire ; les points legacy `MARK_TO_MARKET` sont purges au prochain tick rapide |
| Capital qui semblait revenir ou rester incoherent | Le lanceur interne conservait l'equity par defaut alors que l'usage attendu est un reset a chaque lancement | Confusion entre session courante et anciennes sessions | `tools/start_hypersmart_simulation.ps1` reset maintenant a 1000 par defaut, sauf `HYPERSMART_RESET_ON_LAUNCH=0` |
| Reset manuel qui ne nettoyait pas l'etat vu par l'UI | Deux chemins concurrents existaient : `data/runtime/ui_simulation_state.json` et `runtime/data/ui_simulation_state.json` | L'UI pouvait garder un vieux fichier de 16 MB avec historique obsolete | Ajout de `HYPERSMART_UI_STATE_DIR`; le lanceur et le module persistent_state utilisent le meme dossier `runtime/data` |
| Historique fantome | `runtime/data/ui_simulation_state.json` contenait 1973 points, `open_positions=12`, alors que les positions courantes etaient vides | Le graphe affichait un PnL ancien mal relie a l'etat courant | Reset explicite du fichier runtime autoritaire : 0 position, 1 point `SESSION_START`, equity 1000 |
| Logs a envoyer pollues par les tests | Les tests d'overview exportaient des fixtures dans `logs/logs a envoyer` | Les decisions de test pouvaient etre interpretees comme decisions reelles du bot | En contexte pytest, les exports par defaut sont rediriges vers un dossier temp sandbox |
| Multiplication de no-trade apres entree consensus | Les deltas membres d'un cluster consensus etaient traites apres l'ouverture cluster | Bruit, refus supplementaires, risque de mauvais diagnostic | Ajout d'un dedupe early pour `CONSENSUS_CLUSTER_ALREADY_OPEN_NO_EXTRA_SIZE` |
| Gros ralentissements possibles | `runtime/data/hypersmart_simulation_session.sqlite3` pese environ 21 GB | L'overview lourd et certains scans peuvent devenir lents | Diagnostic ajoute ; retention/compaction DB reste prochaine action non destructive |
| Log verrouille | `logs/logs a envoyer/hypersmart_observer.log` reste verrouille par Windows malgre absence de process visible | Le preparateur de logs ne peut pas l'archiver | Comportement safe conserve : pas de kill, pas de suppression ; avertissement dans le manifest |

## Corrections code

- `src/hl_observer/ui/routes.py`
  - diagnostics runtime et graphe ajoutes au payload ;
  - detection des sources d'equity ;
  - dedupe des deltas de cluster consensus deja ouverts ;
  - garde contre l'ecrasement par l'overview lourd quand le fast status est autoritaire.

- `src/hl_observer/ui/status_routes.py`
  - fast status mark-to-market devient source autoritaire ;
  - purge des anciens points `MARK_TO_MARKET` lorsque le tick rapide existe.

- `src/hl_observer/ui/static/simulation_v2.html`
  - la page privilegie le tick rapide frais pour les cartes et le graphe ;
  - l'overview lourd ne remplace plus un tick rapide utilisable ;
  - drapeaux JS `fast_status_tick_authoritative` / `fast_status_tick_stale_for_graph`.

- `src/hl_observer/ui/simulation_log_export.py`
  - exporte `runtime_diagnostics` et `graph_diagnostics` ;
  - isole les exports de tests dans `%TEMP%` pour eviter de polluer les vrais logs utilisateur.

- `src/hl_observer/ui/persistent_state.py`
  - nouveau override `HYPERSMART_UI_STATE_DIR` ;
  - le chemin de l'etat UI peut etre fixe par le lanceur pour eviter deux fichiers concurrents.

- `tools/start_hypersmart_simulation.ps1`
  - definit `HYPERSMART_UI_STATE_DIR=runtime/data` ;
  - reset a 1000 USDT par defaut a chaque lancement ;
  - conservation possible uniquement avec `HYPERSMART_RESET_ON_LAUNCH=0`.

- `LANCER_HYPERSMART.cmd`
  - definit `HYPERSMART_UI_STATE_DIR=%~dp0runtime\data`.

## Etat local apres correction

- `runtime/data/ui_simulation_state.json`
  - positions : 0 ;
  - historique : 1 point ;
  - source : `SESSION_START` ;
  - equity de depart : 1000.0.

- `logs/logs a envoyer`
  - logs actifs de simulation remis a zero ;
  - anciens fichiers archives dans `_archives/session_20260630_020535` ;
  - warning restant : `hypersmart_observer.log` verrouille par Windows, non supprime.

- Runtime DB
  - `runtime/data/hypersmart_simulation_session.sqlite3` : environ 21 GB ;
  - prochaine priorite : retention/compaction/archivage non destructif.

## Verification live read-only apres reset

Apres reset du vrai fichier runtime, un test court de collecte Hyperliquid read-only a ete lance :

- `live-public-scan --network-read --store --duration-seconds 6 --coins AUTO --max-coins 10 --max-wallets 1000`
  - 320 trades publics vus ;
  - 207 wallets vus ;
  - 50 wallets promus pour follow-up ;
  - `stopped_reason=duration_elapsed` ;
  - aucun ordre, aucune signature.

- `live-user-fills-scan --network-read --store --duration-seconds 8 --max-users 10 --max-live-fill-age-ms 20000`
  - 10/10 wallets abonnés ;
  - 29 fills vus ;
  - 29 deltas stockés ;
  - 300 snapshots ignores ;
  - 0 fill stale ;
  - aucun ordre, aucune signature.

- `simulation-readiness --from-logs "logs/logs a envoyer" --fresh-window-seconds 120`
  - avant scan : `WAITING_FOR_FRESH_LEADERS` ;
  - apres public scan : `WAITING_FOR_FRESH_DELTAS` avec 50 leaders frais ;
  - apres user-fills scan : `SIMULATION_ACTIVE`, 29 deltas recents, 4 entry deltas frais.

Conclusion : le moteur n'etait pas "mort" ; il manquait des donnees fraiches parce que le serveur et les scanners etaient arretes ou lisaient un etat obsolete. Le lanceur doit maintenant recreer une session coherente et les scanners doivent rester actifs.

## Tests lances

- `python -m pytest -q tests\test_hypersmart_single_launcher.py tests\test_runtime_session_logs.py`
  - 8 passed.

- `python -m pytest -q tests\test_hypersmart_simulation_diagnostic_logs.py tests\test_ui_simulation_status_fast.py tests\test_ui_copy_dashboard.py::test_ui_simulation_overview_detects_multi_wallet_consensus`
  - 29 passed.

- `python -m pytest -q tests\test_fusion_persistent_adapter_external_profiles.py tests\test_fusion_strategy_runtime.py tests\test_external_github_strategy_bridge.py`
  - 13 passed.

- `python -m pytest -q tests\test_pnl_loss_fixes.py tests\test_v9_sl_tp.py tests\test_v9_sltp_runtime.py tests\test_paper_engine_realized_unrealized_pnl_equity.py tests\test_leverage_pnl.py tests\test_winrate_per_position.py`
  - 35 passed.

- `python -m pytest -q tests\test_no_exchange_sdk_imports_or_actions.py tests\test_no_fake_chart_or_fake_position_data.py tests\test_hypersmart_v19_no_real_trade.py tests\test_paper_trading_import_boundaries.py`
  - 4 passed.

- `python -m pytest -q tests\test_ui_simulation_persistence.py tests\test_ui_simulation_status_fast.py tests\test_hypersmart_simulation_diagnostic_logs.py`
  - 64 passed.

- `python -m pytest -q tests\test_fusion_persistent_adapter_external_profiles.py tests\test_fusion_strategy_runtime.py tests\test_external_github_strategy_bridge.py tests\test_no_exchange_sdk_imports_or_actions.py tests\test_no_fake_chart_or_fake_position_data.py tests\test_hypersmart_v19_no_real_trade.py`
  - 16 passed.

## Audits lances

- `python -m hyper_smart_observer.app.main --safety-check`
  - OK.

- `python -m hyper_smart_observer.app.main --audit-safety`
  - OK : aucun `/exchange`, aucune signature, aucune cle privee, aucun ordre operationnel, dashboard read-only.

- `python -m hyper_smart_observer.app.main --runtime-check`
  - archive ready ;
  - alerte connue : `logs/hl_observer.sqlite3` legacy dans logs, exclu des archives.

- `python -m hyper_smart_observer.app.main --archive-audit`
  - rapport ecrit dans `docs/release/HYPERSMART_ARCHIVE_AUDIT.md`.

## Limites restantes

1. La DB runtime de 21 GB peut ralentir les endpoints lourds. Il faut ajouter une retention propre : snapshots recents gardes, vieux events archives, vacuum hors session.
2. Les profils GitHub sont des adaptateurs paper locaux. Ils ne doivent pas executer de code upstream ni creer d'action externe.
3. Le PnL peut rester negatif si les signaux reels sont mauvais, trop tardifs, trop chers ou illiquides. Le logiciel ne doit jamais afficher un PnL positif artificiel.
4. `hypersmart_observer.log` reste verrouille ; ne pas supprimer brutalement. Relancer `prepare-simulation-logs` apres fermeture complete de Windows/terminal si besoin.
5. Les tests globaux complets n'ont pas ete relances dans cette passe, seulement les suites ciblees de simulation, logs, safety, paper, PnL et bridge GitHub.

## Prochaine action exacte

1. Ajouter une commande de maintenance non destructive : `compact-runtime-state`.
2. Limiter `simulation_equity_history` runtime en continu et nettoyer les points anciens au demarrage.
3. Ajouter un rapport PnL par moteur/profil pour identifier quel moteur GitHub paper perd, gagne ou cree des spikes.
4. Ajouter un audit de coherence live : positions ouvertes, graphe, equity, logs et fast status doivent tous pointer vers le meme snapshot.
5. Ajouter une retention DB : conserver les X dernieres heures pour l'UI, archiver le reste hors hot path.

## Garde-fous confirmes

- Hyperliquid par defaut.
- Simulation locale paper seulement.
- Aucune action argent reel.
- Aucun ordre reel.
- Aucun `/exchange` operationnel.
- Aucune signature.
- Aucune cle privee.
- Aucun wallet connect.
- Aucun PnL fake.
- Aucun chart fake.
- Paper trade != order.
- Score != recommandation de trading.
- Historique != profit futur.

## Addendum 2026-06-30 02:35 - correctifs apres reprise

### Probleme trouve : deltas WebSocket frais rejetes comme trop vieux

Le detecteur `copy-run` reconstruisait l'age du signal avec `exchange_ts` en priorite. Pour les fills recus en WebSocket live, cela peut etre faux pour la simulation : le fill peut etre recu maintenant, mais porter un timestamp d'echange deja plus ancien. Le projet possedait deja la fonction `copy_candidate_signal_time_ms`, qui sait faire la difference :

- source REST/backfill : timestamp du fill, conservateur ;
- source WebSocket live : timestamp de detection locale ;
- cluster frais : timestamp du leader le plus recent.

Correction appliquee :

- `src/hl_observer/copying/signal_detector.py`
  - utilise maintenant `copy_candidate_signal_time_ms(delta)` pour creer `SignalCandidate.timestamp_ms` et `signal_age_ms`.

Test ajoute :

- `tests/test_copy_signal_detector.py::test_copy_signal_detector_uses_live_ws_detection_time_for_freshness`
  - simule un delta `hyperliquid_ws:userFills:stream` avec `exchange_ts` ancien et `detected_at_ms` recent ;
  - verifie que le signal n'est plus rejete par `REJECT_TOO_LATE`.

### Probleme trouve : dossier `logs a envoyer` encore pollue par des traces anciennes

Apres `prepare-simulation-logs`, les decisions principales etaient fraiches, mais des traces IA/fusion/QA anciennes restaient visibles dans le dossier actif. Cela pouvait faire croire que la session courante contenait de vieux evenements.

Correction appliquee :

- `src/hl_observer/runtime/session_logs.py`
  - archive maintenant aussi `hypersmart_ia_*.json`, `hypersmart_ia_train.log`, `simulation_fusion_runtime_latest.json`, `wallet_mirror_journal.jsonl` et `qa_observation_*.jsonl` ;
  - ne touche toujours pas aux fichiers d'intelligence persistants sous `runtime/`.

Test ajoute :

- `tests/test_runtime_session_logs.py`
  - verifie que ces fichiers sont archives et absents du dossier actif apres preparation.

### Verification read-only apres correctif

Cycle borne lance localement :

```powershell
python -m hl_observer live-public-scan --network-read --store --duration-seconds 4 --coins AUTO --max-coins 10 --max-wallets 1000 --promote-top 50 --no-report
python -m hl_observer live-user-fills-scan --network-read --store --duration-seconds 6 --max-users 10 --max-live-fill-age-ms 20000 --no-report
python -m hl_observer copy-run --interval 15 --dry-run --copy-max-leaders 10 --leader-offset 0 --fresh-window-minutes 1 --max-pages 1 --no-report
python -m hl_observer simulation-readiness --from-logs "logs\logs a envoyer" --fresh-window-seconds 120
```

Resultat observe :

- public scan : 338 trades publics, 167 wallets vus, 50 promus ;
- userFills scan : 10 wallets, 5 fills, 5 deltas, 0 stale ;
- copy-run : 239 signaux analyses, 2 entrees paper candidates acceptees ;
- readiness : `SIMULATION_ACTIVE`, 50 leaders frais, 5 deltas recents, 2 deltas d'entree frais ;
- ordres reels : 0.

### Tests relances apres addendum

- `python -m pytest -q tests\test_copy_signal_detector.py tests\test_simulation_live_filters.py`
  - 13 passed.

- `python -m pytest -q tests\test_runtime_session_logs.py`
  - 2 passed.

- `python -m pytest -q tests\test_copy_signal_detector.py tests\test_simulation_live_filters.py tests\test_runtime_session_logs.py tests\test_ui_simulation_status_fast.py tests\test_hypersmart_single_launcher.py`
  - 46 passed.

- `python -m hyper_smart_observer.app.main --safety-check`
  - OK.

- `python -m hyper_smart_observer.app.main --audit-safety`
  - OK.

### Limite restante apres addendum

Le dossier actif `logs/logs a envoyer` est maintenant propre sauf `hypersmart_observer.log`, encore verrouille par Windows. Le fichier n'a pas ete supprime ni force. A traiter par fermeture propre du processus qui le tient, puis relance de `prepare-simulation-logs`.
