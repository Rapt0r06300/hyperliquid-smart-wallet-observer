# HyperSmart mega audit - 2026-06-29

Statut: PARTIAL, audit local réel effectué sur `C:\Users\flo\Desktop\Projet invest`.

Doctrine conservée:

- Hyperliquid runtime par défaut.
- Simulation locale paper uniquement.
- Aucune action argent réel.
- Aucun `/exchange` opérationnel.
- Aucune clé privée, signature ou wallet connect.
- Aucun PnL inventé, aucune position inventée, aucun graphe fake.
- Un PnL positif ne peut pas être garanti; l'objectif est de supprimer les bugs, les faux positifs et les mauvaises décisions mécaniques.

## Résumé exécutif

Le PnL négatif observé ne vient pas d'un seul bug. Les logs montrent un mélange de causes:

1. Des événements marqués `REJECT_*` par le pipeline V9 pouvaient encore devenir des positions paper si le lanceur n'activait pas le mode autoritaire.
2. Des réductions partielles trop petites et/ou trop tardives saignaient les frais.
3. Des opportunités sans `current_mid` réel pouvaient être évaluées avec un prix de référence de leader, ce qui n'est pas assez sûr pour une simulation portefeuille.
4. Un close direct de type fusion/GitHub a créé un pic de perte important (`SOL SHORT`, environ `-0.69 USDC`).
5. La DB de session est énorme, environ `20.77 GB`, ce qui peut ralentir l'UI et provoquer des impressions de saut/stutter.
6. Le serveur local `127.0.0.1:8794` n'était pas en écoute pendant cet audit; l'écran navigateur vu était donc ancien ou figé.
7. `logs/logs à envoyer` contient encore des traces legacy dYdX dans certains fichiers historiques; le lanceur actuel ne démarre pas dYdX, mais ces traces rendent l'analyse confuse.

## Preuves collectées

Commandes et observations:

- `Get-NetTCPConnection -LocalPort 8794`: `PORT_8794_NOT_LISTENING`.
- DB session: `runtime/data/hypersmart_simulation_session.sqlite3`, taille `20774563840` octets.
- `python -m hyper_smart_observer.app.main --safety-check`: `Safety check: OK`.
- `python -m hyper_smart_observer.app.main --audit-safety`: OK sur `/exchange`, signatures, ordres opérationnels, clés privées, dashboard dangerous buttons, mainnet/testnet.
- `python -m hyper_smart_observer.app.main --runtime-check`: archive ready, aucun ZIP/7Z/RAR racine, warning legacy `logs/hl_observer.sqlite3`.
- `python -m hyper_smart_observer.app.main --archive-audit`: rapport écrit dans `docs/release/HYPERSMART_ARCHIVE_AUDIT.md`.

Extrait synthétique des logs `logs/logs à envoyer/simulation_resume_pour_chatgpt.md`:

- Equity actuelle: `998.847351`.
- PnL courant: `-1.152649`.
- PnL réalisé: `-1.016645`.
- PnL latent: `-0.136005`.
- Coûts payés: `0.694087`.
- Refus locaux: `960`.
- Entrées virtuelles reproduites: `5`.
- Sorties/reductions reproduites: `54`.
- Plus grosse perte récente: `SOL SHORT`, `FUSION_DIRECT_PAPER_CLOSE`, `-0.69182086`.

## Correctifs appliqués pendant cet audit

### 1. V9 devient autoritaire au lancement

Cause:

Les logs montraient des entrées paper avec `v9_decision = REJECT_TOO_ILLIQUID` ou `REJECT_EDGE_TOO_SMALL`. Le code savait bloquer ces entrées si `HYPERSMART_V9_PIPELINE_AUTHORITATIVE=1`, mais le lanceur principal ne le définissait pas.

Correction:

- `LANCER_HYPERSMART.cmd` définit maintenant `HYPERSMART_V9_PIPELINE_AUTHORITATIVE=1`.
- `tools/start_hypersmart_simulation.ps1` définit maintenant `HYPERSMART_V9_PIPELINE_AUTHORITATIVE=1`.
- Tests ajoutés pour éviter la régression dans `tests/test_hypersmart_single_launcher.py` et `tests/test_hypersmart_github_fusion.py`.

Impact attendu:

Les événements explicitement refusés par V9 ne doivent plus ouvrir de position paper lors d'un lancement normal.

### 2. Fraîcheur signal séparée de la fenêtre d'audit

Cause:

