# Relier les ~180 Go FULL/COLD à Alina SmartFlow

## Source de vérité

Les grosses données restent hors de l'historique Git du logiciel. Elles sont conservées dans la Release privée du dépôt `Rapt0r06300/hypersmart-datasets`.

Release utilisée par défaut :

- dépôt : `Rapt0r06300/hypersmart-datasets`
- release id : `371149058`
- nom : `HyperSmart FULL/COLD data snapshot v2`
- **150 546 fichiers**
- **176,0341 Gio bruts**, soit environ **189 Go décimaux**
- assets GitHub avec empreintes SHA-256
- reconstruction refusée si taille ou SHA-256 ne correspondent pas

Le but n'est pas de réduire cette archive au seul lot `economic-core`. Les ~180 Go constituent désormais une **bibliothèque historique du projet principal** pour replays, backtests, recherche de régimes, microstructure, comparaisons et validation de stratégies.

## Nouveau lanceur principal de la bibliothèque

Double-cliquer sur :

```text
LANCER_LABO_180GO.cmd
```

Il permet de travailler avec les suites suivantes :

| Suite | Rôle |
|---|---|
| `economic-core` | contrôle rapide du pipeline sur les sources canoniques des trois moteurs |
| `economic-full` | union large des données Copy-Vault + Lead-Lag + Cross-Venue |
| `copy-vault-full` | toutes les données repérées autour des vaults/leaders/user fills/metaorders/TWAP |
| `lead-lag-full` | BBO/allMids/microprice/order-flow/OFI |
| `cross-venue-full` | données de venues/dislocations/Hyperliquid/Binance/dYdX |
| `microstructure-full` | L2, profondeur, carnet, bid/ask |
| `research-lab-full` | research_lab, scénarios, replays, backtests, historiques |
| `full-archive` | totalité de la Release FULL/COLD |

Le lanceur commence toujours par afficher le plan. Aucun gros téléchargement ne démarre avant une confirmation `OUI`. La suite `full-archive` demande en plus la confirmation explicite `TOUT`.

## Carte de toute la bibliothèque

Commande :

```bat
LANCER_LABO_180GO.cmd plans
```

ou directement :

```bat
python -m hl_observer.ops.dataset_bridge plan-all --root .
```

Sorties :

```text
runtime/reports/datasets/BIBLIOTHEQUE_180GO.md
runtime/reports/datasets/BIBLIOTHEQUE_180GO.json
```

Le plan calcule en une lecture du manifeste :

- nombre de fichiers par suite ;
- volume brut des fichiers ciblés ;
- assets GitHub nécessaires ;
- volume total des assets ;
- assets déjà présents dans le cache local ;
- volume restant à récupérer ;
- assets manquants ;
- digest reproductible de la sélection ;
- workspace qui sera utilisé ;
- usage prévu de la suite.

Les chiffres de cache affichés dans le plan sont un pré-contrôle par taille. Le SHA-256 complet reste vérifié avant usage réel.

## Cache commun, workspaces isolés

Les assets GitHub lourds sont partagés ici :

```text
data/hypersmart_datasets/assets/
```

Un asset déjà téléchargé et valide n'a pas besoin d'être téléchargé une seconde fois lorsqu'il sert à plusieurs suites.

En revanche, les fichiers reconstruits ne sont plus tous mélangés dans un seul dossier. Chaque suite reproductible utilise un workspace isolé :

```text
data/hypersmart_datasets/workspaces/<suite>/<digest>/
```

Exemple :

```text
data/hypersmart_datasets/workspaces/economic-full/0123456789abcdef/
```

Le digest dépend de la liste des fichiers, de leur taille, de leur SHA-256 et de leur mode de stockage. Deux sélections différentes ne partagent donc pas silencieusement le même workspace.

Le pointeur courant est conservé dans :

```text
data/hypersmart_datasets/workspaces/<suite>/CURRENT.json
```

Pour retrouver le workspace actif :

```bat
python -m hl_observer.ops.dataset_bridge locate --root . --suite economic-full
```

## Premier niveau : contrôle du pipeline

`economic-core` reste utile, mais uniquement comme **smoke test**. Il vérifie rapidement :

```text
Release -> manifestes -> plan -> cache -> SHA-256 -> reconstruction
-> Copy-Vault -> Lead-Lag -> Cross-Venue -> petit rapport GitHub
```

Il ne représente pas l'ensemble des données historiques.

## Deuxième niveau : données économiques larges

