# Relais Claude — amélioration replay et backtests

État initial vérifié le 2026-10-22 : dépôt local `C:\Users\flo\Desktop\Projet invest`, branche `main`, HEAD local et `origin/main` = `96696957158011558921dd1fa83ea3b8a5ec9ac7`. `git status` signale 158 fichiers `catalog/data-index-parts/` modifiés ; les préserver, ne pas faire de reset/clean ni les inclure dans un commit de code.

Mise à jour du travail local : `scenario_search.py` ne reclasse plus les finalistes au moyen du holdout OOS. Le test de régression a été observé rouge sur le code initial, puis vert après correction. Les 24 tests ciblés du chercheur et 79 tests d'intégration/simulation, ainsi que 25 tests supplémentaires de sécurité/simulation, ont passé. La suite globale et une preuve économique sur données réelles ne sont pas encore certifiées par ces résultats. Vérifier le HEAD et l'état Git à nouveau avant toute reprise.

## Mission

Améliorer au maximum **la qualité et, si les données le permettent, le PnL net robuste hors échantillon** des moteurs de replay/backtest des trois familles actives : Copy-Vault, Lead-Lag, Cross-Venue Dislocation. Ne jamais optimiser seulement l'apparence du rapport. Cible de recherche du contrat actuel : au moins +5 USD net par jour **par famille séparément** sur 200 USD paper, uniquement si une preuve valide la soutient. Un résultat négatif ou `MORE_DATA` est préférable à un faux positif.

## Autorité et frontières

Lire dans l'ordre `SECURITY.md`, `docs/HYPERSMART_CONSTITUTION.md`, les sections pertinentes de `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`, `docs/LOIS_MESUREES.md`, puis `AGENTS.md` et `CLAUDE.md`. Le runtime actif est `src/hl_observer/`. `hyper_smart_observer/` est legacy/compatibilité. Carry/Funding Carry est hors scope. Ne pas créer un second moteur replay, PnL, ledger, orchestrateur ou scoreboard.

Rester strictement **PAPER / READ-ONLY / FAIL-CLOSED** : aucun ordre mainnet/testnet, clé, signature ou endpoint d'exécution ; ne pas arrêter/toucher les collecteurs. Ne pas baisser fees, spread, slippage, latence, contraintes de capacité/fill, seuils ou tests pour obtenir un PnL positif. Aucune donnée `PARTIAL`/`REJECTED` en preuve. Les seuls shards admissibles sont `SAFE`, replay-compatibles, vérifiés par taille/hash et figés par campagne. Aucune donnée manquante remplacée par zéro, timestamp ou fill inventé. OOS et forward restent disjoints du tuning.

## Cartographie de départ (à vérifier sur le HEAD avant modification)

- Contrôle final économique : `tools/run_daily_economic_certification.py` appelle `src/hl_observer/ops/daily_economic_certification.py` ; ce contrôle, pas un rapport exploratoire, décide de la certification.
- Preuve module : `src/hl_observer/control_plane/module_pnl_proof.py` exige SAFE + replay-compatible.
- Replay/données : `src/hl_observer/datasets/replay_workspace.py`, `src/hl_observer/backtesting/`, `src/hl_observer/control_plane/`.
- `src/hl_observer/backtesting/replay_engine.py` est un petit helper de délai, actuellement appelé seulement par un test selon la recherche statique ; **ne pas supposer qu'il est le moteur canonique de la campagne**.
- `src/hl_observer/backtesting/validation_gates.py` fournit des verdicts de **recherche** (`DEPLOY_CANDIDATE`) et est appelé par `scenario_search.py`, `ab_flag_replay.py` et `market_truth/validation.py`. Son lookahead peut être marqué `skipped` sans faire échouer ce verdict exploratoire ; vérifier qu'aucun chemin ne le confond avec la certification économique. Ne pas modifier le comportement avant cartographie des callers et tests.
- Tests de départ : `tests/test_daily_economic_certification.py`, `tests/test_final_economic_certification.py`, `tests/test_validation_gates.py`, `tests/test_backtest_live_parity.py`, `tests/test_backtest_replays_fills_deltas_books.py`, `tests/test_dataset_replay_workspace.py` et tests propres aux trois familles.

## Ordre de travail recommandé

1. Vérifier HEAD, état Git et callers actifs. Établir une baseline reproductible par famille (données/SHAs, config, coûts, nombre de trades, PnL net, drawdown, profit factor, couverture, statut OOS/forward). Si aucune preuve SAFE suffisante n'existe, déclarer `MORE_DATA`/`UNMEASURABLE` ; ne pas fabriquer un baseline.
2. Chercher un défaut **mesurable** dans le chemin canonique : causalité et horloges, événements dupliqués/gaps, fills partiels ou manqués, coût all-in, double comptage, état à deux jambes, split temporel/purge, contamination OOS, parité replay/forward. Prioriser la cause avec test de non-régression avant correction ; ne pas refactoriser en masse les helpers historiques.
3. Si l'intégrité est solide, tester des améliorations économiques causales sur chaque famille indépendamment (filtrage, timing, sélection, capacité), avec sélection sur TRAIN/validation seulement. Comparer à un baseline gelé sur OOS **intouché**, puis forward paper post-freeze ; garder tous les essais et placebos.
4. Vérifier au minimum les pannes et cas adverses : shard absent/corrompu/non-SAFE, timestamp manquant ou désordonné, doublon, gap BBO/L2, coût inconnu, fill partiel, hedge manqué, position non clôturée, OOS réutilisé, relance/reprise. Aucun de ces cas ne doit créer un profit certifié.
5. Exécuter les tests ciblés puis l'intégration adaptée ; fournir le diff exact, les commandes/résultats, les métriques avant/après à données et coûts identiques, le HEAD final et les blocages. Ne pas affirmer un gain sans replay réel et preuve hors échantillon. Ne pas pousser vers GitHub sans demande explicite.

Ce fichier est un relais de travail, **pas une nouvelle spec ni une preuve de résultat**. La spec canonique et les gates exécutables du HEAD priment.
