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

Le double-clic lance la suite `full`, locale et bornee, qui reutilise les
moteurs d'analyse existants :

1. fusion des shards de replay ;
2. laboratoire PnL sur les ledgers canoniques actifs et archives ;
3. controle qualite du replay ;
4. comparaison A/B exacte a notionnel constant de 50 USDT par trade ;
5. replay temps reel ;
6. replay du ledger ferme ;
7. tournoi de strategies ;
8. audit PnL ;
9. attribution des pertes ;
10. rapport de latence ;
11. diagnostic de fraicheur ;
12. walk-forward et controles anti-overfit en mode `full`.

Modes :

```bat
ANALYSER_BACKTESTS_REPLAYS.cmd
ANALYSER_BACKTESTS_REPLAYS.cmd quick
ANALYSER_BACKTESTS_REPLAYS.cmd full
ANALYSER_BACKTESTS_REPLAYS.cmd deep
ANALYSER_BACKTESTS_REPLAYS.cmd maximum
```

- double-clic / `full` : mode recommande, avec validation temporelle ;
- `quick` : controle regulier plus court ;
- `deep` : ajoute la recherche exhaustive reprenable, volontairement explicite.
- `maximum` : alias lisible de `deep`.

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
