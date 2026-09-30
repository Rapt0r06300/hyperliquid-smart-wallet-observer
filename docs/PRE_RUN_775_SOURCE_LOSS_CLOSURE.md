# Clôture de récupération — roadmap pré-run 1→775

## Statut

La roadmap maître `HYPERSMART_PNL_CANONICAL_775` a bien existé comme liste numérotée 1→775.
Les formulations littérales exactes de 321→775 ne sont plus récupérables depuis les sources
actuellement accessibles (dépôt GitHub, historique Git, fichiers de reprise indexés et contexte de
conversation récupérable). Elles ne doivent donc jamais être recréées de mémoire ni remplacées par
des libellés inventés.

Cette clôture porte uniquement sur **la récupération de la source historique**. Elle ne déclare pas
que 775 optimisations techniques ont été exécutées ni que les objectifs économiques sont atteints.

## Ancres littérales récupérées

- 301 — Interdire promotion par PnL sans coûts
- 314 — Reconstruction OPEN/ADD/REDUCE/CLOSE parfaite
- 315 — Retraits/dépôts non confondus avec PnL
- 316 — Wallet/vault identity stable
- 317 — Backfill complet
- 318 — Pagination userFillsByTime
- 319 — Déduplication fills
- 320 — Fraîcheur du leader

## Exigences thématiques récupérées — Copy-Vault

Conserver et vérifier au minimum : `userFillsByTime`, pagination, OPEN, ADD, REDUCE, CLOSE,
retraits/dépôts non confondus avec PnL, identité vault/wallet, copyability, freshness,
latence leader→follower, slippage follower, capacité, dépendance à un seul gros gain, consistance,
drawdown, régimes, TWAP/metaorders et conflits entre vaults.

La généralisation held-out doit rester réelle : vault jamais vu avant OOS, trades OOS/forward,
coûts réels, taille d'échantillon suffisante, PnL net et placebo. Aucune preuve held-out artificielle.

## Exigences thématiques récupérées — Lead-Lag

Conserver et vérifier : timestamps certifiables, causalité, lag réel, multi-horizon, régimes,
début de seconde, minute, 5 minutes, 15 minutes, OFI, microprice, queue depletion, adds/cancels,
profondeur, latence, univers, stress coûts et placebos.

Une horloge monotone locale à un processus ne peut pas certifier une chronologie entre processus
ou redémarrages. Toute ligne non certifiable doit être explicitement classée ou rejetée.

## Exigences thématiques récupérées — Cross-Venue Dislocation

Conserver et vérifier : synchronisation des venues, clock skew, fraîcheur BBO, profondeur, VWAP,
mapping exact des instruments, entrée jambe A, entrée jambe B, sortie A, sortie B, quatre fills
lorsque le cycle complet l'exige, frais, latence inter-jambes, risque de jambe nue, partial fills,
missed leg, convergence, max holding, panne venue, widening du spread et disparition de profondeur.

Aucun arbitrage ne doit reposer sur un faux mapping ou des prix non exécutables.

## Anti-overfit

Conserver : train, validation, OOS, forward, purging, embargo, walk-forward, CPCV lorsque pertinent,
PBO, placebos, sensitivity neighbours, stress fees, stress slippage, stress latency et univers
alternatifs. La magnitude OOS/forward ne doit jamais devenir un gradient d'optimisation ; le holdout
sert à confirmer ou veto, pas à retuner jusqu'à +4 USD.

## MAX DATA / autonomie / mémoire économique

`TARGET_NET_USD_PER_FAMILY = 4.0` reste la cible par famille. MAX DATA doit connaître les suites
réellement terminées, être lié au SHA, éviter les recomputations inutiles, utiliser cache et
checkpoints, savoir escalader/arrêter, ne pas utiliser le holdout comme gradient et continuer si une
des trois familles reste sous +4 USD.

`COMPLETED_SUITES` ne doit jamais accepter SKIPPED, exit_code absent, prepare-only ou analyse
incomplète comme SUCCESS. L'état doit idéalement être lié au SHA, snapshot dataset, suite, config et
preuve runtime.

