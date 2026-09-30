# HyperSmart — arrêt / reprise Codex — objectif 3 × +4 USD NET

Date du checkpoint : **2026-08-24**  
Branche autorisée : **`main` uniquement**  
Mode : **PAPER / READ-ONLY / DENY-BY-DEFAULT**

## 1. But de ce checkpoint

Ce fichier est le point de reprise destiné à Codex après les très gros runs des 22–23 août 2026.
Il interdit de repartir de zéro et fixe la vérité de départ avant la prochaine session.

**Objectif économique inchangé :** obtenir et certifier séparément :

- Copy-Vault : `LIQUIDATABLE_NET >= +4.00 USD` ;
- Lead-Lag : `LIQUIDATABLE_NET >= +4.00 USD` ;
- Cross-Venue : `LIQUIDATABLE_NET >= +4.00 USD`.

Aucune compensation entre familles. Aucun résultat train/exploratoire ne vaut certification.
OOS, forward post-freeze, placebo, coûts complets, provenance, réconciliation et positions plates restent obligatoires.

## 2. Ancre Git exacte

Le parent immédiatement avant ce checkpoint est :

`26d3d6b9eb8c667ab8bd3a410aec24b27fbc56c2` — `Aligne la whitelist Copy-Vault sur la preuve robuste`.

Ce parent est lui-même **113 commits devant** le point de reprise ChatGPT/Codex du 22 août
`44171e83edf27ae6e44a96e1dd7d21ed5844c5f7`.

La reprise Codex doit partir du **commit qui contient le présent fichier**, c'est-à-dire du HEAD de `main` après ce checkpoint.

Il n'existe qu'une branche autorisée/finale : `main`.

## 3. Travail déjà réalisé — ne pas recommencer

Depuis la reprise du 22 août, de très gros blocs ont déjà été implémentés et testés. Parmi eux :

- diagnostic causal Lead-Lag et autopsie des gaps ;
- convergence/normalisation des diagnostics Lead-Lag concurrents ;
- alignement causal des sources et fenêtres d'événements ;
- exploration Lead-Lag multi-actif train-only ;
- mécanismes vNext Copy-Vault train-only ;
- mécanisme Cross-Venue v3 train-only ;
- pack économique vNext commun ;
- identité globale des preuves économiques ;
- interdiction de réutilisation de preuve entre familles ;
- empreintes canoniques de provenance/certification ;
- durcissement de `ALINA_RETURN` pour empêcher tout surclassement d'une preuve exploratoire ;
- complétude des jobs économiques famille ;
- schéma self-hosted fermé ;
- nombreux contrats runner immuables et gros runs Lead-Lag FULL/vNext ;
- travail important sur `coverage-parallel-probe` et le cache/exécuteur coverage ;
- alignement de la whitelist Copy-Vault sur la preuve robuste.

**Ne pas recréer une architecture parallèle, ne pas refaire les anciens diagnostics, ne pas retuner l'OOS pour embellir un résultat.**

## 4. État machine au parent du checkpoint

Au SHA parent `26d3d6b9...`, les statuts GitHub observés sont :

- `hypersmart/security-quality` : **SUCCESS** ;
- `hypersmart/coverage-parallel-probe` : **FAILURE** ;
- `hypersmart/pre-run-775` : **FAILURE** ;
- `hypersmart/technical-perfect` : **FAILURE**.

Cela signifie :

- le développement économique peut continuer ;
- le runner final exact-SHA ne doit pas être déclaré certifié tant que les gates exigées ne sont pas vertes ;
- la clôture technique finale reste ouverte ;
- ce checkpoint lui-même déclenchera un nouveau SHA et devra être revalidé normalement.

Aucun statut `hypersmart/economic-3of3=success` n'est établi par ce checkpoint.
**Traiter l'objectif 3/3 comme NON CERTIFIÉ tant qu'une preuve canonique distincte ne le démontre pas.**

## 5. Agiflow — source de pilotage

La tasklist Agiflow autoritative est :

**`HyperSmart — TASKLIST MASTER OPTIMISÉE`**

Ne plus piloter depuis l'ancien projet Agiflow archivé `HyperSmart — MASTER 3×4 USD NET`.

Chantiers actifs importants au moment du checkpoint :

- méga run Lead-Lag FULL vNext ;
- réparation `coverage-parallel-probe` sans données ;
- fermeture coverage exacte 100,00 % + CI finales ;
- E2E runner famille jusqu'à `ALINA_RETURN` ;
- protection contre le surclassement économique dans `ALINA_RETURN` ;
- interdiction de réutilisation inter-familles ;
- consolidation du diagnostic causal Lead-Lag ;
- contrat de complétude des jobs économiques famille.

Codex doit lire la tasklist actuelle avant de créer des doublons.

## 6. Priorité de reprise Codex

### A — Reprendre l'objectif économique en cours, pas le redéfinir

1. Lire `AGENTS.md`.
2. Lire `docs/CURRENT_STATE.md`.
3. Lire `docs/release/HYPERSMART_REPRISE_CHATGPT_3X4_NET_20260822.md`.
4. Lire `docs/release/HYPERSMART_CHATGPT_REPRISE_RUN_20260823.md`.
5. Lire le présent checkpoint.
6. Examiner les derniers commits et artifacts/résultats existants avant tout nouveau gros run.
7. Ne pas refaire ce qui est déjà prouvé/codé.

### B — Lead-Lag

La causalité/gaps/multi-actif ont déjà reçu beaucoup de travail.
La prochaine session doit d'abord exploiter les résultats les plus récents et déterminer ce qui manque réellement pour une preuve économique certifiable.
Ne pas ressusciter une variante tuée sans donnée neuve.

