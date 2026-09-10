# Codex Goal Runbook — Alina SmartFlow Discovery V3

Ce runbook complète `AGENTS.md`. Il définit **comment découvrir puis tester** l'edge sans imposer une stratégie fixe. Codex doit agir comme un chercheur quantitatif autonome : explorer des mécanismes réellement différents, les falsifier localement, concentrer le CPU sur les survivants, puis revenir à Discovery dès qu'une lignée stagne.

## Résultat final et vérité machine

Sur le même SHA certifié de `main`, obtenir séparément et sans compensation :

- `copy_vault >= +4.00 USD NET/jour PROUVÉS` ;
- `lead_lag >= +4.00 USD NET/jour PROUVÉS` ;
- `cross_venue_dislocation_v2 >= +4.00 USD NET/jour PROUVÉS`.

Toujours relire les gates du HEAD exact. Au HEAD V3 de conception, `economic_objective.py` impose `TARGET_NET_USD_PER_DAY=4.0` et `MIN_PROOF_DAYS=2` : la preuve quotidienne canonique requiert donc au moins **2 jours UTC complets** et chaque jour doit atteindre la cible. La certification finale `python tools/run_daily_economic_certification.py .` ajoute le forward strictement post-freeze, au moins 86 400 secondes de temps mur vérifié, couverture >= 0,99 et taux net >= +4.00 USD/jour. Si les contrats machine évoluent, ils priment sur ce texte.

## Principe : Codex invente et décide, le PC calcule

Le quota modèle sert à choisir des hypothèses à forte valeur d'information, décider `IMPROVE / COMBINE / PIVOT / STOP`, interpréter les résumés et concevoir la prochaine expérience. Tout calcul faisable localement doit l'être : Python, numpy/scipy, pytest, replays, backtests, optimisation, estimation, bootstrap, permutations, Monte-Carlo, causalité temporelle, profiling et agrégation.

Un calcul CPU peut durer longtemps. Préférer :

`1 décision modèle -> gros travail local -> résumé compact -> 1 nouvelle décision`

au lieu de dizaines de tours modèle autour de calculs déterministes.

Le runner standard est CPU-first : `tools/codex_quant_experiment.py` masque CUDA/ROCm/HIP/JAX GPU et expose `ALINA_CPU_WORKERS`. Threads, multiprocessing, batchs et workers locaux ne sont pas des sous-agents. Le GPU n'est pas préféré et ne doit être utilisé que si le CPU est réellement inadéquat.

## Mémoire V3 : ne pas oublier ni rebaptiser l'ancien travail

Le ledger canonique local est :

`runtime/codex_research/HYPOTHESIS_LEDGER.jsonl`

Interface :

- `python tools/codex_hypothesis_ledger.py register <record.json>`
- `python tools/codex_hypothesis_ledger.py score <record.json>`
- `python tools/codex_hypothesis_ledger.py status --family <family>`
- `python tools/codex_hypothesis_ledger.py needs-rediscovery <hypothesis_id>`

Le ledger est append-only, n'est jamais une preuve de PnL et conserve hypothèse, lignée, sémantique, essais, signatures et progrès économique.

Au premier cycle V3, si le ledger est vide, créer un **bootstrap baseline** compact depuis le HEAD courant, `docs/LOIS_MESUREES.md`, `tools/recherche_14h_mecanismes.py` et les derniers commits économiques pertinents. Marquer `baseline=true`. Les dix mécanismes historiques, les lignées Lead-Lag maker/taker/streaming, Cross-Venue V5 et les lignées Copy-Vault déjà présentes au HEAD ne deviennent pas « nouvelles » simplement parce que le ledger est neuf.

Chaque record peut porter `base_sha`. Si HEAD change depuis le dernier record, inspecter seulement le delta Git pertinent et ajouter les nouvelles lignées/baselines nécessaires. Ne jamais rescanner tout l'historique à chaque reprise.

## Boucle obligatoire : DISCOVERY -> TOURNAMENT -> EXPLOIT -> FREEZE/REDISCOVERY

### 1. DISCOVERY

Entrer en Discovery au démarrage d'une nouvelle lignée et dès qu'une stagnation est détectée.

Générer **>=8 hypothèses structurellement distinctes** avant une nouvelle grosse campagne CPU. Un changement de seuil, fenêtre ou hyperparamètre ne compte pas comme nouvelle hypothèse.

Chaque hypothèse doit préciser au minimum :

- mécanisme économique ;
- surfaces de données ;
- opérateur temporel/event-time ;
- conditionnement/régime ;
- cible future prédite ;
- traduction en exécution paper ;
- rationale causale ;
- test qui la falsifie.

Enregistrer/scorer les candidats avec le ledger. Le score de nouveauté est local et déterministe ; il mesure la distance structurelle aux hypothèses déjà évaluées. Un doublon sémantique ne compte pas parmi les 8.

Une passe externe proactive est autorisée **une fois au début d'un cycle Discovery lorsqu'elle peut élargir l'espace de recherche** : Exa + Parallel Search pour web/praticiens, Consensus pour littérature, GitHub pour code/repos, CoinGecko seulement pour contexte de régime courant. Regrouper/dédupliquer la recherche et convertir rapidement les résultats en hypothèses locales falsifiables. Une page web ou un prix CoinGecko n'est jamais une preuve économique.

Espaces possibles, non obligatoires : wallet informativeness/toxicité/anticipation cross-venue ; wallet × L2/order-flow ; price discovery asynchrone ; représentations stationnaires/event-time ; spillovers cross-asset ; Hawkes/VAR/VECM/transfer-entropy ; liquidations/OI/basis/funding ; régimes de liquidité/volatilité ; micro-saisonnalité ; modèles linéaires ou non linéaires CPU si leur valeur incrémentale est mesurable.

