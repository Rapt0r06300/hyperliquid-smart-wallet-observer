# Alina SmartFlow — runner Windows self-hosted HyperSmart

## But

Transformer un PC Windows personnel en **worker de calcul HyperSmart** piloté depuis GitHub, sans déplacer les gros datasets à chaque run.

Architecture :

`ChatGPT/GitHub -> main -> commande JSON -> GitHub Actions -> runner Windows self-hosted -> ALINA_RESEARCH_HOME -> backtests/replays -> ALINA_RETURN.json + petits rapports GitHub -> ChatGPT`.

Les ~170–180 Gio de données, caches, workspaces, checkpoints et gros logs restent localement sur le PC.

## Ce qui est versionné dans GitHub

- `.github/workflows/alina-self-hosted.yml` : plan de contrôle GitHub Actions ;
- `src/hl_observer/ops/self_hosted_control.py` : canonisation et verrouillage des commandes ;
- `src/hl_observer/ops/self_hosted_return.py` : retour compact machine-lisible après calcul ;
- `src/hl_observer/ops/autonomous_research_job.py` : worker autonome ;
- `src/hl_observer/ops/autonomous_research_guard.py` : timebox maximale 18 h ;
- `src/hl_observer/ops/autonomous_research_brain.py` : choix de la prochaine phase de recherche ;
- `src/hl_observer/datasets/max_data_policy.py` : escalade MAX DATA ;
- `tools/ALINA_RESEARCH_COCKPIT.ps1` : statut seconde par seconde ;
- `tools/INSTALLER_ALINA_RUNNER_WINDOWS.ps1` : installation du runner ;
- `tools/VERIFIER_ALINA_RUNNER_WINDOWS.ps1` : diagnostic local ;
- `PREPARER_PC_ALINA.cmd` : mise à jour sûre de `main`, installation, vérification et ouverture du cockpit ;
- `control/alina_jobs/` : file de commandes GitHub -> PC.

## Installation recommandée : une seule procédure

Depuis le dossier local HyperSmart, double-cliquer sur :

```text
PREPARER_PC_ALINA.cmd
```

Cette procédure :

1. refuse toute branche différente de `main` ;
2. refuse de toucher à un worktree contenant des modifications locales ;
3. fait uniquement `git fetch origin main` puis `git pull --ff-only origin main` ;
4. valide les scripts avec Windows PowerShell 5.1 ;
5. demande l'élévation administrateur et **attend réellement la fin** de l'installation ;
6. exécute `VERIFIER_ALINA_RUNNER_WINDOWS.ps1` ;
7. ouvre le cockpit uniquement si le diagnostic est vert.

Aucun `git reset`, `git clean`, checkout forcé ou écrasement silencieux n'est utilisé.

## Installation PowerShell directe

Pour choisir manuellement les paramètres, ouvrir **Windows PowerShell en administrateur** dans la racine du projet puis lancer :

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\tools\INSTALLER_ALINA_RUNNER_WINDOWS.ps1
```

Par défaut l'installateur choisit le disque fixe disposant du plus d'espace libre et crée :

- `<disque>:\ALINA_RESEARCH_HOME` ;
- `<disque>:\ALINA_RUNNER_HYPERSMART`.

Il est possible d'imposer les chemins :

```powershell
.\tools\INSTALLER_ALINA_RUNNER_WINDOWS.ps1 -LabRoot 'D:\ALINA_RESEARCH_HOME' -RunnerRoot 'D:\ALINA_RUNNER_HYPERSMART'
```

Le script exige Python 3.11+ et Git. Il obtient le jeton temporaire d'enregistrement via `gh` si GitHub CLI est déjà authentifié. Sinon il demande un token GitHub masqué, l'utilise uniquement pour demander le jeton temporaire du runner puis l'oublie.

Le token GitHub ne doit jamais être écrit dans un fichier du projet ou dans `ALINA_RESEARCH_HOME`.

## Service Windows et reprise automatique

Le runner est installé comme **service Windows automatique**. L'installateur configure aussi la récupération du service :

- premier crash : redémarrage après 1 minute ;
- deuxième crash : redémarrage après 1 minute ;
- crash suivant : redémarrage après 5 minutes ;
- compteur de pannes remis à zéro chaque jour.

Cette reprise concerne le **service GitHub Actions Runner**. La reprise métier des campagnes reste gérée séparément par la timebox, les résultats persistants et les mécanismes de cache/checkpoint du laboratoire.

## Vérification

```powershell
.\tools\VERIFIER_ALINA_RUNNER_WINDOWS.ps1
```

Résultat attendu : `DIAGNOSTIC FINAL : RUNNER PRÊT`.

Le service Windows doit être `Running` et le runner doit porter au minimum les labels :

- `self-hosted` ;
- `Windows` ;
- `X64` ;
- `hypersmart` ;
- `alina`.

## Cockpit seconde par seconde

Depuis la racine du projet :

```text
LANCER_COCKPIT_ALINA.cmd
```

Le lanceur relit directement la variable machine `ALINA_RESEARCH_HOME` si la fenêtre CMD était déjà ouverte avant l'installation.

On peut aussi lancer le cockpit directement depuis le stockage persistant :

```text
%ALINA_RESEARCH_HOME%\LANCER_COCKPIT_ALINA.cmd
```

Le cockpit peut être fermé sans arrêter le runner ni le calcul.

## Déclenchement d'un job

Deux voies existent.

### 1. Commande GitHub versionnée

Créer un **nouveau** `*.json` dans `control/alina_jobs/` et le commiter sur `main`.

C'est la voie prévue pour le contrôle depuis ChatGPT/GitHub : un nouveau fichier de commande provoque automatiquement le workflow `alina-self-hosted`.

Les commandes versionnées sont **immuables** :

- ajout d'un nouveau JSON : autorisé ;
- modification d'un ancien JSON : refusée par le workflow ;
- renommage/suppression d'un ancien JSON : refusé ;
- un gros run = un nouveau fichier = une trace Git indépendante.

Cette règle permet de relier chaque expérience à son SHA, son contrat et ses résultats sans recycler l'historique.

### 2. GitHub Actions / Run workflow

Le workflow peut aussi être lancé manuellement depuis GitHub avec `workflow_dispatch`.

## Règles de sécurité du runner

Le workflow est volontairement limité :

- aucun déclenchement `pull_request` ;
- `runs-on: [self-hosted, Windows, X64, hypersmart]` ;
- `permissions: contents: read` ;
- checkout du SHA exact de `main` ;
- `HL_ENABLE_MAINNET_EXECUTION=0` ;
- `HL_ENABLE_TESTNET_EXECUTION=0` ;
- `REAL_MAINNET_TRADING=false` ;
- worker `paper_only=true` ;
- collecte live interdite pour ces gros jobs FULL/COLD ;
- maximum 18 h par cycle ;
- données brutes et gros logs jamais envoyés comme artifact ;
- seuls les petits résultats préparés par le worker sont remontés.

## Stockage persistant

Structure attendue :

```text
ALINA_RESEARCH_HOME/
  datasets/
    assets/
    metadata/
    materialized/
    workspaces/
  jobs/
    requests/
  results/
    github/
  job_logs/
  checkpoints/
  status/
    CURRENT_STATUS.json
    GITHUB_SYNC_STATUS.json
  tools/
