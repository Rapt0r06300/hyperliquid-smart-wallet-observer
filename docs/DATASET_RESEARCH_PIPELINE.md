# Laboratoire historique sur les workspaces FULL/COLD

Les suites FULL/COLD reconstruites ne servent plus seulement de stockage. Le projet principal peut exécuter son laboratoire historique en gardant deux racines distinctes :

- **racine du code** : le dépôt Alina SmartFlow courant ;
- **racine des données** : un workspace isolé issu de la Release privée `371149058`.

Cette séparation évite de copier le code dans chaque archive et empêche aussi de mélanger plusieurs expériences historiques dans `runtime/data`.

## Inventaire des sources réellement présentes

Chaque workspace peut générer :

```text
runtime/reports/datasets/FAMILY_SOURCES.json
```

Le manifeste `hypersmart.dataset_family_sources.v2` recense de façon déterministe les fichiers réellement présents pour :

- Copy-Vault ;
- Lead-Lag ;
- Cross-Venue ;
- market ticks / microstructure ;
- candidates/marks de replay ;
- logs historiques ;
- **bases SQLite et sidecars** ;
- **Research Lab**.

Les copies archivées restent des fichiers distincts dans le manifeste. Elles ne sont jamais fusionnées silencieusement avec le runtime courant.

Commande :

```powershell
python -m hl_observer.datasets.source_discovery --root "<workspace>"
```

## Consommation multi-source des trois moteurs

Le raccord économique large est maintenant explicite :

- **Lead-Lag** reçoit toutes les bandes BBO compatibles manifestées dans un workspace FULL/COLD ;
- **Copy-Vault** construit une vue canonique dérivée depuis ses multiples copies compatibles, avec rejet des lignes exactement dupliquées ;
- **Cross-Venue** fusionne les carnets compatibles de manière déterministe et rejette les observations contradictoires au même timestamp au lieu d'en choisir une arbitrairement.

Le rapport :

```text
runtime/reports/datasets/SOURCE_CONSUMPTION_COVERAGE.json
runtime/reports/datasets/SOURCE_CONSUMPTION_COVERAGE.md
```

permet de comparer les sources découvertes et celles réellement transmises aux moteurs.

Ce raccord n'est activé que pour un workspace dataset portant sa provenance FULL/COLD. Le runtime quotidien normal conserve ses chemins et son comportement habituels.

## SQLite : les ~58 Gio deviennent une source de recherche

Deux suites permettent de cibler les bases sans récupérer inutilement une ancienne copie connue comme corrompue :

| Suite | Contenu |
|---|---|
| `sqlite-core` | uniquement `runtime/data/hypersmart_simulation_session.sqlite3` et `data/hl_observer.sqlite3` |
| `sqlite-all-safe` | toutes les bases finissant par `.sqlite3`, hors chemins marqués corrupt/broken/damaged/quarantine/invalid et hors `.git` |

Le profiler SQLite :

```powershell
python -m hl_observer.ops.dataset_sqlite_inventory --root "<workspace>"
```

ouvre les bases saines via SQLite `mode=ro`, active `PRAGMA query_only=ON`, décrit le schéma et ferme chaque connexion. Il n'exporte aucune valeur de ligne.

Sorties :

```text
runtime/reports/datasets/SQLITE_INVENTORY.json
runtime/reports/datasets/SQLITE_INVENTORY.md
```

Les fichiers WAL/SHM sont inventoriés comme sidecars mais ne sont jamais ouverts comme bases. Les fichiers dont le nom contient un marqueur de corruption/quarantaine sont refusés automatiquement.

`--quick-check` existe, mais reste volontairement désactivé par défaut : un `PRAGMA quick_check(1)` sur plusieurs dizaines de Gio peut être long.

### Tables historiques utilisables

Le second adaptateur transforme les SQLite en sources historiques contrôlées :

```powershell
python -m hl_observer.ops.dataset_sqlite_research --root "<workspace>"
```

Il produit :

```text
runtime/reports/datasets/SQLITE_RESEARCH_CATALOG.json
runtime/reports/datasets/SQLITE_RESEARCH_CATALOG.md
```

Une allowlist fixe autorise uniquement des tables économiques connues, par exemple `fills`, `positions`, `position_deltas`, `wallet_snapshots`, `wallet_scores`, `wallet_candidates`, `paper_trades`, `paper_intents`, `risk_events` et `source_health` lorsqu'elles existent réellement dans la base.

Les colonnes brutes comme `raw_json` ou les payloads complets ne sont pas exposées par cette couche.

