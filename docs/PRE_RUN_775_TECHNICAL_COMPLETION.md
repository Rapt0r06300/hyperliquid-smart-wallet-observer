# HyperSmart — clôture technique canonique 1→775

## État de la clôture

Les **775 contrôles techniques** sont désormais implémentés par catégories spécifiques. La source
historique littérale 321→775 reste irrécupérable et n'est jamais inventée : les identifiants
321→775 sont des preuves techniques dérivées, chacune avec cinq facettes exécutables.

Le manifeste canonique est désormais **scellé à 775/775** sous le statut
`DONE_TECHNICAL_775_SOURCE_LOSS_HONEST` : **775/775 contrôles techniques**, **455/455 facettes
dérivées** et **91/91 exigences de base** sont terminés, avec `next_unverified_id = null`.
Le scellement n'a été effectué qu'après une exécution verte de la CI dédiée. Toute modification
ultérieure de `main` relance `.github/workflows/pre-run-321-775.yml` et doit conserver le statut
`hypersmart/pre-run-775 = success`; un rouge invalide immédiatement la clôture du HEAD concerné.
Cette règle empêche qu'un simple texte `DONE` puisse remplacer une preuve GitHub Actions.

## Blocs techniques

- **1→320** : contrôles historiques préexistants et ancres PnL ;
- **321→395** : Copy‑Vault — 15 exigences × 5 facettes ;
- **396→465** : Lead‑Lag — 14 exigences × 5 facettes ;
- **466→545** : Cross‑Venue — 16 exigences × 5 facettes ;
- **546→605** : Anti‑overfit — 12 exigences × 5 facettes ;
- **606→655** : MAX DATA / autonomie / mémoire économique — 10 × 5 ;
- **656→670** : déterminisme et suppression des mutations globales — 3 × 5 ;
- **671→710** : sécurité self-hosted — 8 × 5 ;
- **711→730** : CI — 4 × 5 ;
- **731→750** : Windows portable — 4 × 5 ;
- **751→760** : observabilité — 2 × 5 ;
- **761→765** : documentation — 1 × 5 ;
- **766→775** : rehearsals et GO final — 2 × 5.

Les facettes sont toujours : `CONTRACT`, `POSITIVE_PATH`, `NEGATIVE_FAIL_CLOSED`,
`DETERMINISM_CAUSALITY`, `EVIDENCE_PROVENANCE`.

## Anti‑overfit

Train/OOS/forward restent séparés. Purging, embargo, walk‑forward, CPCV, PBO, placebos,
sensibilité des voisins, stress frais/slippage/latence et univers alternatifs sont testables.
Le holdout ne classe jamais les candidats : le classement est gelé sur TRAIN puis OOS/forward ne
peuvent que **confirmer ou veto**. Aucun retuning vers la cible économique après observation du
holdout n'est autorisé.

## Objectif économique et MAX DATA

La cible reste **≥ 4 USD net séparément pour Copy‑Vault, Lead‑Lag et Cross‑Venue**, jamais une
compensation entre familles. `COMPLETED_SUITES` reste fail‑closed et lié au SHA. MAX DATA sait
escalader les suites FULL/COLD, réutiliser cache/checkpoints, conserver une réserve disque et
continuer tant qu'une famille reste sous la cible.

La mémoire économique est maintenant immuable et partitionnée par :

`project SHA × famille × snapshot dataset × configuration × suite × preuve runtime`.

Une preuve incomplète, stale, d'un autre SHA ou d'une autre famille ne peut pas écraser une preuve
certifiée.

## Déterminisme

Les monkeypatchs globaux identifiés dans les routeurs MAX DATA et job autonome sont supprimés.
L’adaptateur économique FULL/COLD n’altère plus non plus les globals du runner canonique : il exécute
une fonction isolée avec des dépendances explicitement injectées. Le routage est explicite : mêmes
entrées → mêmes décisions, sans mutation cachée du module canonique.
Replay/paper et digest de dataset restent reproductibles.

## Self-hosted : toujours NON installé par défaut

`PREPARER_PC_ALINA.cmd`, `INSTALLER_ALINA_RUNNER_WINDOWS.cmd` et le PowerShell installateur refusent
tous l'installation tant que la variable exacte **`GO_SELF_HOSTED=TRUE`** n'est pas définie.
Le runner self-hosted n'est donc pas présenté comme installé par cette roadmap.

Le workflow conserve : `main` uniquement, SHA exact, acteur propriétaire, aucune PR,
`contents: read`, `persist-credentials: false`, actions pinées par SHA, token dataset dédié,
paper-only, exécution réelle false et artifact public allowlisté.

Le workspace FULL/COLD est traité comme **non fiable** : path traversal/zip-slip fail-closed,
symlinks/reparse points refusés et scripts/exécutables apportés par le dataset refusés avant
exécution d'un outil projet.

## CI et Windows portable

La clôture vérifie HyperSmart CI, données Linux/Windows, PowerShell 5.1, HyperLab, Alpha Factory,
labo continu, portable Windows, replay=forward, sécurité et self-hosted. Aucun test ne peut être
supprimé dans le commit de clôture pour masquer un rouge.

La portabilité conserve Python embarqué, MinGit, wheelhouse/offline, `PYTHONNOUSERSITE=1`, absence
de fallback Python système, build reproductible, chemins avec espaces/autre disque/nouveau PC et
SQLite vérifié après copie.

## Observabilité

Le cockpit distingue maintenant explicitement **service runner local** et **connexion GitHub
prouvée**. Un service Windows `Running` ne suffit plus à afficher GitHub en ligne. Lorsqu'ils sont
disponibles, le cockpit expose étape/sous‑étape, fichier, x/N, Gio, vitesse, ETA, CPU, RAM, disque,
PID, child processes, heartbeat, checkpoint, log, trades, refus, cause principale et état dataset.

## Rehearsals avant FULL ~180 Go

L'ordre de rehearsal est exécutable et fail‑closed : unitaires → intégration → CI → dataset
déterministe → economic‑core → petit corpus réel → ~4–5 Gio → crash/reprise → profils RAM/disque →
preuve de consommation runtime → suite famille → economic‑full → microstructure‑full →
research‑lab‑full → sqlite‑all‑safe → full‑archive.

Le GO final exige ensuite main propre, CI verte, plateformes vertes, replay=forward, ledger ~180 Go,
preuve de consommation, aucun faux FULL, checkpoints, crash/reprise, mémoire bornée, PnL réconcilié,
trois familles certifiables, anti‑overfit/placebos, artifacts sanitizés, permissions/secrets,
reproductibilité et documentation actuelle. **Seulement alors** le contrat accepte
`GO_SELF_HOSTED=TRUE`.

## Ce que 775/775 ne signifie pas

La clôture technique ne prétend ni que les trois stratégies gagnent déjà +4 USD, ni que le FULL
~180 Go a déjà été exécuté sur le PC self-hosted. Elle signifie que les **775 contrôles pré-run sont
implémentés, testables, fail-closed et reliés à une preuve spécifique**. Les résultats économiques
restent des résultats de données et doivent être prouvés séparément.
