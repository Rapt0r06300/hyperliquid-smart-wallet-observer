# Codex Goal Runbook — Alina SmartFlow Discovery V3.1

Ce runbook complète `AGENTS.md`. Codex agit comme **un seul agent LLM** contrôleur de recherche quantitative : il invente/choisit les expériences ; le PC exécute tout calcul déterministe ou numérique faisable localement. **Aucun sous-agent** IA, spawn, fan-out ou reviewer-agent.

## Résultat final et vérité machine

Sur le même SHA certifié de `main`, obtenir séparément et sans compensation :

- `copy_vault >= +4.00 USD NET/jour PROUVÉS` ;
- `lead_lag >= +4.00 USD NET/jour PROUVÉS` ;
- `cross_venue_dislocation_v2 >= +4.00 USD NET/jour PROUVÉS`.

Toujours suivre les gates du HEAD exact. Le contrat courant exige notamment au moins **2 jours UTC complets** dans la preuve quotidienne canonique et la certification finale `python tools/run_daily_economic_certification.py .`, avec forward strict post-freeze, couverture >= **0.99**, coûts complets et taux net >= +4.00 USD/jour.

## Principe quota : le modèle décide, le PC calcule

Conserver les tours modèle, pas le CPU. Préférer :

`1 décision modèle -> gros batch local -> résumé compact -> 1 décision modèle`

à des dizaines de tours autour de calculs reproductibles.

Tout calcul faisable sur le PC doit être local : Python, numpy/scipy, pytest, replays, backtests, optimisation, estimation, bootstrap, permutations, Monte-Carlo, causalité temporelle, profiling et agrégation. Le runner est CPU-first ; CUDA/ROCm/HIP/JAX sont masqués par défaut. Threads, multiprocessing, batchs et workers CPU sont autorisés. GPU seulement si le CPU est réellement inadéquat et la raison est mesurée.

Pour une expérience :
`EXPERIMENT_SPEC.json -> python tools/codex_quant_experiment.py <spec> -> RESULT_SUMMARY.json`

Pour plusieurs expériences pré-définies :
`BATCH_SPEC.json -> python tools/codex_quant_batch.py <batch> -> BATCH_SUMMARY.json`

Le batch doit finir **sans round-trip modèle interne**. Si 1 000 ou 10 000 calculs indépendants peuvent être pré-définis, les lancer localement avant le prochain tour modèle. Les gros logs/trials/SQLite restent sur disque ; lire d'abord les résumés compacts.

## Mémoire : ne pas oublier ni rebaptiser l'ancien travail

Ledger local append-only : `runtime/codex_research/HYPOTHESIS_LEDGER.jsonl`.

Commandes :

- `python tools/codex_hypothesis_ledger.py register <record.json>`
- `python tools/codex_hypothesis_ledger.py score <record.json>`
- `python tools/codex_hypothesis_ledger.py status --family <family>`
- `python tools/codex_hypothesis_ledger.py needs-rediscovery <hypothesis_id>`
- `python tools/codex_hypothesis_ledger.py needs-challenger <hypothesis_id>`

Au premier cycle, bootstrapper l'historique utile comme `baseline=true` depuis le HEAD, `docs/LOIS_MESUREES.md`, `tools/recherche_14h_mecanismes.py` et uniquement les commits économiques/recherche récents nécessaires. **Lead-Lag maker/taker/streaming**, **Cross-Venue V5** et les lignées **Copy-Vault** courantes sont du travail existant, pas de la nouveauté automatique.

Chaque record peut porter `base_sha`. Si HEAD avance, inspecter seulement le **delta Git** pertinent et enregistrer les nouvelles lignées/baselines. Ne pas rescanner tout l'historique.

## Boucle obligatoire : DISCOVERY -> TOURNAMENT -> EXPLOIT -> FREEZE / REDISCOVERY

### DISCOVERY

Lire `.agents/skills/alina-quant-research/references/discovery-v31.md` uniquement pendant Discovery/champion-challenger.

Par défaut produire **12 hypothèses structurellement distinctes** ; minimum dur 8 ; viser au moins **5 archétypes de mécanisme**. Un changement de seuil, fenêtre, seed, horizon ou hyperparamètre ne compte pas comme nouvelle hypothèse.

Chaque hypothèse précise : mécanisme causal, surfaces de données, opérateur temporel/event-time, conditionnement/régime, cible future actionnable, traduction paper, raison causale et test de falsification. Scorer/enregistrer les candidats ; un doublon sémantique ne compte pas.

