# Audit final de portabilite Windows - 2026-08-09

## Verdict

- HEAD de depart audite : `93887fd3c0e7e83bcd9305b42f682e3af6115782`.
- Runtime cible : Windows x64, Python et Git embarques, simulation locale/read-only.
- Etat technique local : les protections, verifications et outils de preuve sont implementes et testes sur le PC A.
- `PORTABLE_READY=false` tant que la recette physique PC A -> PC B n'a pas ete executee sur deux machines distinctes.
- Aucun resultat ne pretend remplacer cette preuve physique.

## Commit ledger

| Commit | Livraison |
|---|---|
| `a403964` | Verification integrale du staging avant publication atomique du clone |
| `c1a119e` | Propagation des erreurs du lanceur et chemin GitHub securise unique |
| `fa7ab68` | Controles Windows, chemins longs, outils et dependances embarquees |
| `748774b` | Verification de l'identite du processus qui ecoute sur le port UI |
| `d8a5f72` | Preuve de transfert exigeant deux empreintes machine distinctes |
| `d0d08c7` | Verification post-transfert, CMD officiels, collecte et preuves durables |
| `5151468` | Ajout verrouille de PyArrow pour HyperLab/Parquet portable |

## Couverture des 15 exigences

| # | Exigence | Statut factuel | Preuve |
|---:|---|---|---|
| 1 | Verifier le staging avant `os.replace` | DONE | `portable_clone.py` verifie le manifeste et les hashes complets avant publication atomique ; la cible n'est pas publiee en cas d'echec. |
| 2 | `portable-check` impose `verify_clone(full_hash=True)` | DONE | Le manifeste full-clone declenche la verification exhaustive avant `PORTABLE_LAUNCHER_CHECK_OK`. |
| 3 | Propager `ERRORLEVEL` pour install/build/zip | DONE | Les sous-commandes capturent immediatement le code retour et le transmettent dans `RC`. |
| 4 | Un seul chemin de push embarque | DONE | Delegation exclusive a `POUSSER-GITHUB-FORCE.cmd`, `tools/git` et `push_github_safe.ps1` ; ancien `git push --ff-only` retire. |
| 5 | Refuser Git/Codex actif, worktree modifie, source mouvante | DONE | Preflight processus/worktree et empreintes source debut/fin obligatoires. |
| 6 | `git fsck --full`, HEAD, branche et remotes apres clone | DONE | Verification avec le Git embarque et comparaison source/cible. |
| 7 | Refus des chemins de plus de 259 caracteres | DONE | Controle sur le chemin cible reel au check et au premier lancement ; recommandation `C:\HyperSmart`. |
| 8 | Refus des reparse points critiques | DONE | Les symlinks/junctions/reparse non explicitement autorises font echouer le clone. |
| 9 | Proprietaire reel du port 8794 | DONE | Un port occupe n'est jamais assimile a HyperSmart sans verification PID/commande. |
| 10 | Preuves PowerShell/CIM/taskkill/schtasks | DONE | Preflight Windows fail-closed sur les outils requis. |
| 11 | Verification Python/Git/wheels/DLL/TLS/imports/collecteurs/scripts/ressources | DONE | Controle post-transfert et lock wheelhouse ; 72 wheels, dont PyArrow 25.0.0 verrouille. |
| 12 | CMD officiels depuis un autre chemin avec espaces et accents | DONE | Test automatise depuis un cwd etranger contenant espaces et `e` accent aigu. |
| 13 | Recette PC A -> transport -> PC B -> 15 min -> replay | READY_TO_RUN | `LANCER_HYPERSMART.cmd portable-proof` automatise la recette et refuse la meme machine ; execution physique PC B encore requise. |
| 14 | Identite ledger/sessions/rapports/historiques/hashes/HEAD | DONE_CODE / PENDING_PHYSICAL | Le manifeste v2 contient les aggregates durables et le HEAD Git ; la comparaison physique sera validee par `portable-proof`. |
| 15 | Suite Windows finale et preuves | PARTIAL | Suites ciblees vertes ; la suite `python -m pytest -q` a atteint la limite dure de 3 604 secondes (`exit 124`) alors que le processus progressait encore en CPU, sans verdict pytest final. |

## Recette physique obligatoire

1. Depuis le PC A, creer le clone complet avec le lanceur officiel.
2. Transporter le dossier obtenu sans le modifier vers le PC B, idealement sous `C:\HyperSmart`.
3. Sur le PC B, lancer :

```bat
LANCER_HYPERSMART.cmd portable-proof
```

Cette commande doit prouver, sans raccourci :

- empreinte machine PC B differente du PC A ;
- verification full-hash du clone ;
- Python, Git, wheelhouse, DLL, TLS, imports et ressources dynamiques ;
- `portable-check` puis `portable-smoke` ;
- auto-tests sans reseau des CMD officiels depuis un cwd distinct ;
- collecte reelle pendant 900 secondes ;
- arret propre par `Q` ;
- session fraiche `COMPLETE` ;
- replay `full` puis `deep` ;
- egalite des empreintes durables et de l'identite Git attendue.

Si une etape echoue, la commande retourne un code non nul et `PORTABLE_READY` reste faux.

## Tests et audits obtenus sur le PC A

- Tests CMD officiels : `1 passed`.
- HyperLab/Parquet : `54 passed`.
- Recette ciblee finale (portabilite, lanceurs, transfert, wheelhouse et HyperLab) : `213 passed, 1 skipped, 36 warnings` en 38,76 s.
- `portable-check` : OK, Python embarque, imports complets, chemin maximal mesure a 259 caracteres.
- `POUSSER-GITHUB-FORCE.cmd --portable-self-check` : OK, sans reseau.
- `CREER_ARCHIVE_PORTABLE.cmd --portable-self-check` : OK, sans creation d'archive.
- `--safety-check` : OK.
- `--audit-safety` : OK.
- Suite complete `python -m pytest -q` : limite du harnais atteinte apres 3 604 secondes (`exit 124`), sans verdict pytest final ni sortie partielle exploitable.

## Limites honnetes

- Une machine unique ne peut pas produire la preuve physique PC A -> PC B demandee.
- Le chemin source actuel atteint exactement 259 caracteres pour son element le plus long ; `C:\HyperSmart` reste fortement recommande.
- La suite globale est trop longue pour la limite d'une heure de cette recette ; les suites ciblees sont vertes, mais cela ne remplace pas un verdict global.
- Les artefacts runtime vivants, locks et heartbeats ne sont pas inclus dans les commits source.
- La portabilite garantit l'environnement logiciel et les controles locaux ; elle ne garantit pas la disponibilite future du reseau ou des services externes.

## Securite

Le runtime reste paper/read-only : aucun ordre reel, aucune cle privee, aucune signature et aucun endpoint d'execution mainnet operationnel.