```

Le checkout GitHub Actions reste jetable. `ALINA_RESEARCH_HOME` ne l'est pas.

## Premier test conseillé

Le premier job réel doit rester un replay canonique ciblé, suffisamment gros pour valider toute la chaîne mais assez petit pour diagnostiquer rapidement un problème de runner, de cache ou de reconstruction.

Une fois ce circuit validé :

1. `economic-full` ;
2. suite de la famille prioritaire (`copy-vault-full`, `lead-lag-full` ou `cross-venue-full`) ;
3. `microstructure-full` ;
4. `research-lab-full` ;
5. `sqlite-all-safe` ;
6. `full-archive`.

La politique MAX DATA peut choisir l'escalade utile selon les preuves, la famille prioritaire et l'espace disque restant.

## Résultats et boucle d'analyse

Chaque run crée localement :

`%ALINA_RESEARCH_HOME%\results\github\run_<GITHUB_RUN_ID>`

Les journaux potentiellement volumineux restent dans :

`%ALINA_RESEARCH_HOME%\job_logs\<JOB_ID>`

Avant l'upload, `self_hosted_return.py` construit :

```text
ALINA_RETURN.json
ALINA_RETURN.md
```

`ALINA_RETURN.json` contient uniquement un résumé allowlisté :

- statut technique du job ;
- SHA et digest de la requête ;
- suite et mode ;
- métriques disponibles de Copy-Vault, Lead-Lag et Cross-Venue ;
- PnL net/coûts/ROI/drawdown/compteurs lorsqu'ils existent ;
- raisons de refus bornées ;
- décision du cerveau de recherche ;
- prochain type de run recommandé.

Il n'embarque pas les fills bruts, payloads `raw_json`, bases SQLite ou gros historiques.

Le workflow publie ensuite uniquement le dossier de résultats préparé dans un artifact GitHub nommé :

`alina-resultats-<GITHUB_RUN_ID>`

Depuis ChatGPT/GitHub, cet artifact peut être récupéré et `ALINA_RETURN.json` analysé pour préparer **un nouveau JSON immuable** dans `control/alina_jobs/`. Cela ferme la boucle :

`commande -> PC -> calcul -> retour compact -> analyse -> prochain gros run`.

Le cockpit reçoit aussi `GITHUB_SYNC_STATUS.json` afin d'afficher :

- si l'artifact est parti ;
- si `ALINA_RETURN.json` est prêt ;
- combien de petits fichiers ont été remontés ;
- si l'analyse suivante peut commencer.

Un artifact réussi signifie uniquement que les preuves ont été transférées. Il ne prouve pas un PnL positif.

## Objectif économique

Le laboratoire vise une preuve nette robuste et séparée pour :

- Copy-Vault ;
- Lead-Lag ;
- Cross-Venue Dislocation.

La cible de recherche actuelle est `>= 4,00 USD net` par famille avec coûts observables, sans compensation entre familles et sans tuning sur la magnitude OOS/forward.
