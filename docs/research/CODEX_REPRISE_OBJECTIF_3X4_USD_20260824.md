# Reprise HyperSmart - objectif economique 3 x +4 USD

Date de consolidation : 2026-08-24

Parent du bloc : `d9c9b654771f664b1b410c7240e4eb55e77cc6ba`

## Verdict honnete

L'objectif economique n'est pas atteint. Aucun des trois modules ne dispose encore
d'une preuve reproductible d'au moins `+4,00 USD NET` apres tous les couts, avec
parametres physiquement figes, OOS positif et forward posterieur au gel.

| Module | Verdict | Preuve actuelle | Decision |
|---|---|---|---|
| Copy-Vault | NON ATTEINT | base canonique negative, OOS negatif, forward absent | ne pas promouvoir |
| Lead-Lag | NON ATTEINT | continuation negative ; reversal globalement negatif et echantillons positifs trop petits | ne pas ouvrir l'OOS |
| Cross-Venue Dislocation | NON ATTEINT | grille taker atomique negative et couverture d'un seul jour distinct | ne pas promouvoir |

Les corrections de ce bloc rendent le PnL plus vrai, pas plus joli. Elles ne
modifient aucun seuil pour fabriquer une rentabilite.

## Travail termine dans ce bloc

### 1. Copy-Vault et metaorders : causalite des prix

- Le prix d'entree est maintenant le premier prix observable a ou apres la cible,
  jamais le dernier prix anterieur.
- La cible d'entree est le maximum entre l'heure du fill exchange et l'heure de
  reception locale disponible.
- Les delais d'entree et de sortie demandes sont transmis au chargeur de tape cible.
- Les points situes avant la cible ne sont plus conserves comme prix de substitution.
- Les tests couvrent les cibles entree/delai/sortie et les absences de prix causaux.

### 2. Collecte Copy-Vault bornee

- L'univers de vaults matures est etendu jusqu'a 100 candidats locaux valides.
- La collecte tourne par cohortes de 10 slots avec rotation persistante.
- La tape est ciblee sur les actifs utiles au lieu de charger inutilement tout le
  marche.
- Les appels bloquants ont ete sortis du chemin asynchrone critique.
- Les tests couvrent la rotation, les cohortes et la selection des vaults.

### 3. Lead-Lag : couverture Hyperliquid mesurable

- Le train charge maintenant les BBO Hyperliquid presents dans les memes shards que
  les trades Binance au lieu de dependre uniquement du L2 clairseme.
- Les timestamps, prix finis, tailles positives, carnets non croises et provenance
  sont verifies.
- Le timestamp local observable est utilise pour la causalite ; le timestamp
  exchange reste conserve comme preuve.
- Les carnets des shards alignes sont prioritaires ; le L2 sparse n'est qu'un
  fallback pour les coins sans carnet exploitable.
- Les sources heldout restent exclues du TRAIN.

### 4. Lead-Lag : direction et placebo

- La direction est explicite avec `direction_multiplier` strictement egal a `+1`
  ou `-1`.
- Deux mecanismes distincts sont declares : `SHOCK_CONTINUATION` et
  `EXTREME_SHOCK_REVERSAL`.
- Le placebo inverse n'utilise plus le spread original : il est reprice contre les
  memes bid/ask causaux dans la direction opposee exacte.
- Le placebo est diagnostic seulement : il ne peut ni selectionner une strategie,
  ni changer la politique, ni ouvrir l'OOS.

### 5. Famille TRAIN figee et correction multiplicite

- Continuation : seuils `8/12/20 bps`, horizons `1s/5s`, minimum 8 fills.
- Reversal extreme : seuils `20/30/50 bps`, horizons `1s/5s/15s`, minimum 30 fills.
- La famille declare 165 essais et applique la correction Bonferroni sur ce nombre
  total, y compris quand certaines combinaisons n'ont aucune observation.
- La fenetre de carnet fallback couvre maintenant jusqu'a 15 secondes.
- Le hash/score/freeze transporte mecanisme, politique, multiplicateur, minimum
  d'echantillon et taille totale de la famille.