### 2. TOURNAMENT

Avant de dépenser un gros budget, falsifier les candidats à bas coût puis classer les survivants sur plusieurs dimensions :

- nouveauté/non-redondance ;
- plausibilité causale ;
- données réellement disponibles et horodatées ;
- horizon exploitable ;
- headroom NET après coûts/exécution ;
- gain d'information attendu ;
- coût de falsification.

Ne pas sélectionner le gagnant sur le meilleur backtest brut. Une hypothèse utile doit viser une quantité actionnable : direction, probabilité/taille du move, timing/horizon et **edge net attendu après exécution**. Accuracy, R², IC ou Sharpe train ne remplacent jamais le PnL exécutable.

### 3. EXPLOIT

Pour un survivant, consacrer autant de calcul local que scientifiquement utile.

Une campagne :
`EXPERIMENT_SPEC.json -> python tools/codex_quant_experiment.py <spec> -> RESULT_SUMMARY.json`

Plusieurs campagnes pré-définies :
`BATCH_SPEC.json -> python tools/codex_quant_batch.py <batch> -> BATCH_SUMMARY.json`

Le batch doit finir localement sans round-trip modèle entre les expériences. Réutiliser grid, random, QMC, TPE/Optuna, CMA-ES, NSGA-II, Successive-Halving, Hyperband et les évaluateurs existants. Codex peut écrire des scripts locaux spécialisés pour lancer des campagnes beaucoup plus complexes lorsque nécessaire.

Menu de validation selon pertinence : walk-forward ; purging/embargo ; CPCV/CSCV/PBO ; PSR/Deflated Sharpe ; Reality Check ; block/stationary bootstrap ; permutation/placebo/null ; Monte-Carlo ; multi-seed ; sensibilité/plateaux ; leave-one-coin/wallet/regime-out ; stress fees/spread/slippage/latence/capacité/fill ; ablations ; comparaison de modèles simples/non-linéaires.

Le PC peut exécuter des centaines, milliers ou davantage de trials. Les gros artefacts restent sur disque. Lire `RESULT_SUMMARY.json`/`BATCH_SUMMARY.json` en premier et agréger localement avant d'ouvrir les détails.

Après chaque résultat matériel, ajouter au ledger les `experiment_ids`, signatures scientifiques, `trial_count`, verdict et progrès économique comparable.

### 4. ANTI-BOUCLE / REDISCOVERY

Après chaque itération, exécuter :

`python tools/codex_hypothesis_ledger.py needs-rediscovery <hypothesis_id>`

`PIVOT` vers Discovery si deux itérations consécutives sont seulement `PARAMETER_ONLY` sans progrès économique comparable positif, ou si deux évaluations consécutives conservent un headroom exécutable non positif/rejettent la lignée.

Ne pas confondre « j'ai modifié du code / ajouté une gate / obtenu un meilleur fit » avec un progrès économique.

`IMPROVE` : améliore une lignée qui montre un progrès réel.
`COMBINE` : recombine des mécanismes complémentaires, en gardant la certification finale de chaque famille séparée.
`PIVOT` : ouvre un nouveau mécanisme.
`STOP` : ferme une lignée épuisée ; ne termine pas la mission globale.

## Freeze, test final et anti-overfit

Le search/feedback window est adaptatif ; la preuve finale ne l'est pas. Tous les essais distincts sont comptés.

Si une validation/OOS/forward observée influence ensuite une modification, elle devient exploratoire. Refreeze puis utiliser une preuve temporellement disjointe. Ne jamais permettre au moteur de recherche d'optimiser directement la fenêtre qu'il présentera comme test final.

Chercher des plateaux et des mécanismes robustes plutôt qu'un optimum ponctuel. Conserver les baselines simples. Toute complexité supplémentaire doit démontrer une valeur incrémentale OOS après coûts.

## Recherche externe et marché courant

Les outils externes servent à **élargir ou préciser les hypothèses**, pas à rester dans une boucle de browsing. Une seule passe groupée par Discovery est la norme ; une seconde passe exige une lacune précise issue des premiers tests.

CoinGecko peut aider à identifier le régime actuel à utiliser comme contexte/stratification future, mais ne doit jamais transformer une observation du jour en règle optimisée rétrospectivement.

## Politique quota Plus

**Un seul agent LLM principal. Aucun sous-agent, spawn, fan-out ou reviewer-agent.**

- GPT-5.6 Sol High/Élevé, Standard, Fast OFF.
- XHigh seulement pour une réflexion scientifique/architecturale exceptionnelle.
- Parallélisme local non-LLM libre.
- Sorties modèle courtes ; état et preuves machine-readable sur disque.
- Pas de relecture systématique des 775, de tout Git ou de tous les rapports.
- Cache/déduplication des signatures.
- Pas de gros run identique sans changement scientifique ou raison de reproductibilité.
- Si 1 000 calculs peuvent être pré-définis, les lancer localement avant le prochain tour modèle.

## Done

DONE uniquement lorsque `python tools/run_daily_economic_certification.py .` certifie les trois familles séparément sur le même SHA avec le contrat machine courant : au minimum la preuve quotidienne canonique (actuellement >=2 jours UTC complets à >=+4 USD NET/jour), la preuve OOS/forward requise, le forward strict post-freeze vérifié et les coûts/liquidabilité/identités/placebos/causalité exigés, puis les gates techniques finales vertes.

Si seul du temps ou de nouvelles données manque, laisser les collecteurs locaux nécessaires tourner et cesser les tours modèle inutiles.