### C — Copy-Vault

La whitelist simple n'est plus l'autorité. Le dernier parent aligne explicitement la whitelist sur la preuve robuste.
Poursuivre uniquement des hypothèses train-only qui respectent la robustesse, les entités, la concentration, les jours/régimes et la causalité.

### D — Cross-Venue

Le v2 tué ne doit pas être maquillé. Le v3 train-only existe déjà : reprendre ses preuves/résultats et la collecte disponible avant de lancer une nouvelle variante.
Exiger ouverture/fermeture des deux jambes, coûts des deux venues, capacité, latence, purge/embargo, aucune position résiduelle.

### E — CI / runner

Ne pas consommer tout le quota Codex à refaire la CI si un travail économique utile peut avancer en parallèle.
Mais avant toute certification runner exacte du SHA :

- réparer la cause racine du coverage rouge ;
- obtenir les gates techniques requises ;
- créer le contrat runner immuable **en dernier commit** ;
- ne plus déplacer `main` pendant le gate stale-SHA et le run ;
- lire l'artifact `ALINA_RETURN` et la recertification canonique avant toute annonce.

## 7. Règles absolues pour la prochaine session

- `main` uniquement ;
- aucune exécution réelle ;
- aucune clé privée / signature / `/exchange` ;
- aucun reset/clean destructeur des données runtime ;
- aucune donnée synthétique présentée comme preuve réelle ;
- aucun seuil diminué après observation validation/OOS ;
- aucun skip/xfail/exclusion/baisse de seuil pour fabriquer un vert ;
- aucun même trade/événement réutilisé entre segments ou familles ;
- un verdict `KILL` / `MORE_DATA` reste préférable à un faux +4 ;
- gros runs et gros commits cohérents sont autorisés, mais chaque commit doit garder le repo compréhensible et reproductible ;
- la vérité finale vient des ledgers/gates/artifacts canoniques, pas d'un résumé narratif.

## 8. Définition de fin

Le chantier économique n'est terminé que lorsque les trois familles affichent séparément une preuve canonique :

`Copy-Vault  : LIQUIDATABLE_NET >= +4.00 USD — CERTIFIÉ`  
`Lead-Lag    : LIQUIDATABLE_NET >= +4.00 USD — CERTIFIÉ`  
`Cross-Venue : LIQUIDATABLE_NET >= +4.00 USD — CERTIFIÉ`

avec OOS, forward post-freeze, placebos, coûts complets, provenance, identités uniques, aucune position ouverte et aucune compensation.

La clôture globale exige ensuite les gates techniques finales du même SHA.

## 9. Synchronisation locale sûre avant de relancer Codex

Dossier local :

`C:\Users\flo\Desktop\Projet invest`

**Important : ne jamais faire directement `git reset --hard origin/main` si Codex a encore du travail local non poussé.**

Procédure de sécurité recommandée :

```powershell
$ErrorActionPreference = 'Stop'
$Repo = 'C:\Users\flo\Desktop\Projet invest'
Set-Location -LiteralPath $Repo

# 1) Vérifier le dépôt et sauvegarder tout travail local non commité.
git status --short --branch
$dirty = @(git status --porcelain=v1 --untracked-files=all)
if ($dirty.Count -gt 0) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    git stash push -u -m "BACKUP_AVANT_REPRISE_CODEX_$stamp"
    if ($LASTEXITCODE -ne 0) { throw 'Echec du stash de sécurité' }
}

# 2) Récupérer le dernier main GitHub sans supprimer les données ignorées.
git fetch origin --prune --tags
if ($LASTEXITCODE -ne 0) { throw 'Echec git fetch' }

git switch main
if ($LASTEXITCODE -ne 0) { throw 'Impossible de passer sur main' }

# 3) Refuser d'écraser des commits locaux non poussés.
$localOnly = @(git log --oneline origin/main..HEAD)
if ($localOnly.Count -gt 0) {
    Write-Host 'STOP : commits locaux non poussés détectés :' -ForegroundColor Red
    $localOnly | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    throw 'Pousser ou sauvegarder ces commits avant la synchronisation.'
}

# 4) Fast-forward uniquement : aucun historique local n'est réécrit.
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'Le fast-forward a échoué : ne pas forcer.' }

# 5) Vérification finale.
$local  = (git rev-parse HEAD).Trim()
$remote = (git rev-parse origin/main).Trim()
Write-Host "LOCAL       : $local"
Write-Host "ORIGIN/MAIN : $remote"
if ($local -ne $remote) { throw 'LOCAL != ORIGIN/MAIN' }

git status --short --branch
Write-Host 'REPO LOCAL SYNCHRONISÉ EN SÉCURITÉ — prêt pour Codex.' -ForegroundColor Green
```

Si un stash a été créé, **ne pas faire `git stash pop` automatiquement** avant Codex : conserver ce backup à part jusqu'à avoir confirmé qu'il n'est plus nécessaire.

## 10. Message court à donner à Codex

> Reprends exactement le chantier HyperSmart 3×4 USD NET depuis le HEAD actuel de `main` et lis d'abord `docs/release/HYPERSMART_ARRET_REPRISE_CODEX_3X4_NET_20260824.md`. Ne repars pas de zéro. Exploite les 113+ commits déjà réalisés, la TASKLIST MASTER OPTIMISÉE et les artifacts/runs existants. Continue les hypothèses économiques en cours jusqu'aux preuves canoniques +4 USD séparées, sans tricher les coûts/OOS/forward/placebos, main uniquement, paper/read-only. Gros runs et gros commits cohérents. Ne crée un contrat self-hosted final qu'en dernier commit sur un SHA techniquement admissible et ne déplace plus `main` pendant ce run.
