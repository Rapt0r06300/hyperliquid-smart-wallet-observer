# Plan actuel des données FULL/COLD

Ce document reprend le dernier plan calculé automatiquement dans le dépôt privé `Rapt0r06300/hypersmart-datasets` à partir de :

- `FULL_UPLOADED_FILE_MANIFEST.jsonl.gz` ;
- `FULL_RELEASE_ASSET_MANIFEST.json` ;
- Release source `371149058`.

Les volumes **bruts** correspondent aux fichiers reconstruits ciblés. Les volumes **à télécharger** correspondent aux assets GitHub uniques nécessaires : un même asset n'est compté qu'une fois par suite.

| Suite projet principal | Groupe plan privé | Fichiers | Gio bruts | Assets | Gio à télécharger | Assets manquants |
|---|---|---:|---:|---:|---:|---:|
| `economic-core` | `economic_core` | 618 | 4,3737 | 4 | 4,5229 | 0 |
| `economic-full` | `economic_full` | 2 379 | 7,9600 | 11 | 9,8289 | 0 |
| `copy-vault-full` | `copy_vault` | 506 | 0,2138 | 6 | 3,8647 | 0 |
| `lead-lag-full` | `lead_lag` | 1 209 | 7,3729 | 11 | 9,8289 | 0 |
| `cross-venue-full` | `cross_venue` | 688 | 0,3739 | 8 | 5,9058 | 0 |
| `microstructure-full` | `microstructure` | 1 070 | 0,5714 | 8 | 5,9058 | 0 |
| `research-lab-full` | `research_lab` | 19 241 | 63,0292 | 47 | 61,0100 | 0 |
| `sqlite-core` | `sqlite_core` | 2 | 58,1430 | 36 | 58,1430 | 0 |
| `sqlite-all-safe` | `sqlite_all_safe` | 293 | 58,4429 | 41 | 60,6375 | 0 |
| `full-archive` | `full_archive` | 150 546 | 176,0341 | 112 | 158,8381 | 0 |

## Ce que ces chiffres changent

`economic-core` reste le contrôle rapide : environ **4,52 Gio d'assets**.

`economic-full` est le meilleur premier vrai replay large des trois moteurs : environ **9,83 Gio d'assets**, bien plus riche que `economic-core` sans imposer les ~60 Gio des blocs massifs.

`research-lab-full` est un chantier lourd : environ **61,01 Gio d'assets**. Le scanner streaming/checkpoint est donc obligatoire ; ce volume ne doit jamais être chargé en RAM ou recommencé depuis zéro après une interruption.

`sqlite-core` représente déjà **58,143 Gio pour seulement deux bases**. C'est pourquoi elles sont ouvertes directement en lecture seule et les vues historiques sont filtrables par période/coin/wallet/famille.

`sqlite-all-safe` monte à **60,6375 Gio d'assets** parce que l'archive contient de nombreuses copies SQLite saines par leur nom. Cette suite doit être utilisée pour un audit historique large, pas par défaut.

`full-archive` demande **158,8381 Gio d'assets** pour reconstruire **176,0341 Gio bruts**. Elle existe pour l'exhaustivité et les audits transversaux ; une expérience ciblée doit préférer une suite plus petite.

## Ordre de travail recommandé

```text
1. economic-core       -> contrôle du pipeline
2. economic-full       -> premier replay économique large
3. famille ciblée      -> Copy / Lead-Lag / Cross-Venue si besoin
4. research-lab-full   -> scan/checkpoints + sélections ciblées
5. sqlite-core         -> tables historiques principales
6. sqlite-all-safe     -> audit SQLite exhaustif si nécessaire
7. full-archive        -> seulement pour audit transversal complet
```

Les assets partagés restent dans le cache commun : un téléchargement déjà validé pourra donc réduire les volumes restants des suites suivantes.

## Règle de vérité

Un volume disponible n'est pas une preuve économique. Chaque expérience doit encore suivre :

```text
source -> provenance -> consumer -> replay causal -> coûts -> train/validation/OOS/forward -> verdict
```

Le rapport `DATASET_CONNECTION_AUDIT.md` distingue désormais le raccordement technique des preuves réellement produites par les runs.