## Mesures economiques consolidees

### Copy/metaorder

- 2 149 signaux et 215 metaorders observes.
- Base mesurable : `n=188`, moyenne `-2,69384574 bps`.
- Filtre microstructure existant : `n=125`, moyenne `-14,241408 bps`, soit une
  degradation de `-11,54756226 bps` face a la base.
- FIRST : `-7,524 bps` ; REVERSAL : `-20,791 bps` ; CONTINUATION : `-1,502 bps`.
- Tous les delais testes de 50 a 5 000 ms restent negatifs.
- Tape : 19 351 361 lignes ; 54 coins demandes ; 7 coins apparies ; couverture cible
  `44,1 %`.
- Ledger Copy canonique : 49 trades completement fermes, net `-9,84788766 USD`,
  brut `+2,63498484`, frais `6,61572389`, spread `2,68786032`, latence
  `3,17928828`.
- OOS Copy : `n=14`, net `-1,8541894 USD`. Forward absent et parametres de base non
  physiquement figes.

### Lead-Lag

Le replay TRAIN corrige a aligne 317 sources sur 738 candidates, soit
1 953 298 301 octets et 45 fenetres de ticks marche.

Les agregats ci-dessous sont des diagnostics et non des preuves de strategie : ils
additionnent des variantes seuil/horizon qui peuvent reutiliser des observations.

- Continuation : 54 variantes, 326 observations, 302 full fills, brut
  `-3,99 USD`, couts `9,60 USD`, net `-13,59 USD`.
- Reversal extreme : 81 variantes, 106 observations, 102 full fills, brut
  `+1,29 USD`, couts `3,19 USD`, net `-1,91 USD`.
- Quelques cellules INJ sont positives mais sous-puissantes : `n=3` a 20 bps sur
  1s/5s (net environ `+0,03 USD`) et `n=1` a 30 bps/15s (net environ
  `+0,01 USD`). Elles sont tres loin du minimum TRAIN de 30 et ne sont pas
  selectionnables.
- Verdict du pack : `NO_ROBUST_TRAIN_CANDIDATE`.
- Ledger Lead canonique : 27 trades liquidables sur 39 bruts, net
  `-1,20325679 USD`. OOS `n=5`, net `-0,18227435 USD`. Forward absent.

### Cross-Venue Dislocation

- Ledger canonique : 84 trades, net `-7,420291 USD`.
- OOS : `n=6`, net `-0,341215 USD`.
- Replay atomique certifie : 233 821 snapshots, 10 coins, toutes les variantes
  taker negatives.
- Meilleure cellule mesuree : 12 bps / 30s, `n=100`, net `-1,32337 USD`,
  profit factor `0,0678`, un seul jour distinct.
- Verdict du pack : `NO_ROBUST_TRAIN_CANDIDATE`.

## Loi economique observee

- Le lead-lag cross-venue taker apporte environ `0,2 a 1,5 bps` bruts pour
  `10 a 14 bps` de couts : l'edge net reste proche de `-10/-11 bps`.
- Aucun des 66 couples retardes testes ne montre une correlation OOS exploitable.
- La vitesse seule ne sauve pas le copy trading moyen mesure.
- Le signal de dislocation existe, mais il n'est pas assez grand pour payer les
  couts taker dans les donnees certifiees disponibles.

## Validation executee

Commande ciblee :

```powershell
.\portable_runtime\python\python.exe -m pytest -q tests\test_copy_edge_forward.py tests\test_metaorder_shadow.py tests\test_promotion_candidats.py tests\test_collecter_userfills_vaults.py tests\test_collecter_vaults.py tests\test_lead_lag_multiasset_train.py tests\test_lead_lag_measured_replay.py tests\test_lead_lag_l2_history.py tests\test_economic_vnext_pack.py tests\test_dataset_economic_vnext_wiring.py
```

Derniere execution avant commit : `131 passed in 6.59s`.