Pour créer une vue JSONL dérivée et locale :

```powershell
python -m hl_observer.ops.dataset_sqlite_research `
  --root "<workspace>" `
  --export-table fills
```

Sortie par défaut :

```text
runtime/reports/datasets/sqlite_views/fills.jsonl
```

Cette vue est une commodité de replay. La source SQLite reste inchangée.

## Research Lab : scan de dizaines de Gio sans les charger en RAM

Les très gros `episodes.jsonl`, `working_set.jsonl` et autres JSONL du Research Lab sont lus en streaming.

Commande longue :

```powershell
python -m hl_observer.ops.dataset_research_inventory `
  --root "<workspace>" `
  --heartbeat-seconds 5
```

Par défaut :

- tous les JSONL Research Lab sont ciblés ;
- aucun plafond de volume ni de lignes n'est imposé ;
- les gros fichiers non compressés sont **reprenables** ;
- un heartbeat affiche progression, lignes, JSON invalides, débit et ETA ;
- les checkpoints sont conservés sous `runtime/reports/datasets/research_lab_checkpoints/` ;
- aucun événement brut complet n'est copié dans le rapport.

Pour une sonde courte :

```powershell
python -m hl_observer.ops.dataset_research_inventory `
  --root "<workspace>" `
  --max-files 3 `
  --max-gib-per-file 0.25
```

Le profiler agrège notamment : familles, types d'événements, coins, bornes temporelles et métriques numériques connues telles que PnL net/brut, frais, spread, slippage, latence, drawdown, ROI, `edge_remaining_bps`, `net_bps` et profit factor lorsqu'elles sont présentes.

Sorties :

```text
runtime/reports/datasets/RESEARCH_LAB_STREAM_PROFILE.json
runtime/reports/datasets/RESEARCH_LAB_STREAM_PROFILE.md
```

Ces agrégats cartographient les preuves existantes. Ils ne sont pas assimilés à une validation OOS.

## Laboratoire historique principal

Commande générique :

```powershell
python -m hl_observer.ops.dataset_research_runner `
  --root . `
  --data-root "<workspace>" `
  --suite research-lab-full `
  --full
```

Le runner commence maintenant par :

1. inventaire SQLite read-only ;
2. catalogue SQLite de recherche ;
3. sonde streaming Research Lab ;
4. puis les briques historiques existantes.

Il réutilise ensuite :

- consolidation replay ;
- laboratoire PnL ;
- qualité des données ;
- market-truth ;
- preuve Lead-Lag ;
- replay A/B ;
- replay causal du ledger ;
- tournoi de stratégies ;
- audit PnL ;
- attribution des pertes ;
- diagnostics de latence/fraîcheur ;
- walk-forward ;
- audit anti-overfit.

Avec `--full`, le runner reprend également les checkpoints du Research Lab et lance un scan sans plafond jusqu'à EOF lorsque ces fichiers existent.

Une étape dont les données obligatoires ne sont pas présentes est `SKIPPED` avec la raison exacte. Elle n'est jamais remplacée par des données synthétiques.

Le mode `--deep` ajoute la recherche de scénarios reprenable.

## Depuis le bouton des ~180 Go

`LANCER_LABO_180GO.cmd` fait :

```text
plan de suite
-> confirmation
-> cache partagé
-> vérification SHA-256
-> reconstruction isolée
-> inventaire FAMILY_SOURCES.json
-> replay économique pour economic-core/economic-full
   OU laboratoire historique pour les autres suites
```

Le menu expose notamment :

```text
research-lab-full
sqlite-core
sqlite-all-safe
full-archive
```

Le launcher garde :

```text
HL_ENABLE_MAINNET_EXECUTION=0
HL_ENABLE_TESTNET_EXECUTION=0
REAL_MAINNET_TRADING=false
```

## Doctrine de vérité

Le fait qu'un fichier existe ne suffit pas à déclarer un edge. Le pipeline distingue désormais :

```text
fichier archivé
-> fichier sélectionné
-> asset vérifié
-> workspace reconstruit
-> source découverte
-> source réellement consommée
-> métrique mesurée
-> replay causal
-> coûts
-> train/validation/OOS/forward
-> verdict
```

Une ancienne DB marquée corrompue, un cache, un fichier `.git`, une copie logicielle ou un payload brut ne devient donc jamais automatiquement une donnée de stratégie.

Les ~180 Go sont une bibliothèque de recherche historique. Les nouvelles observations postérieures au snapshot restent indispensables pour confirmer ou invalider en forward toute découverte faite dans cette bibliothèque.
