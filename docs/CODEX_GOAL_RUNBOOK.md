# Codex Goal Runbook — Alina SmartFlow Discovery V3.2

Ce runbook est **lazy-load**. `AGENTS.md` route d'abord vers le context pack ; ne lire ce document que pour une vraie décision de recherche. Codex reste **un seul agent LLM** : **aucun sous-agent** IA dans une campagne économique.

## 1. Reprise à coût modèle minimal

Toujours commencer par :
`python tools/codex_research_context.py --auto`

Lire ce **résumé compact** avant toute autre exploration. Il contient HEAD/famille, état `HYPOTHESIS_LEDGER`, `PROCESS_MEMORY`, veto motifs, trial accounting, état semantic discovery, surfaces disponibles et actions admissibles.

Règle de quota : **1 décision modèle -> gros batch local -> résumé compact -> 1 décision modèle**.
Pas de scan de l'historique Git complet, pas de scan des 775 optimisations scellées, pas de gros raw logs/trials pour reconstruire l'état. Si `base_sha` diffère de HEAD : inspecter seulement le **delta Git** pertinent. `docs/CURRENT_STATE.md` ou d'autres docs ne sont lus que si le context pack laisse une ambiguïté ciblée.

## 2. Mission et preuve machine

Même SHA certifié de `main`, sans compensation :
- `copy_vault >= +4.00 USD NET/jour PROUVÉS` ;
- `lead_lag >= +4.00 USD NET/jour PROUVÉS` ;
- `cross_venue_dislocation_v2 >= +4.00 USD NET/jour PROUVÉS`.

Suivre les gates du HEAD exact. Le contrat courant demande notamment **2 jours UTC complets**, couverture >= **0.99**, coûts complets, forward strict post-freeze et certification finale `python tools/run_daily_economic_certification.py .`.

## 3. Mémoire V3.2

Ledgers locaux append-only :
- `runtime/codex_research/HYPOTHESIS_LEDGER.jsonl` ;
- `runtime/codex_research/PROCESS_MEMORY.jsonl`.

Historique stable non certifiant : `docs/quant/HISTORICAL_EXPERIMENT_MEMORY.jsonl`.

Commandes V3.1 conservées : `codex_hypothesis_ledger.py register|score|status|needs-rediscovery|needs-challenger`.
La mémoire négative haute confiance peut veto un mécanisme+contexte équivalent après échecs répétés ; un **retest** reste permis avec donnée/surface nouvelle, changement causal matériel ou contradiction fraîche. La mémoire positive est un petit prior borné, jamais une preuve.

Lead-Lag maker/taker/streaming, Cross-Venue V5 et les lignées Copy-Vault déjà présentes au HEAD sont des baselines existantes, pas de la nouveauté automatique.

## 4. DISCOVERY V3.2

Charger `$alina-quant-research` et `references/discovery-v32.md` seulement à l'entrée en Discovery, Rediscovery ou champion-challenger.

Pool modèle : 12 hypothèses structurellement distinctes par défaut, minimum 8, >=5 archétypes. Un seuil/fenêtre/seed seul = `PARAMETER_ONLY`, pas une nouvelle hypothèse.

Avant d'utiliser un tour modèle pour inventer toutes les combinaisons, lancer le moteur local :
`python tools/codex_semantic_discovery.py --family <family> --pool-size 2000 --shortlist 12`

Il peut étendre le pool jusqu'à 1 000-20 000 combinaisons CPU si utile, filtrer invalides, doublons/near-doublons et veto mémoire, scorer nouveauté/undercoverage/faisabilité/coût de falsification/headroom, puis n'exposer que la shortlist au modèle. Le score est une priorité de recherche, **jamais** une certification économique.

Recherche externe : une passe groupée seulement si elle agrandit réellement l'espace causal absent du ledger ; convertir toute trouvaille en hypothèse locale falsifiable, puis revenir au calcul local.

## 5. TOURNAMENT -> EXPLOIT

TOURNAMENT : falsifier à bas coût et classer par nouveauté, causalité, données disponibles, headroom NET, gain d'information et coût de falsification. Une bonne cible est actionnable : quantile/distribution de markout, probabilité/taille d'un move couvrant les coûts, hazard/temps jusqu'au move, fill/adverse-selection ou expected NET edge.

EXPLOIT : seulement sur survivants. Utiliser le PC : grid/random/QMC/TPE/Optuna/CMA-ES/NSGA-II/Halving/Hyperband, walk-forward, purge/embargo, CPCV/CSCV/PBO, DSR/PSR, bootstrap, permutations/placebos/nulls, Monte-Carlo, ablations, plateaux, leave-one-out et stress d'exécution selon pertinence.

Une campagne : `EXPERIMENT_SPEC.json -> python tools/codex_quant_experiment.py <spec> -> RESULT_SUMMARY.json`.
Plusieurs : `BATCH_SPEC.json -> python tools/codex_quant_batch.py <batch> -> BATCH_SUMMARY.json`.
Le batch finit sans round-trip modèle interne. CPU-first ; parallélisme local libre ; GPU seulement sur justification mesurée.

## 6. Anti-boucle

Après résultat matériel : ledger + signatures + `trial_count` + progrès économique + action `IMPROVE|COMBINE|PIVOT|STOP`.

`needs-rediscovery` : 2 `PARAMETER_ONLY` comparables sans progrès, ou 2 évaluations/rejets à headroom non positif => PIVOT.
`needs-challenger` : après 3 `IMPROVE` consécutifs sans FREEZE, tester >=4 challengers orthogonaux avant un 4e improve.

Tous les essais comptent. OOS/forward observé puis utilisé pour retuner = feedback, donc refreeze + nouvelle preuve disjointe. Frais, spread, slippage, latence, capacité, fill, liquidatabilité, positions fermées, provenance, placebos et no-lookahead restent obligatoires.

## 7. Done

Ne jamais baisser une gate, ignorer un test ou transformer `None` en 0 pour fabriquer du vert. Si seul le temps/nouvelles données manque, laisser les collecteurs locaux nécessaires tourner et arrêter les tours modèle inutiles.

DONE économique uniquement quand `python tools/run_daily_economic_certification.py .` certifie séparément les trois familles sur le même SHA, avec toutes les gates du HEAD vertes.