`opportunity-report --active-window-seconds 120` pouvait gonfler indirectement la tolérance de fraîcheur utilisée par le scoring.

Correction:

- `src/hl_observer/cli.py` garde une fenêtre d'audit longue pour observer, mais utilise une fenêtre de trading paper plafonnée et configurée via `HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS`.
- Valeur par défaut: `15000 ms`, cap dur `60000 ms`.

Impact attendu:

Un signal vieux reste visible dans les rapports, mais ne devient pas une entrée paper exploitable.

### 3. `current_mid` réel obligatoire pour une entrée de simulation portefeuille

Cause:

Un prix de leader ou un prix de fill n'est pas suffisant pour marquer le portefeuille paper au marché réel. Sans `allMids/current_mid`, le PnL peut être mal interprété.

Correction:

- `src/hl_observer/opportunities/fresh_opportunity.py` refuse les signaux sans mid réel avec `CURRENT_MID_REQUIRED_FOR_LOCAL_SIMULATION`.

Impact attendu:

Moins de trades, mais une simulation plus honnête: le graphe et l'equity dépendent du marché réel disponible.

### 4. Réductions partielles: anti frais et anti stale

Cause:

Les logs montraient beaucoup de `REDUCE` BTC très petits et/ou vieux, qui ajoutaient du coût sans vrai bénéfice.

Correction:

- `src/hl_observer/ui/routes.py` refuse les micro-réductions sous `HYPERSMART_MIN_REDUCE_NOTIONAL_USDT=10`.
- `src/hl_observer/ui/routes.py` refuse les réductions trop vieilles avec `HYPERSMART_REDUCE_MAX_SIGNAL_AGE_MS=15000`.
- Les closes complets restent possibles via la logique de sortie, mais les petits reduces tardifs ne mutent plus l'état paper.

Impact attendu:

Moins de fee bleed, moins de petits événements qui font bouger le graphe sans vraie décision.

### 5. Direct fusion/arbitrage paper durci

Cause:

Les moteurs GitHub/fusion peuvent produire des ordres paper directs. Un direct close a contribué à la plus grosse perte.

Correction:

- `src/hl_observer/ui/fusion_persistent_adapter.py` exige maintenant des sources distinctes pour l'arbitrage direct.
- Spread minimum par défaut: `HYPERSMART_DIRECT_ARBITRAGE_MIN_SPREAD_BPS=30`.
- Refus explicites: `DIRECT_ARBITRAGE_REQUIRES_DISTINCT_SOURCES`, `DIRECT_ARBITRAGE_SPREAD_TOO_SMALL`.

Impact attendu:

Les moteurs externes paper restent observables, mais ne doivent plus injecter des décisions directes faibles ou mal justifiées.

### 6. Lancement dashboard plus robuste

Cause:

Le navigateur pouvait s'ouvrir alors que le serveur local n'était pas prêt, donnant un écran `ERR_CONNECTION_REFUSED`.

Correction:

- `tools/start_hypersmart_simulation.ps1` attend plus longtemps la readiness UI.
- Il n'ouvre le dashboard que si l'API répond.
- Il logge clairement si le serveur UI s'arrête juste après le lancement.

Impact attendu:

Moins de faux diagnostic "page morte" quand le navigateur part trop tôt.

## Tests lancés

Tous les tests ciblés ci-dessous passent:

```powershell
python -m pytest -q tests/test_hypersmart_single_launcher.py tests/test_hypersmart_github_fusion.py tests/test_start_script_preserves_6s_freshness_guard.py
# 17 passed

python -m pytest -q tests/test_fresh_opportunity.py tests/test_ui_simulation_status_fast.py::test_status_persists_accepted_fusion_paper_order_into_simulation_state tests/test_ui_simulation_status_fast.py::test_status_persists_external_arbitrage_paper_order_when_copy_conflicts tests/test_ui_simulation_persistence.py::test_ui_simulation_reduce_is_partial_and_visible_in_fast_status tests/test_ui_simulation_persistence.py::test_ui_simulation_refuses_stale_matching_leader_close_without_touching_position tests/test_ui_simulation_persistence.py::test_ui_simulation_refuses_entries_when_expected_dollar_edge_is_too_small
# 10 passed

python -m pytest -q tests/test_no_exchange_sdk_imports_or_actions.py tests/test_hypersmart_v19_no_real_trade.py tests/test_pnl_loss_fixes.py tests/test_hypersmart_v19_negative_pnl_audit.py tests/test_v9_sltp_runtime.py
# 24 passed
```