Un avertissement Windows `WinError 5` apparait seulement pendant le nettoyage du
symlink temporaire mort `pytest-current`, apres le succes des tests.

Pack TRAIN local, sans OOS :

```powershell
.\portable_runtime\python\python.exe -c "from hl_observer.backtesting.economic_vnext_pack import run_economic_vnext_pack; import json; print(json.dumps(run_economic_vnext_pack('.', lead_sources=[]), ensure_ascii=False))"
```

Audits :

```powershell
.\portable_runtime\python\python.exe -m hyper_smart_observer.app.main --safety-check
.\portable_runtime\python\python.exe -m hyper_smart_observer.app.main --audit-safety
```

Resultats : `Safety check: OK` et audit profond sans finding actif.

## Ce qui reste a faire, dans l'ordre

### Copy-Vault

1. Rafraichir en lecture seule l'univers borne de vaults matures.
2. Collecter assez de fills et de prix causaux pour obtenir une couverture utile sur
   plusieurs jours distincts.
3. Construire une base Copy physiquement figee avant toute evaluation heldout.
4. Exiger un TRAIN net positif apres frais, spread, slippage, latence et capacite.
5. Si aucun candidat TRAIN ne survit, tuer l'hypothese Copy actuelle au lieu de
   relacher les seuils.
6. Seulement apres freeze : ouvrir une fois l'OOS, puis exiger un forward posterieur
   au freeze avant toute certification.

### Lead-Lag

1. Ne plus optimiser la continuation : le mecanisme mesure est economiquement tue.
2. Accumuler, sans modifier la famille declaree, au moins 30 evenements TRAIN de
   reversal extreme INJ repartis sur plusieurs jours distincts.
3. Recalculer les statistiques avec correction de multiplicite et placebo inverse
   exact.
4. Ne figer un candidat que s'il est robuste, net de tous les couts, capacitaire et
   distinct du placebo.
5. Une alternative maker/queue n'est recevable qu'avec un modele de queue et de fills
   mesurable ; aucune hypothese de fill gratuit.
6. Ouvrir l'OOS une seule fois apres freeze, puis mesurer le forward posterieur.

### Cross-Venue

1. Arreter le tuning de seuils taker sur la meme famille negative.
2. Tester une famille physiquement differente : maker/convergence avec queue
   mesurable, ou carry/basis reellement deux jambes et hedge.
3. Utiliser uniquement des snapshots atomiques certifies sur au moins deux jours
   distincts, avec echantillon suffisant.
4. Inclure les couts des deux jambes, risque de non-fill, hedge delay, capacite et
   residual exposure.
5. Figer physiquement la famille avant OOS et forward.

### Regles communes de certification

Chaque module doit, separement :

- produire au moins `+4,00 USD NET` dans un ledger ferme et reconciliable ;
- inclure frais, spread, slippage, latence, funding et capacite applicables ;
- avoir zero position residuelle et zero PnL cache ;
- battre son placebo causal ;
- avoir des parametres physiquement figes et hashes avant OOS ;
- avoir un OOS positif puis un forward posterieur au freeze positif ;
- ne jamais agreger plusieurs familles ou variantes comme si elles formaient un seul
  resultat independant ;
- rester strictement PAPER/READ-ONLY.

## Commandes de reprise

Le wrapper dataset normal doit echouer si aucun workspace FULL/COLD materialise ne
possede une provenance valide. Ne jamais fabriquer de manifeste pour le contourner.

Pour reproduire le TRAIN local sans ouvrir l'OOS, utiliser le pack direct indique
plus haut. Pour une campagne officielle, materialiser d'abord un workspace dataset
valide, puis utiliser le wrapper de campagne existant.

## Etat de securite

- Aucun ordre reel.
- Aucun argent reel.
- Aucune cle privee.
- Aucune signature.
- Aucun endpoint `/exchange` operationnel.
- Aucun OOS ouvert par ce bloc.
- Aucun candidat promu par ce bloc.

Ce document est la reprise exacte. Il ne certifie pas les trois objectifs `+4 USD`.
