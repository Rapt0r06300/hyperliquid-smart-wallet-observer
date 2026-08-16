# Plans d'expérience FULL/COLD

## But

La bibliothèque FULL/COLD contient des volumes très différents selon les familles de données. Une expérience ne doit donc pas commencer par « télécharger tout » ou « relire tout ».

Le plan d'expérience sert à fixer une sélection reproductible avant le replay :

```text
période + famille + coin + wallet + métrique
        ↓
profil Research Lab déjà calculé
+ schémas SQLite read-only
+ provenance de la suite
        ↓
CURRENT_EXPERIMENT_PLAN.json / .md
```

Le plan **ne copie aucune donnée brute**, **ne télécharge aucun asset**, **ne lance aucun replay** et **n'utilise aucun réseau**. Il décrit seulement les sources compatibles et les filtres qui devront être appliqués.

## Commande Python

Exemple :

```powershell
python -m hl_observer.ops.dataset_experiment_plan `
  --root "<workspace>" `
  --start-ms 1780000000000 `
  --end-ms 1780100000000 `
  --family copy_vault `
  --coin BTC `
  --wallet 0xabc
```

Les critères sont optionnels :

- `--start-ms` / `--end-ms` : bornes temporelles en millisecondes ;
- `--family` : famille recherchée ;
- `--coin` : coin normalisé en majuscules ;
- `--wallet` : wallet précis ;
- `--metric` : métrique devant être présente dans la source ;
- `--require-complete-research` : refuse les profils Research Lab interrompus avant EOF ;
- `--include-unknown-time` : permet explicitement les fichiers sans bornes temporelles connues.

Une période inversée est refusée.

## Bouton Windows

Pour un workspace déjà reconstruit :

```bat
PREPARER_EXPERIENCE_FULL_COLD.cmd SUITE [FAMILLE] [COIN] [METRIQUE] [START_MS] [END_MS] [WALLET]
```

Exemples :

```bat
PREPARER_EXPERIENCE_FULL_COLD.cmd economic-full copy_vault BTC net_pnl_usd
PREPARER_EXPERIENCE_FULL_COLD.cmd sqlite-core copy_vault BTC "" 1780000000000 1780100000000 0xabc
```

Le bouton retrouve uniquement le workspace courant de la suite avec `dataset_bridge locate`. Il n'appelle jamais `prepare --download` et ne lance pas `ANALYSER_DONNEES_HYPERSMART.cmd`.

## Sélection Research Lab

Le plan lit :

```text
runtime/reports/datasets/RESEARCH_LAB_STREAM_PROFILE.json
```

Ce profil est produit par `dataset_research_inventory`. Les critères sont comparés aux métadonnées déjà calculées :

- bornes temporelles ;
- compteurs de familles ;
- coins ;
- métriques repérées ;
- état complet/partiel.

Cela permet de choisir les bons gros JSONL **sans les rescanner uniquement pour savoir s'ils sont pertinents**.

Par défaut, lorsqu'une période est demandée, un fichier sans période connue n'est pas assimilé à un match. `--include-unknown-time` permet de l'inclure explicitement et le plan le marque alors comme incertain.

## Sélection SQLite

Le plan ouvre les bases autorisées via la couche SQLite read-only existante puis inspecte uniquement leur schéma.

Il ne fait pas de `SELECT *` sur les milliards de lignes pour construire le plan.

Pour chaque couple base/table, il vérifie si les critères peuvent être appliqués avec les colonnes sûres :

- filtre temporel ;
- filtre coin ;
- filtre wallet ;
- filtre famille ;
- métrique demandée.

Les valeurs de filtres restent destinées à des requêtes SQL paramétrées dans `sqlite_research_source.py`.

Cas Copy-Vault : certaines tables historiques comme `fills`, `positions`, `position_deltas` ou `wallet_snapshots` n'ont pas forcément une colonne `family`. Elles peuvent être conservées comme sources Copy-Vault implicites lorsque les autres critères sont applicables. Le plan l'indique par `IMPLICIT_COPY_SOURCE` au lieu de prétendre qu'un filtre SQL `family` existe.

Les colonnes brutes de type `raw_json`/payload ne sont pas exposées par cette couche.

## Provenance

Le plan incorpore les petits champs utiles de :

```text
runtime/reports/datasets/SELECTION_PROVENANCE.json
```

notamment :

- Release source ;
- dépôt source si disponible ;
- suite ;
- digest de sélection de la suite.

Un workspace sans provenance peut encore être inspecté, mais le plan ajoute `PROVENANCE_NOT_READY`.

## Digest reproductible

Le digest d'expérience dépend de :

```text
critères normalisés
+ release/suite/digest source
+ chemins Research Lab retenus
+ couples base SQLite / table retenus
```

Il ne dépend pas du chemin absolu du PC pour les sources situées dans le workspace.

Deux plans identiques sur le même snapshot doivent donc produire le même digest.

## Sorties

Les rapports sont écrits dans :

```text
runtime/reports/datasets/experiment_plans/
```

avec :

```text
experiment_<digest16>.json
experiment_<digest16>.md
CURRENT_EXPERIMENT_PLAN.json
CURRENT_EXPERIMENT_PLAN.md
```

Le fichier `CURRENT_EXPERIMENT_PLAN.*` donne la sélection active la plus récente.

## Statuts

`READY` signifie qu'au moins une source Research Lab ou un couple SQLite base/table satisfait le plan.

`NO_MATCH` signifie qu'aucune source connue ne satisfait les critères actuels. Cela ne doit pas être contourné par des données synthétiques : il faut soit corriger une donnée manquante, soit élargir consciemment les critères.

`PROFILE_MISSING` côté Research Lab signifie que le gros scan/profil n'a pas encore produit son rapport. Le plan ne déclenche pas ce scan automatiquement afin d'éviter un long run caché.

## Progression gzip

Le scanner officiel utilisé par `dataset_research_inventory` distingue maintenant :

- `scanned_physical_bytes` : octets réellement consommés dans le fichier `.gz` ;
- `logical_scanned_bytes` : octets JSONL décompressés traités.

Le pourcentage/ETA d'un `.jsonl.gz` repose uniquement sur les octets **compressés physiques** et est borné à 100 %. Le volume logique peut naturellement dépasser la taille du fichier compressé.

Les JSONL non compressés restent reprenables par checkpoint/offset. Les `.gz` ne sont pas déclarés reprenables par offset.

## Sécurité

Le plan d'expérience respecte les invariants suivants :

```text
HL_ENABLE_MAINNET_EXECUTION=0
HL_ENABLE_TESTNET_EXECUTION=0
REAL_MAINNET_TRADING=false
HYPERSMART_ANALYSIS_LOCAL_ONLY=1
```

Il n'utilise ni `/exchange`, ni signature, ni ordre, ni collecte live. Il s'agit uniquement d'une couche de préparation reproductible pour la recherche historique locale.

## Ce que le plan ne prouve pas

Un plan `READY` signifie seulement que des sources compatibles existent.

Il ne signifie pas :

- PnL positif ;
- ROI positif ;
- edge causal ;
- validation OOS ;
- robustesse forward ;
- rentabilité future.

Ces preuves doivent venir ensuite des replays/backtests appropriés avec coûts, séparation temporelle et garde-fous anti-overfit.