La suite prioritaire après validation du smoke test est :

```text
economic-full
```

Elle regroupe toutes les sources repérées pour les trois familles économiques actives et les reconstruit dans un workspace séparé. Le lanceur peut ensuite appeler :

```text
ANALYSER_DONNEES_HYPERSMART.cmd economic-full
```

Le moteur de campagne existant reste utilisé : aucun second moteur économique parallèle n'est inventé.

## Troisième niveau : recherche ciblée

Les suites `copy-vault-full`, `lead-lag-full` et `cross-venue-full` servent à préparer des corpus de famille plus larges.

Les suites `microstructure-full` et `research-lab-full` servent à exploiter les données qui ne rentrent pas directement dans le replay économique canonique :

- profondeur et L2 ;
- bid/ask et carnets ;
- historiques de recherche ;
- scénarios ;
- anciennes sorties de replay/backtest ;
- archives de laboratoire.

Ces corpus doivent alimenter les outils de recherche existants et les futurs adapters dédiés. Ils ne doivent jamais être assimilés automatiquement à une preuve de PnL.

## Archive complète

La suite :

```text
full-archive
```

représente les **150 546 fichiers / 176,0341 Gio**.

Elle existe pour que le projet principal puisse adresser la totalité de la sauvegarde avec la même logique de manifestes, cache, SHA-256, provenance et workspace.

Cela ne veut pas dire qu'il faut systématiquement télécharger ~180 Go. Le bon ordre est :

1. planifier ;
2. réutiliser le cache ;
3. préparer la suite nécessaire à une expérience ;
4. exécuter le replay/backtest adapté ;
5. conserver seulement les petits résultats versionnables ;
6. passer à la suite suivante.

## Provenance des expériences

Chaque préparation écrit notamment :

```text
runtime/reports/datasets/DERNIERE_PREPARATION_<suite>.json
<workspace>/runtime/reports/datasets/SELECTION_PROVENANCE.json
```

La provenance contient :

- Release source ;
- suite ;
- digest de sélection ;
- nombre de fichiers ;
- volume brut ;
- assets utilisés ;
- workspace ;
- état paper/read-only.

Les rapports économiques exportés incluent aussi la suite utilisée. Les sorties canoniques légères sont :

```text
docs/research/datasets/DERNIER_REPLAY_DATASETS.md
docs/research/datasets/DERNIER_REPLAY_DATASETS.json
```

Des copies par suite sont également écrites sous `DERNIER_REPLAY_180GO_<suite>.*`. Les anciens noms `DERNIER_REPLAY_176GO.*` restent écrits pour compatibilité.

## Anciennes commandes

`PREPARER_DONNEES_HYPERSMART.cmd` et `LANCER_REPLAY_176GO.cmd` restent disponibles pour compatibilité.

Les nouvelles expériences reproductibles doivent privilégier `LANCER_LABO_180GO.cmd` et `--suite`, car les anciens modes ad hoc reconstruisent encore dans :

```text
data/hypersmart_datasets/materialized/
```

## Sécurité et vérité des données

- aucune exécution réelle ;
- aucune signature ;
- aucune clé privée ;
- mainnet et testnet execution forcés à `0` dans les lanceurs ;
- aucun fichier accepté si le contrôle d'intégrité échoue ;
- aucune donnée manquante remplacée par une valeur inventée ;
- cache partagé, mais workspaces reconstruits isolés ;
- provenance obligatoire pour les suites ;
- résultats historiques distincts de la validation future.

## Méthode de recherche à appliquer aux ~180 Go

Les données servent à **chercher puis falsifier** des hypothèses, pas à fabriquer un résultat gagnant.

Pour toute stratégie candidate :

1. découverte sur une période d'entraînement ;
2. paramètres gelés ;
3. validation sur période distincte ;
4. OOS temporel ;
5. forward sur données plus récentes lorsque disponible ;
6. frais, spread, slippage, latence et capacité inclus ;
7. placebos/contrôles quand ils sont applicables ;
8. mesure du PnL net, ROI, drawdown, stabilité et nombre d'observations ;
9. rejet si le résultat dépend d'un sous-échantillon, d'un réglage fragile ou d'une donnée non causale ;
10. aucune promotion sur le seul fait qu'un backtest historique est positif.

Les ~180 Go sont donc désormais la **bibliothèque de recherche historique d'Alina SmartFlow**, tandis que les nouvelles collectes postérieures au snapshot restent essentielles pour confirmer ou invalider les découvertes en forward.
