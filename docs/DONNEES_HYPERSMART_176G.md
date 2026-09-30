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

Le but n'est pas de réduire cette archive au seul lot `economic-core`. Les ~180 Go constituent une **bibliothèque historique du projet principal** pour replays, backtests, recherche de régimes, microstructure, SQLite, comparaisons et validation de stratégies.

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
| `research-lab-full` | gros historiques JSONL, scénarios, replays et backtests |
| `sqlite-core` | uniquement les deux grosses bases SQLite canoniques |
| `sqlite-all-safe` | toutes les `.sqlite3` non marquées corrompues/quarantaine et hors `.git` |
| `full-archive` | totalité de la Release FULL/COLD |

Le lanceur commence toujours par afficher le plan. Aucun gros téléchargement ne démarre avant une confirmation `OUI`. La suite `full-archive` demande en plus la confirmation explicite `TOUT`.

## Pourquoi SQLite a ses propres suites

L'archive contient environ **58,44 Gio de fichiers `.sqlite3`**. Les deux bases canoniques connues sont :

```text
runtime/data/hypersmart_simulation_session.sqlite3
data/hl_observer.sqlite3
```

Une ancienne copie porte explicitement un nom de corruption :

```text
runtime/data/hypersmart_simulation_session.sqlite3.corrupted-20260708
```

Elle ne doit jamais être prise automatiquement comme source primaire.

`sqlite-core` ne sélectionne donc que les deux chemins canoniques exacts. `sqlite-all-safe` sélectionne plus largement les `.sqlite3`, mais refuse les chemins contenant des marqueurs tels que `corrupt`, `broken`, `damaged`, `quarantine` ou `invalid`, ainsi que les objets internes `.git`.

Même dans `full-archive`, où le fichier peut être présent pour conserver la sauvegarde complète, le profiler SQLite le classe en quarantaine et refuse son ouverture automatique.

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

Elle regroupe toutes les sources repérées pour les trois familles économiques actives et les reconstruit dans un workspace séparé.

Le raccord FULL/COLD consomme désormais explicitement les sources compatibles :

- Lead-Lag utilise l'ensemble des bandes BBO manifestées ;
- Copy-Vault construit une vue multi-source dédupliquée ;
- Cross-Venue fusionne les carnets compatibles et refuse les conflits de même timestamp.

Le rapport `SOURCE_CONSUMPTION_COVERAGE.*` mesure ce qui a réellement été fourni à chaque moteur.

Le moteur de campagne existant reste utilisé : aucun second moteur économique parallèle n'est inventé.

## Troisième niveau : bases SQLite historiques

Après reconstruction d'une suite SQLite :

```powershell
python -m hl_observer.ops.dataset_sqlite_inventory --root "<workspace>"
```

Le profiler :

- ouvre en SQLite `mode=ro` ;
- active `PRAGMA query_only=ON` ;
- décrit tables, colonnes, indexes et métadonnées ;
- inventorie WAL/SHM séparément ;
- ne copie aucune valeur de ligne dans le rapport ;
- ferme chaque connexion ;
- refuse automatiquement les noms signalant une ancienne base corrompue.

Sorties :

```text
runtime/reports/datasets/SQLITE_INVENTORY.json
runtime/reports/datasets/SQLITE_INVENTORY.md
```

Le catalogue de recherche :

```powershell
python -m hl_observer.ops.dataset_sqlite_research --root "<workspace>"
```

expose uniquement une allowlist de tables/colonnes économiques. Les colonnes brutes `raw_json`/payload ne sont pas transmises par cette couche.

Une vue locale dérivée peut ensuite être produite, par exemple :

```powershell
python -m hl_observer.ops.dataset_sqlite_research `
  --root "<workspace>" `
  --export-table fills
```

Cela permet à des outils de replay de travailler en streaming sur une forme simple sans modifier la DB source.

## Quatrième niveau : Research Lab massif

`research-lab-full` contient des historiques très volumineux. Ils ne sont pas lus avec `read_text()` ou chargés en mémoire.

Le scanner :

```powershell
python -m hl_observer.ops.dataset_research_inventory `
  --root "<workspace>" `
  --heartbeat-seconds 5
```

lit séquentiellement les JSONL, agrège des métadonnées et métriques, écrit des checkpoints et reprend les gros fichiers non compressés à leur dernier offset après interruption.

Le rapport garde notamment :

- lignes valides/invalides ;
- bornes temporelles ;
- familles ;
- événements ;
- coins ;
- métriques numériques repérées : PnL, coûts, drawdown, ROI, edge, profit factor, etc. ;
- progression du scan.

Il n'exporte pas les lignes brutes complètes.

Sorties :

```text
runtime/reports/datasets/RESEARCH_LAB_STREAM_PROFILE.json
runtime/reports/datasets/RESEARCH_LAB_STREAM_PROFILE.md
```

## Laboratoire historique commun

Pour une suite autre que `economic-core/economic-full`, le bouton principal utilise :

```powershell
python -m hl_observer.ops.dataset_research_runner `
  --root . `
  --data-root "<workspace>" `
  --suite "<suite>" `
  --full
```

Le runner commence désormais par :

```text
inventaire SQLite read-only
-> catalogue SQLite de recherche
-> sonde Research Lab reprenable
-> replays/qualité/market truth/PnL/A-B
-> walk-forward/anti-overfit
-> scan complet Research Lab en mode --full lorsque présent
```

Les étapes incompatibles avec une suite sont `SKIPPED`, avec leur raison exacte, jamais remplacées par une donnée artificielle.

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

Le manifeste de sources d'un workspace est :

```text
<workspace>/runtime/reports/datasets/FAMILY_SOURCES.json
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

Le rapport historique final incorpore aussi, lorsqu'ils existent, les résumés SQLite et Research Lab afin de garder une trace de ce qui a réellement été inspecté.

Les rapports économiques exportés incluent la suite utilisée. Les sorties canoniques légères sont :

```text
docs/research/datasets/DERNIER_REPLAY_DATASETS.md
docs/research/datasets/DERNIER_REPLAY_DATASETS.json
```

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
- bases SQLite ouvertes read-only par la couche dataset ;
- noms de bases corrompues quarantainés ;
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

Les ~180 Go sont donc la **bibliothèque de recherche historique d'Alina SmartFlow**, tandis que les nouvelles collectes postérieures au snapshot restent essentielles pour confirmer ou invalider les découvertes en forward.