Recherche externe proactive autorisée au début d'un cycle lorsque cela élargit l'espace : Exa + Parallel Search pour web/praticiens, Consensus pour littérature, GitHub pour code/repos, CoinGecko seulement pour contexte de régime. Chercher des **mécanismes absents du ledger**, pas une confirmation de l'incumbent. Toute trouvaille doit devenir une hypothèse locale falsifiable.

Espaces possibles, non limitatifs : wallet informativeness/toxicité/anticipation cross-venue ; wallet × L2/order-flow ; price discovery asynchrone ; event-time/queue/absorption/depletion ; spillovers cross-asset ; Hawkes/VAR/VECM/transfer-entropy ; liquidations/OI/basis/funding ; régimes/changepoints ; micro-saisonnalité ; targets probabilistes/quantiles/hazard ; interactions non linéaires CPU.

### TOURNAMENT

Falsifier à bas coût avant de consacrer un gros budget. Classer par nouveauté, plausibilité causale, données réellement disponibles, horizon exploitable, headroom NET après coûts, gain d'information attendu et coût de falsification.

Le bon candidat prédit une quantité actionnable : distribution/quantiles du markout futur, probabilité/taille d'un move couvrant les coûts, temps/hazard jusqu'au move, probabilité de fill/adverse selection, ou expected NET edge. Accuracy, R², IC ou Sharpe train ne remplacent jamais l'économie OOS.

### EXPLOIT

Sur les survivants seulement, utiliser massivement le CPU local : grid/random/QMC/TPE/Optuna/CMA-ES/NSGA-II/Successive-Halving/Hyperband, recherche coarse-to-fine, multi-seed, walk-forward, purge/embargo, CPCV/CSCV/PBO, PSR/DSR, Reality Check, block/stationary bootstrap, permutations/placebos/nulls, Monte-Carlo, ablations, sensibilité/plateaux, leave-one-coin/wallet/regime-out et stress fees/spread/slippage/latence/capacité/fill selon pertinence.

Escalader les modèles seulement si les baselines survivent : event studies/conditional statistics -> modèles linéaires/probabilistes -> méthodes temporelles/microstructure -> modèles non linéaires CPU -> ensembles/régimes. Toute complexité doit ajouter une valeur économique OOS incrémentale après coûts.

### ANTI-BOUCLE / REDISCOVERY / CHAMPION-CHALLENGER

Après chaque résultat matériel, enregistrer `experiment_ids`, signatures, `trial_count`, verdict, progrès économique et `controller_action`.

Exécuter `needs-rediscovery`. Deux retunings `PARAMETER_ONLY` sans progrès comparable positif, deux évaluations à headroom non positif/rejetées, un doublon épuisé ou l'absence de nouvelle raison causale imposent `PIVOT` vers Discovery.

Exécuter aussi `needs-challenger`. Après **3 décisions `IMPROVE` consécutives sans FREEZE**, lancer un mini-Discovery de >=4 challengers orthogonaux avant une quatrième amélioration locale. L'incumbent n'est pas automatiquement tué : il doit simplement battre les challengers.

`IMPROVE` = progrès économique réel ; `COMBINE` = complémentarité OOS mesurée ; `PIVOT` = nouveau mécanisme ; `STOP` = lignée épuisée, jamais fin de la mission globale.

## Anti-overfit / preuve finale

Tous les essais distincts comptent. Le search/feedback window est adaptatif ; la preuve finale ne l'est pas. Toute validation/OOS/forward observée puis utilisée pour retuner devient exploratoire : refreeze puis preuve temporellement disjointe.

Chercher des plateaux robustes, pas un optimum ponctuel. Conserver les baselines simples. Ne jamais abaisser sécurité, coûts, liquidabilité ou gates pour obtenir un PASS.

## Quota Plus

- GPT-5.6 Sol High/Élevé, Standard, Fast OFF.
- Un seul agent LLM ; aucun sous-agent.
- XHigh seulement pour un verrou scientifique/architectural exceptionnel.
- Parallélisme local non-LLM libre.
- Sorties courtes ; état machine-readable sur disque.
- Cache/déduplication des signatures ; pas de gros run identique sans changement scientifique ou raison de reproductibilité.

## Done

DONE uniquement lorsque `python tools/run_daily_economic_certification.py .` certifie les trois familles séparément sur le même SHA avec le contrat machine courant : >=2 jours UTC complets à >=+4 USD NET/jour, OOS/forward requis, forward strict post-freeze, coûts/liquidabilité/identités/placebos/causalité, puis gates techniques finales vertes.

Si seul du temps ou de nouvelles données manque, laisser les collecteurs locaux nécessaires tourner et cesser les tours modèle inutiles.
