# Utiliser les 176 Gio de données HyperSmart

## Ce qui existe maintenant

Les grosses données ne sont pas dans l'historique Git du logiciel. Elles sont dans la Release privée du dépôt `Rapt0r06300/hypersmart-datasets`.

Release utilisée par défaut :

- dépôt : `Rapt0r06300/hypersmart-datasets`
- release id : `371149058`
- nom : `HyperSmart FULL/COLD data snapshot v2`
- environ 176 Gio de données brutes
- chaque asset possède un SHA-256 vérifiable côté GitHub

Le logiciel principal ne doit jamais télécharger les 176 Gio sans raison. Le pont commence par les petits manifestes, cherche les chemins utiles, calcule quels gros assets sont nécessaires, puis télécharge seulement ces assets.

## Commande simple

Double-cliquer sur :

```text
PREPARER_DONNEES_HYPERSMART.cmd
```

Le menu permet de :

1. vérifier que la Release est accessible ;
2. récupérer seulement les manifestes ;
3. faire une carte complète des 150 000+ fichiers sans télécharger les gros assets ;
4. voir le plan Copy-Vault ;
5. voir le plan Lead-Lag ;
6. voir le plan Cross-Venue.

Voir un plan ne télécharge pas les gros fichiers.

## Commandes détaillées

Vérifier la Release :

```bat
PREPARER_DONNEES_HYPERSMART.cmd status
```

Télécharger et vérifier uniquement les manifestes :

```bat
PREPARER_DONNEES_HYPERSMART.cmd catalog
```

Construire la carte complète :

```bat
PREPARER_DONNEES_HYPERSMART.cmd carte
```

La carte écrit :

```text
runtime/reports/datasets/CATALOGUE_COMPLET.json
runtime/reports/datasets/CATALOGUE_COMPLET.md
```

Elle donne notamment les volumes par famille repérée, par extension, par gros dossier, la plage des dates de modification et les plus gros fichiers. Elle ne supprime rien et ne trie rien définitivement.

Voir combien de données Copy-Vault seraient nécessaires :

```bat
PREPARER_DONNEES_HYPERSMART.cmd copy-vault
```

Même principe pour Lead-Lag :

```bat
PREPARER_DONNEES_HYPERSMART.cmd lead-lag
```

Et Cross-Venue :

```bat
PREPARER_DONNEES_HYPERSMART.cmd cross-venue
```

## Télécharger vraiment une sélection

Le téléchargement massif est volontairement explicite. Exemple :

```bat
python -m hl_observer.ops.dataset_bridge prepare --root . --contains copy_vault --download --max-download-gib 20
```

Le pont :

1. lit le manifeste complet ;
2. sélectionne les chemins demandés ;
3. calcule les assets GitHub réellement nécessaires ;
4. refuse si le volume dépasse le plafond donné ;
5. télécharge dans `data/hypersmart_datasets/assets/` ;
6. vérifie la taille et le SHA-256 de chaque asset ;
7. reconstruit uniquement les fichiers sélectionnés dans `data/hypersmart_datasets/materialized/` ;
8. vérifie aussi le SHA-256 du fichier reconstruit ;
9. écrit un rapport dans `runtime/reports/datasets/DERNIERE_PREPARATION_DATASET.json`.

Mettre `--max-download-gib 0` signifie que le plafond est désactivé. À utiliser seulement lorsque le volume affiché avant téléchargement est accepté.

## Pourquoi le dossier `materialized` est important

Les chemins originaux sont conservés sous :

```text
data/hypersmart_datasets/materialized/
```

Exemple : un ancien fichier `runtime/data/copy_vault_l2_tape.jsonl` devient :

```text
data/hypersmart_datasets/materialized/runtime/data/copy_vault_l2_tape.jsonl
```

Ainsi les moteurs de replay qui savent travailler avec une racine de données peuvent recevoir `data/hypersmart_datasets/materialized` comme racine sans réécrire le contenu historique.

## Sécurité et vérité des données

- aucune exécution réelle ;
- aucun `/exchange` ;
- aucune signature ;
- aucune clé privée ;
- aucun fichier n'est accepté si le SHA-256 distant est absent ou faux ;
- aucune reconstruction n'est acceptée si sa taille ou son SHA-256 ne correspondent pas au manifeste ;
- aucun chemin d'archive n'a le droit de sortir du dossier de reconstruction ;
- une donnée absente provoque un NO_GO, jamais une valeur inventée.

## Suite du chantier

Le pont et la carte sont les deux premières étapes. Ensuite il faut :

1. utiliser la carte pour connaître précisément la couverture par famille, période et résolution ;
2. produire des vues canoniques pour Copy-Vault, Lead-Lag et Cross-Venue ;
3. brancher ces vues aux moteurs de replay existants ;
4. lancer train / validation / OOS / forward ;
5. mesurer PnL brut, coûts, PnL net, ROI, drawdown et stabilité ;
6. ne promouvoir une famille que si la preuve économique est positive et reproductible.
