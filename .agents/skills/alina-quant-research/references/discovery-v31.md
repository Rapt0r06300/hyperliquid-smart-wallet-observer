# Discovery V3.1 — predictive alpha playbook

Lire cette référence **uniquement** à l'entrée d'un cycle Discovery, d'un mini-tournoi champion-challenger ou lorsqu'une lignée doit pivoter. Ne pas la recharger à chaque backtest.

## But

Éviter l'exploitation locale interminable d'une même idée. Le modèle sert à inventer et choisir des mécanismes ; le PC exécute toute la partie numérique reproductible. Le résultat final reste économique : >= +4 USD NET/jour prouvés séparément par famille, jamais un simple score prédictif.

## 1. Diversité du pool

Contrat canonique/CI : `12 candidates`, `5 archetypes`.

Par défaut proposer **12 candidats** ; le minimum dur reste 8. Un pool sain couvre au moins **5 archétypes de mécanisme** et plusieurs combinaisons de surfaces/opérateurs temporels. Des variantes de seuil, fenêtre, seed, horizon ou hyperparamètre d'une même mécanique ne sont pas des candidats distincts.

Archétypes possibles, non exhaustifs :

- identité/informativeness/toxicité/anticipation des wallets ;
- price discovery asynchrone CEX -> Hyperliquid et venue -> venue ;
- L2/order-flow/event-time, queue, absorption, depletion, sweep, microprice ;
- spillovers cross-asset / leader-follower ;
- liquidations, OI, basis, funding et leurs interactions ;
- régimes, ruptures/changepoints, volatilité/liquidité conditionnelles ;
- micro-saisonnalités et clocks d'événements ;
- exécution/queue/fill/adverse-selection comme mécanisme d'edge ;
- interactions non linéaires entre signaux faibles ;
- combinaisons de mécanismes déjà faibles mais complémentaires.

Ne jamais rebaptiser une baseline existante pour la faire compter comme nouveauté. Utiliser le ledger comme mémoire négative : une lignée rejetée ou deux fois sans headroom devient un **motif à éviter**, sauf nouvelle donnée, nouvelle surface, nouveau mécanisme causal ou contradiction empirique explicite.

## 2. Novelty injection / champion-challenger

Même si une lignée progresse, après **3 décisions IMPROVE consécutives** sans passage à FREEZE, lancer un mini-Discovery de >=4 challengers orthogonaux avant une quatrième amélioration locale. L'incumbent n'est pas tué : il continue seulement s'il bat les challengers sur information utile et économie OOS.

Un PIVOT forcé reste requis par `needs-rediscovery` après stagnation. Le champion-challenger est différent : il prévient la fixation avant la stagnation complète.

## 3. Ce qu'il faut prédire

Ne pas viser uniquement `price_up/down`. Préférer des cibles directement actionnables et calibrées :

- distribution ou quantiles du markout futur ;
- probabilité qu'un move dépasse **tous les coûts** avant un horizon donné ;
- amplitude conditionnelle attendue du move ;
- temps/hazard jusqu'à un move exploitable ou une convergence ;
- expected NET edge conditionnel après fees/spread/slippage/latence/fill ;
- probabilité de fill et adverse selection pour les variantes maker.

Mesurer calibration/Brier/log-loss/quantile loss/MAE/IC si utile, mais aucun de ces scores ne remplace le PnL exécutable OOS.

## 4. Échelle de modèles CPU

Commencer par la méthode la plus simple capable de falsifier l'hypothèse, puis **escalader la complexité seulement si elle apporte une valeur OOS incrémentale**.

1. Event studies, conditional means/quantiles, permutation, cross-correlation et baselines naïves.
2. Régressions linéaires/logistiques/ridge/robustes, modèles de probabilité ou quantiles.
3. Méthodes temporelles/microstructure adaptées aux données : Hayashi-Yoshida/asynchronous lead-lag, Granger/VAR/VECM, state-space/Kalman, survival/hazard, Hawkes, transfer-entropy ou équivalents lorsque leurs hypothèses sont satisfaites.
4. Modèles non linéaires CPU : arbres/extra-trees/gradient boosting ou autres modèles tabulaires disponibles, avec calibration et ablations.
5. Mélanges de régimes, ensembles ou stacking seulement si les composants simples ont une valeur complémentaire démontrée.

Une architecture plus complexe perd contre une baseline simple si son gain disparaît après coûts, perturbation des paramètres, changement de régime ou vraie séparation temporelle.

## 5. Recherche locale massive

Le CPU n'est pas le quota (`the CPU is not quota`). Une fois les décisions nécessaires prises, pré-déclarer le maximum de calculs indépendants dans un script ou `tools/codex_quant_batch.py` et **ne pas retourner au modèle entre les trials**.

Utiliser selon pertinence : QMC, TPE/Optuna, CMA-ES, NSGA-II, Successive-Halving, Hyperband, recherche coarse-to-fine, multi-seed, bootstrap, permutations/placebos, Monte-Carlo, walk-forward, purge/embargo, CPCV/CSCV, PBO, DSR/PSR, Reality Check, ablations, leave-one-regime/coin/wallet-out et stress d'exécution.

Le calcul massif n'autorise jamais le p-hacking. Tous les essais distincts comptent. Les résultats d'un search adaptatif restent feedback/train ; le test final reste disjoint.

## 6. Budget d'information

Pour chaque candidat, demander :

- Quelle observation le tuerait vite ?
- Quelle quantité locale peut être calculée sans nouveau tour modèle ?
- Quel est le headroom NET maximal plausible avant un gros sweep ?
- Quelle baseline simple doit-il battre ?
- Quelle donnée manque réellement ?

Préférer une expérience qui élimine 6 hypothèses en 20 minutes CPU à une expérience qui optimise 500 paramètres d'une hypothèse mal fondée.

## 7. Recherche externe

Au premier Discovery d'une famille et après plusieurs lignées épuisées, une passe groupée Exa + Parallel Search + littérature/GitHub peut être proactive. Rechercher surtout **des mécanismes absents du ledger**, pas une confirmation de l'idée courante. CoinGecko est seulement un snapshot de régime ; il ne sert jamais de preuve ni de cible de tuning.

Chaque trouvaille externe doit finir sous forme d'une hypothèse locale falsifiable avec surface de données, causalité temporelle, traduction paper et test de rejet.

## 8. Décision

Après chaque tournoi ou campagne :

- `IMPROVE` seulement si un mécanisme montre un progrès économique comparable et une raison causale de continuer ;
- `COMBINE` si deux mécanismes montrent une complémentarité OOS mesurable ;
- `PIVOT` lorsque la lignée stagne, duplique l'historique ou manque de headroom ;
- `STOP` pour une lignée épuisée, jamais pour la mission globale.

La bonne question n'est pas « comment rendre ce backtest plus joli ? », mais « quelle prochaine expérience a la plus grande probabilité de changer notre croyance sur l'existence d'un edge net réellement exploitable ? »