Safety:

```powershell
python -m hyper_smart_observer.app.main --safety-check
# Safety check: OK

python -m hyper_smart_observer.app.main --audit-safety
# OK sur /exchange, signatures, ordres opérationnels, clés privées, dashboard, mainnet/testnet
```

Runtime/archive:

```powershell
python -m hyper_smart_observer.app.main --runtime-check
# archive_ready: True, root_archives_zip_7z_rar: 0, warning legacy logs/hl_observer.sqlite3

python -m hyper_smart_observer.app.main --archive-audit
# docs/release/HYPERSMART_ARCHIVE_AUDIT.md
```

## Bugs encore ouverts

### A. DB de session trop volumineuse

La DB `runtime/data/hypersmart_simulation_session.sqlite3` pèse environ `20.77 GB`.

Risque:

- UI lente.
- Graphes qui sautent.
- Requêtes status trop lourdes.
- PC ralenti.

Correction recommandée:

- Ajouter une commande non destructive `simulation-db-retention-report`.
- Ajouter ensuite une rotation contrôlée par session, avec archivage compact, jamais suppression brutale.
- Indexer/limiter les requêtes UI aux dernières fenêtres utiles.

### B. Logs historiques confus

`logs/logs à envoyer` peut conserver des traces legacy, y compris dYdX. Le lanceur actuel ne démarre pas dYdX, mais les anciens fichiers polluent l'analyse.

Correction recommandée:

- Renforcer `prepare-simulation-logs` pour marquer explicitement les warnings de fichiers verrouillés.
- Ajouter au résumé une section "ancien log non archivé car verrouillé".
- Ne jamais supprimer brutalement.

### C. V12 artifacts absents

Le chemin `runtime/data/hypersmart_v12_artifacts.sqlite3` est configuré, mais le fichier n'était pas présent pendant l'audit.

Risque:

- Les modules V12 peuvent écrire ailleurs ou ne pas écrire.
- Dashboard V12 incomplet.

Correction recommandée:

- Ajouter un test de smoke runtime qui vérifie qu'un run crée/alimente l'artifact V12 attendu.

### D. Tables de décision formelles vides

Les tables `follow_decisions`, `paper_follow_orders`, `risk_events` étaient vides dans l'échantillon DB, alors que la simulation écrit des événements dans le ledger JSON/state.

Risque:

- Dashboard et logs ne lisent pas tous la même source.
- Audit difficile.

Correction recommandée:

- Écrire chaque décision importante dans une table unique `decision_ledger`.
- Faire pointer UI, logs, no-trade explorer et export vers ce ledger.

### E. NO_TRADE Explorer incomplet

L'UI affiche parfois "Aucune donnée" alors que les logs listent des refus.

Correction recommandée:

- Brancher le panneau NO_TRADE sur le ledger réel de simulation.
- Afficher les top reasons, coin, wallet, âge signal, edge, coût, source, action recommandée.

### F. Moteurs GitHub/fusion trop permissifs ou trop opaques

L'UI indique `34/34` moteurs actifs, mais l'effet réel sur les entrées/sorties est encore opaque.

Correction recommandée:

- Ajouter un rapport par moteur: candidats proposés, acceptés, refusés, PnL réalisé, PnL latent, raison de chaque veto.
- Interdire qu'un moteur direct ouvre/ferme sans evidence chain minimale.

## Prochaine priorité exacte

1. Relancer `LANCER_HYPERSMART.cmd` avec les correctifs actuels.
2. Observer 10 à 20 minutes.
3. Exporter `logs/logs à envoyer`.
4. Vérifier que les nouveaux événements `REJECT_*` V9 restent `NO_TRADE`.
5. Corriger ensuite la dette la plus lourde: DB `20.77 GB` + ledger unifié + NO_TRADE Explorer.

## Conclusion

Cet audit n'a pas "forcé" un PnL positif. Il a corrigé des causes réelles de PnL négatif mécanique:

- entrées paper malgré rejet V9;
- signaux vieux acceptés via fenêtre d'audit;
- simulation sans mid réel;
- micro-réductions fee-dominées;
- arbitrage/direct fusion insuffisamment prouvé;
- ouverture navigateur avant readiness serveur.

La simulation est plus stricte et plus honnête. Le prochain vrai test est un nouveau run propre, car le serveur n'était pas en écoute au moment de l'audit et les logs existants reflètent l'ancien comportement.
