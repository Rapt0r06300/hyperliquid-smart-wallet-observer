# Lanceurs HyperSmart

HyperSmart separe volontairement le runtime du bot et les analyses historiques.
Cette separation evite que les backtests, replays et recherches A/B ralentissent
la collecte live ou le dashboard.

## 1. Runtime principal

Fichier :

```text
LANCER_HYPERSMART.cmd
```

Le double-clic demarre uniquement le profil `CORE` :

- environnement Python portable du projet ;
- initialisation locale et migrations necessaires ;
- serveur UI local ;
- poller persistant Hyperliquid read-only ;
- flux leaders read-only ;
- collecteur `allMids` ;
- collecteur BBO ;
- surveillance des ressources.

Le poller persistant assure deja la decouverte, la rotation des wallets, la
collecte `/info`, les reconciliations et les decisions paper. Le lanceur ne
repete donc plus ces travaux dans une seconde boucle de demarrage.

Le superviseur est idempotent : un collecteur CORE deja vivant est reutilise,
pas relance en double. L'IA auxiliaire est desactivee au demarrage ; elle reste
disponible comme outil manuel, mais ne consomme pas de ressources dans le hot
path.

Commandes utiles :

```bat
LANCER_HYPERSMART.cmd status
LANCER_HYPERSMART.cmd stop
LANCER_HYPERSMART.cmd restart
LANCER_HYPERSMART.cmd collectors
```

## 2. Profils optionnels

Les collecteurs non essentiels n'ont pas ete supprimes. Ils sont ranges dans
des profils explicites :

```bat
LANCER_HYPERSMART.cmd collectors-maintenance
LANCER_HYPERSMART.cmd collectors-research
LANCER_HYPERSMART.cmd collectors-all
```

- `maintenance` : whitelist copy et rapport periodique ;
- `research` : collecte et laboratoires historiques specialises ;
- `all` : tous les collecteurs, uniquement pour un diagnostic exceptionnel.

Ces commandes ne sont jamais appelees par le double-clic normal.

## 3. Backtests, replays et comparaisons A/B

Fichier :

```text
ANALYSER_BACKTESTS_REPLAYS.cmd
```

Le double-clic lance le laboratoire canonique `full`, local et borne a la
derniere session `COMPLETE` dont les checksums sont valides. Il reutilise les
moteurs d'analyse existants pour :

1. verifier et isoler la session choisie ;
2. apparier le ledger paper et les preuves `OPEN/CLOSE` ;
3. recalculer PnL, frais et attribution des pertes ;
4. comparer les regles A/B a notionnel constant ;
5. separer train, validation et holdout ;
6. produire le rapport de pistes sans activer automatiquement un flag.

Le profil `deep`/`maximum` enchaine ensuite la suite historique large : fusion
des shards, qualite, replays, audit PnL, latence, fraicheur, walk-forward,
anti-overfit et recherche reprenable. Cette seconde passe est explicite car
elle est plus longue et travaille sur l'inventaire historique global.

Modes :

```bat
ANALYSER_BACKTESTS_REPLAYS.cmd
ANALYSER_BACKTESTS_REPLAYS.cmd quick
ANALYSER_BACKTESTS_REPLAYS.cmd full
ANALYSER_BACKTESTS_REPLAYS.cmd deep
ANALYSER_BACKTESTS_REPLAYS.cmd maximum
```

- double-clic / `full` : grille complete sur la derniere session valide ;
- `quick` : meme chemin canonique avec budget de huit combinaisons par defaut ;
- `deep` : ajoute la recherche exhaustive reprenable, volontairement explicite.
- `maximum` : alias lisible de `deep`.
- `portable-smoke` ou `portable-check` : preuve bornee, hors reseau et sans
  modification de la session, destinee au controle apres copier-coller.

Le laboratoire PnL :

- apparie les `OPEN` et `CLOSE` de chaque session paper canonique ;
- exclut les sorties historiques sans preuve exploitable ;
- reconcilie le PnL brut avec prix d'entree, prix de sortie et notionnel ;
- conserve le vrai PnL paper pour l'audit ;
- compare les regles a notionnel constant pour ne pas favoriser artificiellement
  un gros portefeuille ;
- reutilise le replay A/B exact uniquement si l'empreinte des donnees, du code et
  des parametres est strictement identique ; toute modification invalide le cache ;
- separe chronologiquement train, validation et holdout ;
- n'utilise jamais le holdout pour choisir une regle ;
- attribue pertes et frais par sortie, sens, strategie et coin ;
- propose des experiences A/B precises, sans activer de flag automatiquement.
- produit un backlog priorise avec grilles SL/TP, horizons, edge net apres couts,
  preuves requises et seuils de promotion hors echantillon.

La suite tourne en priorite Windows inferieure a la normale et limite les
threads numeriques. Elle ne fait aucun appel d'execution et ne modifie pas le
runtime du bot.

## 4. Rapports

Chaque execution ecrit un dossier horodate sous :

```text
runtime/reports/backtest_replay/run_YYYYMMDD_HHMMSS/
```

Le dernier rapport est toujours disponible ici :

```text
runtime/reports/backtest_replay/RAPPORT_LATEST.md
runtime/reports/backtest_replay/report_latest.json
```

Le detail du laboratoire est ecrit dans chaque dossier d'execution :

```text
runtime/reports/backtest_replay/run_YYYYMMDD_HHMMSS/PNL_IMPROVEMENT_LAB.md
runtime/reports/backtest_replay/run_YYYYMMDD_HHMMSS/pnl_improvement_lab.json
```

Chaque etape possede son propre journal. Une entree manquante est indiquee
comme `SKIPPED` avec sa raison ; elle n'est jamais remplacee par une donnee
inventee. Ctrl+C conserve les resultats deja obtenus et finalise le rapport.

## 5. Regles d'exploitation

- Demarrer le bot avec `LANCER_HYPERSMART.cmd`.
- Lancer les analyses avec `ANALYSER_BACKTESTS_REPLAYS.cmd`.
- Eviter `collectors-all` pendant une session normale.
- Ne jamais utiliser un resultat historique comme promesse de profit futur.
- Les deux lanceurs restent local-only, read-only cote marche et paper-only
  cote portefeuille.
