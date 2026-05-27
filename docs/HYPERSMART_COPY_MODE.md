# HyperSmart Copy Mode

Le copy mode implemente le cahier des charges `HYPERSMART_MAGIC_BOT_RESEARCH_README.md`
en mode observation/paper uniquement.

Pipeline livre:

1. Leaderboard shortlist locale.
2. Copy loop dry-run toutes les 300 secondes par defaut.
3. Delta detector `OPEN_LONG`, `OPEN_SHORT`, `ADD`, `INCREASE`, `REDUCE`,
   `CLOSE_LONG`, `CLOSE_SHORT`, `UNKNOWN`.
4. `SignalCandidate` avec `edge_remaining_bps` obligatoire.
5. `no_trade_report` en francais.
6. Dashboard read-only.

Commandes:

```powershell
python -m hyper_smart_observer.app.main --write-shortlist-template data\reports\leaderboard_candidates_template.csv
python -m hyper_smart_observer.app.main --build-shortlist-file config\leaderboard_candidates.example.csv
python -m hyper_smart_observer.app.main copy-preflight --network-read
python -m hyper_smart_observer.app.main copy-run --interval 300 --dry-run
python -m hyper_smart_observer.app.main copy-run --interval 300 --dry-run --network-read
python -m hyper_smart_observer.app.main copy-report --period 7d
python -m hyper_smart_observer.app.main promote-testnet-candidates --dry-run
```

Garanties:

- aucun ordre;
- aucune signature;
- aucune cle privee;
- aucun mainnet;
- aucun executor testnet actif;
- paper mock USDC uniquement;
- pas de LLM dans le hot path.

## Preflight obligatoire avant collecte large

Commande:

```powershell
python -m hyper_smart_observer.app.main copy-preflight --network-read
```

Le preflight ne fait aucun appel reseau. Il verifie:

- presence de `data/leaderboard_shortlist.json`;
- nombre de leaders shortlistes;
- adresses completes seulement;
- absence d'archives sales a la racine;
- DB legacy dans `logs/` en warning;
- endpoints `/info` prevus;
- limite `HYPERSMART_COPY_MAX_LEADERS_PER_RUN=3`.

Si la shortlist contient plus de leaders, `copy-run` ne lit que les premiers
leaders bornes et journalise `RATE_LIMIT_GUARD`.

## Sizing paper proportionnel

La recherche publique sur les copy bots Hyperliquid montre deux patterns
recurrents: sizing par pourcentage fixe et sizing par ratio d'equity
leader/follower. HyperSmart implemente uniquement la version locale paper mock
USDC:

- notional leader = `abs(leader_position_size * reference_price)`;
- ratio copy = `paper_follower_equity / leader_account_value`;
- notional paper = `notional leader * ratio copy`;
- cap local = `HYPERSMART_PAPER_MAX_POSITION_NOTIONAL`;
- refus si le notional paper tombe sous le minimum local;
- refus si `leader_account_value` ou le notional leader manque;
- refus si l'asset est bloque.

La sortie reste un `PaperIntent` / `PaperTrade` local apres risk gates. Aucun
ordre reel, aucune signature, aucun `/exchange`.

## Degradation de copie

`edge_remaining_bps` penalise aussi le prix courant si le follower arrive apres
le leader a un prix moins favorable:

- `OPEN_LONG`: prix courant plus haut que le prix leader = penalite en bps;
- `OPEN_SHORT`: prix courant plus bas que le prix leader = penalite en bps;
- les cas ambigus restent traites par les autres gates et par `UNKNOWN`.

Cette degradation s'ajoute au retard, spread, slippage, frais, liquidite,
adverse selection, crowding et funding penalty.

## Fraicheur temps reel

Pour les wallets choisis, le suivi ne doit pas utiliser une position ancienne.
`LivePositionFreshnessGuard` verifie le dernier update position/fill/openOrder:

- update recent = observation paper/research possible;
- update trop vieux = `STALE_SIGNAL`;
- aucun update = `SOURCE_UNAVAILABLE`;
- aucun ordre n'est cree.

Le but est d'eviter une fausse simulation positive fondee sur une position
leader deja obsolète.
