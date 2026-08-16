# Laboratoire historique sur les workspaces FULL/COLD

Les suites FULL/COLD reconstruites ne servent pas seulement de stockage. Le projet principal peut maintenant exécuter son laboratoire historique en gardant deux racines distinctes :

- **racine du code** : le dépôt Alina SmartFlow courant ;
- **racine des données** : un workspace isolé issu de la Release privée `371149058`.

Cette séparation évite de copier le code dans chaque archive et évite aussi de mélanger plusieurs expériences historiques dans `runtime/data`.

## Inventaire des sources

Chaque workspace peut générer :

```text
runtime/reports/datasets/FAMILY_SOURCES.json
```

Le manifeste recense de façon déterministe les fichiers réellement présents pour :

- Copy-Vault ;
- Lead-Lag ;
- Cross-Venue ;
- market ticks / microstructure ;
- candidates/marks de replay ;
- logs historiques.

Les copies archivées restent des fichiers distincts dans le manifeste. Elles ne sont jamais fusionnées silencieusement avec le runtime courant.

Commande :

```powershell
python -m hl_observer.datasets.source_discovery --root "<workspace>"
```

## Laboratoire historique

Commande générique :

```powershell
python -m hl_observer.ops.dataset_research_runner `
  --root . `
  --data-root "<workspace>" `
  --suite research-lab-full `
  --full
```

Le runner réutilise les briques existantes du projet :

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

Une étape dont les données obligatoires ne sont pas présentes est `SKIPPED` avec la raison exacte. Elle n'est jamais remplacée par des données synthétiques.

Le mode `--deep` ajoute la recherche de scénarios reprenable. Il n'est pas lancé automatiquement par le bouton principal afin d'éviter une exploration très longue par accident.

## Depuis le bouton des ~180 Go

`LANCER_LABO_180GO.cmd` fait maintenant :

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

Le launcher garde :

```text
HL_ENABLE_MAINNET_EXECUTION=0
HL_ENABLE_TESTNET_EXECUTION=0
REAL_MAINNET_TRADING=false
```

## Ce que cela ne prétend pas encore

Le fait qu'un fichier soit recensé dans `FAMILY_SOURCES.json` ne signifie pas encore que chaque moteur historique le consomme automatiquement. Certains moteurs anciens utilisent encore un chemin canonique unique.

Le manifeste sert précisément à rendre ce manque **mesurable** : on peut comparer le nombre de sources présentes au nombre de sources réellement consommées dans les rapports, puis adapter les loaders famille par famille sans perdre la provenance.

La prochaine couture est donc volontairement explicite : faire consommer aux loaders Copy-Vault, Lead-Lag et Cross-Venue toutes leurs sources compatibles du manifeste, avec déduplication et ordre temporel déterministes.
