# Vérification du contrat d'expérience FULL/COLD

## Pourquoi cette étape existe

Un plan `READY` et un contrat correctement généré ne suffisent pas à autoriser un futur replay.

Entre la préparation de l'expérience et son exécution, un fichier peut être supprimé, remplacé ou modifié. Une base SQLite peut aussi perdre une table ou une colonne attendue. Alina SmartFlow vérifie donc le contrat une nouvelle fois contre le workspace réel avant de considérer les entrées prêtes.

La chaîne attendue est :

```text
CURRENT_EXPERIMENT_PLAN.json
        ↓ READY
CURRENT_REPLAY_INPUT_CONTRACT.json
        ↓
vérification du digest + fichiers + schémas
        ↓
CURRENT_REPLAY_INPUT_CONTRACT_VERIFICATION.json
        ↓ READY uniquement
futur replay ciblé
```

## Commande

```powershell
python -m hl_observer.ops.dataset_experiment_contract_verify --root "<workspace>"
```

Le bouton Windows `PREPARER_EXPERIENCE_FULL_COLD.cmd` lance cette vérification automatiquement après la création du contrat.

## Ce qui est vérifié

Le vérificateur contrôle sans lire les lignes économiques :

- le digest du contrat ;
- le lien avec le digest du plan courant ;
- les champs de sécurité `read_only`, `network_used=false`, `real_execution=false` ;
- le nombre de sources déclaré ;
- les chemins relatifs au workspace ;
- l'existence des fichiers Research Lab ;
- leur taille attendue lorsqu'elle est connue ;
- l'appartenance des bases SQLite à la liste des bases sûres ;
- l'existence des tables SQLite ;
- l'existence des colonnes autorisées ;
- la possibilité d'appliquer les filtres temps / coin / wallet / famille demandés.

Pour SQLite, seules les informations de schéma sont consultées. Le vérificateur ne fait pas de lecture des trades, fills ou autres lignes de marché.

## Sorties

```text
runtime/reports/datasets/experiment_contracts/
  CURRENT_REPLAY_INPUT_CONTRACT_VERIFICATION.json
  CURRENT_REPLAY_INPUT_CONTRACT_VERIFICATION.md
```

Le rapport contient notamment :

```text
status
contract_digest_ok
experiment_link_ok
declared_source_count
verified_source_count
errors
warnings
row_data_read=false
read_only=true
network_used=false
real_execution=false
```

## Statuts

`READY` signifie uniquement que le contrat correspond encore au plan courant et que les fichiers/schémas nécessaires sont toujours présents.

`NO_GO` bloque la préparation. Exemples :

- digest du contrat modifié ;
- plan courant différent ;
- fichier Research Lab absent ;
- taille d'un fichier Research Lab modifiée ;
- base SQLite absente ou quarantainée ;
- table disparue ;
- colonne autorisée disparue ;
- filtre demandé devenu impossible ;
- compteur de sources incohérent.

Un `NO_GO` ne doit jamais être remplacé par une donnée synthétique ou un succès forcé.

## Codes de sortie CLI

```text
0 = READY
2 = erreur de lecture / configuration / workspace
4 = contrat vérifié mais NO_GO
```

Ces codes permettent au lanceur Windows ou à un futur runner automatisé de rester fail-closed.

## Ce que cette vérification ne prouve pas

Même un contrat vérifié `READY` ne prouve pas :

- un PnL positif ;
- un edge causal ;
- une validation OOS ;
- une robustesse walk-forward ;
- une rentabilité future.

Elle prouve seulement que le futur replay reçoit les sources qu'il pense recevoir, dans un état compatible avec le contrat préparé.
