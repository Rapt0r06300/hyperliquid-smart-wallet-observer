# Alina SmartFlow — Local READ-ONLY Observer

## Objectif

Permettre d'auditer le dossier local du portable :

`C:\Users\rberm\Desktop\Projet AlinaSmartFlow`

depuis un self-hosted runner GitHub, sans modifier ce dossier.

Le workflow associé est :

`.github/workflows/local-readonly-observer.yml`

Il est **manuel uniquement** (`workflow_dispatch`) et exige la phrase exacte :

`I_AUTHORIZE_READ_ONLY_OBSERVER`

Sans cette phrase, le job s'arrête avant l'observation.

## Ce que l'observateur sait faire

Le premier mode implémenté couvre :

- inventaire de l'arborescence visible : chemins, tailles, dates, catégories ;
- SHA-256 des fichiers suivis et comparaison avec un checkout séparé de `main` ;
- `git status`, HEAD, branche, branches locales, remotes et commits locaux ;
- vérification de la présence des commits récents dans les objets/branches GitHub du checkout séparé ;
- liste des fichiers non suivis ;
- diff texte local versus GitHub pour les fichiers modifiés ;
- copie dans l'artefact des **fichiers texte modifiés/non suivis uniquement**, avec redaction de secrets évidents ;
- audit statique des sources : TODO/FIXME/PLACEHOLDER, `pass`, `NotImplementedError`, erreurs de syntaxe Python, chemins utilisateur codés en dur, doublons exacts et symboles fortement répétés ;
- inventaire des datasets, replays, résultats, rapports et logs par métadonnées ;
- détection des exécutables Python locaux sans les exécuter ;
- lecture des ACL Windows du dossier ;
- lecture des processus Alina/HyperSmart correspondants ;
- lecture de l'espace disque ;
- rapport Markdown + JSON + CSV ;
- preuve avant/après que l'arbre source protégé n'a pas changé ;
- preuve avant/après que `.git/index` n'a pas changé.

## Ce que l'observateur ne fait jamais

Dans le dossier observé, le workflow ne doit jamais exécuter :

- `git fetch`
- `git pull`
- `git checkout`
- `git switch`
- `git reset`
- `git clean`
- `git add`
- `git commit`
- `git push`
- installation de paquet
- lancement de replay/backtest
- lancement/arrêt de collecteur
- suppression ou réécriture de fichier

Les éventuels `git fetch` servent uniquement au **checkout GitHub séparé du runner** sous `C:\actions-runner\_work\...`, jamais au dossier local Alina.

Les fichiers de preuve sont écrits sous `RUNNER_TEMP`, donc hors du dossier observé.

## Données et logs

L'inventaire automatique remonte les métadonnées des logs et datasets : chemin, taille, date, fraîcheur et catégorie.

Le contenu brut de tous les logs/datasets n'est **pas** copié automatiquement. Pour éviter de remonter accidentellement des secrets ou des datasets énormes, la lecture détaillée d'un fichier particulier restera une action ciblée et explicitement autorisée.

Les sources locales modifiées/non suivies peuvent être copiées dans l'artefact après redaction des secrets évidents, car elles sont nécessaires pour diagnostiquer précisément ce que Nemotron a changé.

## Garantie read-only

Deux niveaux sont déjà implémentés :

1. **Garde logicielle** : le code de l'observateur n'a besoin d'aucune commande Git d'écriture sur la cible et la sortie est refusée si elle se trouve dans la cible.
2. **Postcondition** : l'observateur compare une signature de l'arbre source avant/après, et le workflow compare le SHA-256 de `.git/index` avant/après. Un changement fait échouer le run.

Une protection encore plus forte est possible ultérieurement : exécuter le runner sous un compte Windows auquel NTFS accorde uniquement `Read & Execute` sur le dossier Alina. Cette étape modifierait les permissions Windows du portable et nécessite donc une autorisation séparée ; elle n'est pas appliquée par ce chantier.

## Artefact produit

Un futur run autorisé produira notamment :

- `REPORT.md`
- `report.json`
- `inventory.csv`
- `inventory_details.json`
- `git.json`
- `tracked_comparison.json`
- `untracked.json`
- `local_vs_github_main.patch`
- `changed_text/`
- `static_findings.json`
- `environment.json`
- `windows_preflight.json`
- `processes.json`
- `disk.json`
- `git_index_postcondition.json`
- `protected_before.json`
- `protected_after.json`

Cet artefact pourra ensuite être analysé pour décider comment réparer/synchroniser le portable, sans avoir touché aux fichiers locaux.
