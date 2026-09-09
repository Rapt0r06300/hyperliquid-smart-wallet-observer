# Codex Goal Runbook — Alina SmartFlow

Ce runbook complète `AGENTS.md`. Il décrit **comment chercher** l'edge sans dicter à Codex une stratégie fixe. Codex doit découvrir lui-même les meilleures hypothèses, expériences, backtests et tests statistiques adaptés aux données observées.

## Résultat final

Sur un même état certifié de `main`, obtenir séparément et sans compensation :

- `copy_vault >= +4.00 USD NET PROUVÉS` ;
- `lead_lag >= +4.00 USD NET PROUVÉS` ;
- `cross_venue_dislocation_v2 >= +4.00 USD NET PROUVÉS`.

La gate économique canonique reste la définition exécutable de la réussite. Ne jamais redéfinir le succès, masquer un coût ou affaiblir une gate pour obtenir un PASS.

## Principe directeur : local-first, information-first

Le quota modèle doit servir principalement à **choisir les expériences qui valent la peine**. Le calcul doit être déporté vers le PC autant que possible.

Avant toute recherche externe : inspecter le HEAD, les preuves récentes utiles, les données et scripts locaux concernés. Utiliser Python, pytest, replays, backtests, scripts de recherche, caches et artefacts locaux pour tester les hypothèses. Ne demander au modèle ni de lire ni de recopier d'énormes logs si un script peut les agréger en quelques métriques/JSON.

Travailler sur **une famille et un goulot principal à la fois**. Choisir l'expérience ayant le meilleur gain d'information attendu, pas celle qui produit le plus de runs.

Boucle normale :

`preuve actuelle -> diagnostic -> hypothèse causale -> test train ciblé -> sensibilité/stabilité -> freeze -> OOS/walk-forward -> forward post-freeze -> stress/placebos -> certification ou rejet`.

Codex choisit lui-même les tests et peut en inventer/implémenter de nouveaux s'ils sont justifiés. La batterie ci-dessous est un **menu**, jamais une checklist aveugle.

## Liberté de stratégie

Codex peut modifier ou remplacer : seuils, fenêtres, filtres, features, scoring, univers, sizing paper, logique d'entrée/sortie, maker/taker paper, collecte, algorithmes, architecture et variantes de modules. Il peut tuer une piste, créer une vNext ou revenir à une solution plus simple si les mesures l'exigent.

Cette liberté ne s'étend pas aux garanties de preuve/sécurité : paper-only, coûts réalistes, liquidabilité, causalité/no-lookahead, provenance, positions closes, déduplication, OOS, forward post-freeze et contrôles requis restent non négociables.

Un paramètre peut être retuné après un échec. Mais si une donnée OOS/validation/forward déjà vue influence ce retuning, elle devient exploratoire/train : nouveau freeze puis nouvelle preuve future/disjointe.

## Recherche quantitative et anti-overfit

Réutiliser les validateurs déjà présents avant de réinventer, notamment `src/hl_observer/backtesting/anti_overfit_gate.py` et `validation_methods.py`.

Selon le mécanisme, la quantité de données et la dépendance temporelle, Codex peut employer : walk-forward rolling/anchored ; splits temporels purgés et embargo ; CPCV/CSCV et PBO ; PSR/Deflated Sharpe ; White's Reality Check ; stationary/block bootstrap ; intervalles de confiance ; permutations/shuffles/placebos/nulls ; tests de sensibilité ; recherche de plateaux plutôt que pics de paramètres ; stabilité inter-régimes ; stress frais/spread/slippage/latence/profondeur/VWAP/capacité/fill ; sous-échantillonnage/Monte-Carlo ; audits timestamps/causalité/lookahead/provenance ; minimum de trades et longueur de track-record.

Le nombre **réel** d'essais fait partie de la preuve. Enregistrer les variantes testées, y compris les échecs, pour que les corrections de multiplicité restent honnêtes. Préférer une recherche coarse-to-fine, successive-halving/pruning ou une exploration guidée par information à un sweep exhaustif aveugle.

Une forte performance train seule ne vaut rien. Une performance sélectionnée après de nombreux essais sans correction de multiplicité ne vaut pas une certification.

## Recherche externe : seulement pour créer de nouvelles hypothèses testables

Quand les données/repo locaux ne suffisent plus à proposer une piste nouvelle :

- **Exa + Parallel Search** : recherches groupées et complémentaires sur microstructure Hyperliquid/perps, smart-money/copy trading, lead-lag, dislocations/arbitrage, coûts d'exécution, repos/bots comparables et retours de praticiens ;
- **Consensus** : littérature scientifique sur microstructure, causalité, validation, overfitting, multiple testing et méthodes quantitatives ;
- **GitHub** : état du repo/CI/artifacts et code open source précis lorsqu'il peut produire une hypothèse ou une implémentation mesurable ;
- **Superpowers** : systematic debugging, TDD et verification quand utiles. Ne jamais utiliser ses workflows qui exigent des sous-agents pour ce Goal.

Ne pas appeler tous les plugins « au cas où ». Définir d'abord la question exacte, lancer le minimum de recherches complémentaires, dédupliquer, extraire quelques hypothèses falsifiables, puis revenir immédiatement aux tests locaux.

## Politique quota Plus

Le Goal utilise **un seul agent principal**. Aucun spawn, sous-agent, fan-out ou reviewer-agent.

- GPT-5.6 Sol **High/Élevé** en continu ; Standard, pas Fast.
- XHigh/Très élevé est réservé à une phase de Plan explicitement ouverte pour un problème exceptionnellement difficile ; il n'est pas le défaut du Goal.
- Sorties courtes et machine-readable ; éviter les narrations de commandes.
- Tests unitaires/ciblés pendant l'itération ; suite globale/CI lourde aux checkpoints utiles.
- Grouper les lectures indépendantes et limiter les fichiers aux surfaces directement concernées.
- Ne pas relire l'historique Git, les 775 tâches ou tous les rapports à chaque reprise.
- Ne jamais relancer un gros run identique si code, données, paramètres et hypothèse n'ont pas changé.
- Réutiliser les datasets/caches/collecteurs existants et résumer localement les gros outputs avant lecture par le modèle.

Après deux expériences coûteuses consécutives sans information nouvelle, ne pas faire une troisième répétition : reformuler le mécanisme, changer de piste, auditer le pipeline ou rechercher une nouvelle hypothèse. Si seule l'arrivée de nouvelles données/du temps peut fournir la prochaine preuve, conserver un état de reprise précis et arrêter les runs inutiles.

## Done

DONE uniquement si les trois familles passent séparément la certification économique canonique avec coûts complets, liquidabilité, causalité, OOS, forward post-freeze, placebos/contrôles, provenance et positions closes, puis les gates techniques finales requises sont vertes sur le même SHA de `main`.

Un rapport, un backtest isolé, un train excellent, un résultat synthétique ou un ancien artifact ne suffit jamais.