La mémoire économique doit être séparée par SHA, famille, snapshot et configuration. Copy ne peut
écraser Lead, Lead ne peut écraser Cross, Cross ne peut écraser Copy. Un résultat incomplet, ancien
ou provenant d'un autre SHA ne remplace jamais silencieusement une preuve certifiée courante.

## Déterminisme / mutations globales

Éliminer les monkeypatchs globaux et mutations cachées de configuration. Préférer validation pure,
routing déterministe, entrées explicites et sorties explicites.

## Self-hosted runner

`PREPARER_PC_ALINA.cmd` reste **non lancé**. Le runner self-hosted reste volontairement non installé.
Il ne doit être installé qu'après audits, optimisations, tests et rehearsals pré-run verts, avec un
`GO_SELF_HOSTED = TRUE` explicite.

Les durcissements à conserver incluent : main uniquement, SHA exact, acteur propriétaire, aucune PR,
`contents: read`, `persist-credentials: false`, commande contrôlée, dataset token dédié en lecture,
paper-only, exécution réelle false, artifacts sanitizés. Continuer à vérifier permissions, secrets,
Actions pinées par SHA, code exécuté avant gate, dataset non fiable, path traversal, zip-slip,
symlinks, scripts/exécutables dans dataset, shell injection, inputs bornés et absence de
`contents:write` côté PC.

## CI

Avant runner, viser un HEAD où les suites pertinentes sont vertes : HyperSmart CI, données Linux,
données Windows, PowerShell 5.1, HyperLab, Alpha Factory, labo continu, portable Windows,
replay=forward, sécurité et tests self-hosted. Aucune CI rouge ne doit être masquée par suppression
artificielle de tests.

## Windows portable

Conserver l'architecture Python embarqué, MinGit, wheelhouse, build offline, tests hermétiques et
archive reproductible. Continuer à vérifier imports, circular imports, paths, espaces, autre disque,
nouveau PC, no user-site, no Python système, runtime exact et SQLite après copie.

## Observabilité

Le cockpit doit pouvoir exposer : étape, sous-étape, fichier courant, x/N, GiB traités/total, vitesse,
ETA, CPU, RAM, disque, PID, child processes, dernier heartbeat, checkpoint, log, nombre de trades,
refus, cause principale, état dataset et état GitHub. Ne jamais afficher « GitHub online » uniquement
parce qu'un service Windows est Running.

## Documentation / README

Le README doit représenter l'état actuel d'Alina SmartFlow / HyperSmart : Copy-Vault, Lead-Lag,
Cross-Venue, FULL/COLD Data, Replay, Backtest, Paper Only, cible +4 USD par famille, architecture,
bibliothèque ~180 Go, méthode de preuve PnL, MAX DATA, sécurité, lanceurs, portable Windows, CI,
documentation et roadmap. Ne pas présenter le runner comme installé.

## Rehearsals et GO final

Avant FULL ~180 Go : tests unitaires, intégration, CI, dataset déterministe, economic-core, petit
corpus réel, ~4–5 GiB, crash/reprise, profil RAM, profil disque, preuve runtime consumption, suite
famille, economic-full, microstructure-full, research-lab-full, sqlite-all-safe puis full-archive.

Le GO final exige raisonnablement : main propre, CI verte, portable/Linux/Windows/PowerShell 5.1
verts, replay=forward, ledger ~180 Go, runtime consumption proof, aucun faux FULL, checkpoints,
crash/reprise, mémoire bornée, PnL réconcilié, trois familles certifiables, anti-overfit, placebos,
artifacts sanitizés, permissions/secrets, reproductibilité, docs actuelles et rehearsals verts.

Seulement ensuite : `GO_SELF_HOSTED = TRUE`.

## Règle de provenance

Le statut terminal `RECOVERY_CLOSED_SOURCE_LOSS` signifie :
1. la recherche de la source littérale est terminée ;
2. la source exacte 321→775 est considérée irrécupérable avec les sources accessibles ;
3. les ancres exactes connues et exigences thématiques récupérées sont conservées ;
4. aucun libellé 321→775 ne peut être présenté comme « original » sans nouvelle source primaire ;
5. ce statut n'est **jamais** équivalent à `DONE` pour l'exécution des 775 optimisations.
