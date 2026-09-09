# Codex Goal Runbook — Alina SmartFlow

Ce runbook complète `AGENTS.md`. Il explique **comment chercher** l'edge sans imposer une stratégie fixe. Codex doit découvrir lui-même les mécanismes, expériences, backtests et tests statistiques adaptés aux données.

## Résultat final

Sur le même SHA certifié de `main`, obtenir séparément et sans compensation :

- `copy_vault >= +4.00 USD NET/jour PROUVÉS` ;
- `lead_lag >= +4.00 USD NET/jour PROUVÉS` ;
- `cross_venue_dislocation_v2 >= +4.00 USD NET/jour PROUVÉS`.

La gate économique historique `economic_objective.py` reste la preuve de base. La définition finale du succès est `python tools/run_daily_economic_certification.py .` : base complète + au moins 86 400 secondes de forward strictement post-freeze observé + net forward normalisé >= +4.00 USD/jour pour chacune des trois familles. Durée absente ou non prouvée => `NO_GO`.

## Règle principale : conserver les tours modèle, pas le CPU

Le quota GPT doit servir surtout à **choisir les expériences à forte valeur d'information, interpréter les résumés et décider la suite**. Tout calcul que le PC peut faire doit être exécuté localement : Python, numpy/scipy, pytest, replays, backtests, optimisations, bootstrap, permutations, Monte-Carlo, CPCV/CSCV, PBO, DSR/PSR, stress tests, profiling, agrégations et comparaisons.

Un calcul local peut prendre longtemps et utiliser fortement le CPU si l'expérience est bien conçue. Ne pas découper un calcul déterministe en dizaines de conversations Codex. Préférer **1 décision modèle -> gros batch local -> 1 résumé compact -> 1 nouvelle décision**.

Le runner standard est CPU-first : `tools/codex_quant_experiment.py` masque CUDA/ROCm/HIP/JAX GPU et expose `ALINA_CPU_WORKERS`. Le GPU n'est pas interdit partout, mais il n'est jamais le choix par défaut ; ne l'utiliser hors runner que si le gain est réellement nécessaire et documenté.

Le parallélisme local est autorisé : threads, multiprocessing, batchs, workers CPU, vectorisation et jobs locaux ne sont **pas** des sous-agents. Éviter seulement l'oversubscription inutile ; mesurer avant de multiplier des processus qui utilisent chacun tous les cœurs.

## Boucle Codex Quant locale

Utiliser en priorité `$alina-quant-research`.

Pour une seule campagne :

`EXPERIMENT_SPEC.json -> python tools/codex_quant_experiment.py <spec> -> RESULT_SUMMARY.json`

Pour plusieurs expériences déjà décidées :

`BATCH_SPEC.json -> python tools/codex_quant_batch.py <batch> -> BATCH_SUMMARY.json`

Le batch runner exécute toutes les expériences déclarées localement avant de revenir au modèle : **0 round-trip modèle à l'intérieur du batch**. Il les orchestre séquentiellement par défaut car chaque recherche peut déjà utiliser le CPU disponible ; Codex peut construire des scripts locaux parallèles plus spécialisés si un benchmark montre que c'est plus rapide.

Les expériences réutilisent `tools/outils_recherche.py` : grid, random, QMC, TPE/Optuna, CMA-ES, NSGA-II, Successive-Halving et Hyperband. Une signature scientifique terminée vient du cache au lieu d'être recalculée. `--force` exige une justification et ne crée jamais une nouvelle preuve fraîche par magie.

Toujours lire `RESULT_SUMMARY.json` / `BATCH_SUMMARY.json` en premier. Les trials détaillés, SQLite et gros logs restent sur disque et ne sont ouverts que pour une anomalie précise. Si un output est énorme, écrire un script local qui le réduit avant lecture par le modèle.

## Funnel de recherche quantitative

Codex choisit les méthodes adaptées ; ceci est un menu, pas une checklist obligatoire :

1. **Faisabilité causale/économique** : mécanisme, timestamps, exécution, break-even après coûts.
2. **Recherche train coarse-to-fine** : TPE/QMC/CMA-ES ou autre moteur adapté ; pruning, Successive-Halving/Hyperband pour tuer tôt les mauvaises régions.
3. **Robustesse locale** : multi-seed si pertinent, voisinage/plateaux de paramètres, leave-one-coin/vault/regime-out, sous-échantillonnage, perturbations de seuils et coûts.
4. **Anti-overfit** : purging/embargo, walk-forward, CPCV/CSCV/PBO, PSR/Deflated Sharpe, Reality Check si adapté, block/stationary bootstrap, permutations/placebos/nulls et correction du multiple testing.
5. **Réalité d'exécution** : fees, bid/ask, profondeur/VWAP, slippage, latence, capacité, fill, stale data, liquidabilité et positions closes.
6. **Freeze** du candidat sélectionné sans utiliser la future preuve.
7. **OOS disjoint**, puis **forward strictement post-freeze**.
8. **Certification quotidienne finale** sur une vraie durée forward mesurée, jamais extrapolée depuis quelques minutes.

Le nombre réel de variantes essayées fait partie de la preuve. Enregistrer aussi les échecs. Chercher des plateaux/stabilité plutôt qu'un pic isolé. Un train excellent ou 10 000 trials ne valent rien sans preuve fraîche.

## Liberté de stratégie

Codex peut modifier ou remplacer tout ce qui est une **hypothèse de recherche** : seuils, fenêtres, features, filtres, scoring, univers, sizing paper, logique entrée/sortie, maker/taker paper, collecteurs, algorithmes, architecture et versions de stratégie. Il peut abandonner une piste, créer une vNext ou revenir à une approche plus simple.

Cette liberté ne permet jamais de baisser une gate de sécurité/preuve pour fabriquer un PASS. Paper-only, coûts réalistes, causalité/no-lookahead, provenance, positions closes, identité/déduplication, liquidabilité, OOS, forward post-freeze et durée quotidienne réelle restent non négociables.

Si OOS/validation/forward déjà observé influence un retuning, ce segment devient exploratoire/train. Il faut alors refreeze puis obtenir une nouvelle preuve temporellement disjointe.

## Recherche externe

Local d'abord. Quand une information absente bloque une nouvelle hypothèse :

- **Exa + Parallel Search** : microstructure, praticiens, bots/repos comparables, Hyperliquid/perps, exécution et nouvelles pistes ;
- **Consensus** : littérature scientifique sur microstructure, causalité, validation et multiple testing ;
- **GitHub** : code/CI/artifacts/repos précis ;
- **Superpowers** : systematic-debugging, TDD et verification utiles au problème courant.

Ne jamais appeler tous les plugins par réflexe. Formuler la question précise, rechercher en batch, dédupliquer, extraire quelques hypothèses falsifiables, puis revenir au PC.

## Politique quota Plus

**Un seul agent LLM principal.** Aucun sous-agent, spawn, fan-out ou reviewer-agent. Cette règle n'interdit aucun calcul local non-LLM.

- GPT-5.6 Sol **High/Élevé**, Standard, Fast OFF.
- XHigh seulement pour une réflexion exceptionnelle réellement difficile, pas pour exécuter/tester.
- Grouper les lectures et commandes indépendantes.
- Sorties modèle courtes ; résultats lourds machine-readable sur disque.
- Pas de relecture systématique des 775 tâches, de l'historique complet ou de tous les rapports.
- Pas de gros run identique sans changement de code, données, hypothèse ou objectif de reproductibilité.
- Si 1 000 ou 100 000 calculs peuvent être exécutés par un script local sans décision intermédiaire du modèle, préférer ce script/batch aux 1 000 tours Codex.

Le calcul local lui-même ne consomme pas de tokens modèle ; Codex consomme encore du quota pour décider quoi lancer et pour interpréter les résultats. Le but est donc de maximiser la quantité de science locale utile entre deux appels au modèle.

## Done

DONE uniquement lorsque `python tools/run_daily_economic_certification.py .` certifie les trois familles séparément à >= +4.00 USD NET/jour avec la preuve complète, puis que les gates techniques finales requises sont vertes sur le même SHA de `main`.

Si la seule chose manquante est du temps/données forward, laisser les collecteurs locaux nécessaires travailler et arrêter les tours modèle inutiles. Un ancien artifact, un résultat synthétique, un train positif ou une extrapolation de courte durée ne vaut jamais certification.
