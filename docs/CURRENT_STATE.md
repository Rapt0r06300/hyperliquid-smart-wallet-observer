# Alina SmartFlow — état courant autoritatif

Dernière mise à jour : **2026-08-19**.

Ce document est la **source de vérité lisible actuelle** pour l'état du projet. Il ne remplace pas les contrats exécutables : en cas de divergence, le code, les tests, les gates CI et les registres machine gagnent toujours.

## 1. Périmètre économique actif

Le périmètre canonique est défini par `src/hl_observer/strategies/active_scope.py`.

Familles économiques paper actives :

- `copy_vault` ;
- `lead_lag` ;
- `cross_venue_dislocation`.

`funding_carry` et les autres familles historiques ne doivent pas réapparaître comme moteurs économiques actifs sans changement explicite du scope canonique et tests associés.

## 2. Sécurité

Le projet reste **paper/read-only** :

- `HL_ENABLE_MAINNET_EXECUTION=0` ;
- `HL_ENABLE_TESTNET_EXECUTION=0` ;
- aucun ordre réel ;
- aucune signature ;
- aucune clé privée ;
- aucune donnée synthétique présentée comme preuve économique réelle ;
- toute donnée économique manquante ou non liquidable doit conduire à un verdict fail-closed.

La politique de signalement est dans `SECURITY.md`.

## 3. Chantier des 775 optimisations pré-run

Le registre canonique des **775 optimisations pré-run est scellé 775/775**. Il n'est pas permis de renuméroter, supprimer ou recycler les identifiants 1–775. Toute découverte réellement nouvelle commence à 776+.

Les gates dédiées restent des preuves de conformité pré-run ; elles ne sont pas, à elles seules, une preuve de rentabilité économique.

## 4. Vérité économique

Aucune cible économique ne doit être déclarée atteinte sans preuve **LIQUIDATABLE_NET**, coûts complets, OOS, forward, placebo et échantillon suffisant.

Au gel de certification du 12/08/2026, les verdicts documentés étaient :

- Copy-Vault : `MORE_DATA` ;
- Lead-Lag : `MORE_DATA` ;
- Cross-Venue v2 : `KILL`.

Les campagnes et infrastructures ajoutées depuis peuvent produire de nouvelles preuves, mais **un résultat exploratoire, train, synthétique ou observé n'est pas automatiquement un PnL prouvé**. La cible +4 USD par famille ne doit être annoncée que par la gate économique canonique.

Un verdict économique `KILL`, `MORE_DATA` ou négatif n'empêche pas le logiciel d'être techniquement parfait : au contraire, refuser honnêtement une stratégie non prouvée fait partie de la qualité attendue.

## 5. PARFAIT / TOUT VERT — définition machine

La certification technique est **indépendante du verdict économique**. Le statut machine autoritatif est :

`hypersmart/technical-perfect`

Il ne peut être publié `success` que lorsque, sur le **même SHA** :

1. la gouvernance versionnée est cohérente ;
2. l'audit de vulnérabilités Python est vert ;
3. l'analyse statique bloquante est verte ;
4. la suite complète sous coverage termine sans rouge ;
5. le cliquet de couverture ne régresse pas.

Le workflow `security-quality` publie ce statut. S'il manque ou s'il est rouge, il est interdit de dire « PARFAIT / TOUT VERT » pour ce SHA.

Cette certification ne prétend jamais que les trois familles gagnent de l'argent. La preuve économique garde ses propres gates et ses propres verdicts.

## 6. CI et certification

La certification globale attend au minimum :

- `hypersmart-ci` ;
- `hyperlab-ci` ;
- `labo-continu-ci` ;
- `alpha-factory` ;
- `portable-release-windows` ;
- `security-quality` ;
- statut `hypersmart/technical-perfect=success`.

Le workflow `security-quality` ajoute :

- gate de gouvernance ;
- audit de vulnérabilités Python ;
- analyse statique structurelle ;
- cliquet de couverture de lignes fail-closed ;
- publication d'un verdict technique unique sur le SHA exact.

## 7. Gouvernance GitHub

La protection native de `main` reste un durcissement serveur recommandé lorsqu'elle est compatible avec le workflow du dépôt. Elle est distincte de la perfection technique du code : un réglage administrateur GitHub que le dépôt ne peut pas modifier lui-même ne doit pas créer un faux rouge permanent.

La source de vérité technique reste le statut `hypersmart/technical-perfect` et les workflows obligatoires du SHA exact. Aucun réglage serveur ne permet de contourner les tests, la sécurité ou la vérité économique.

## 8. Dépendances et supply-chain

- Les GitHub Actions tierces doivent rester pinées sur des SHA immuables.
- Dependabot surveille Python et GitHub Actions.
- La release Windows portable reste la chaîne la plus stricte : wheelhouse exact, hashes, SBOM et provenance.
- Les outils CI critiques sont pinés dans `requirements-ci-tools.txt`.
- Chaque passage supply-chain archive l'environnement Python réellement résolu.

## 9. Documents historiques

Les documents suivants sont **historiques** s'ils contredisent ce fichier ou les contrats exécutables actuels :

- `TASKLIST.md` ;
- `TASKLIST.md.avant_cloture` ;
- `docs/TASKLIST_ACTIVE.md` ;
- `docs/ETAT_ET_FEUILLE_DE_ROUTE.md` ;
- `runtime/research/ALPHA_PROGRESS.md` ;
- anciens rapports sous `docs/archive/`, `runtime/audit/` et répertoires de rapports.

Ils restent utiles pour la traçabilité, mais ne doivent plus être utilisés comme état courant.

## 10. Règle de clôture

Le projet n'est jamais déclaré « parfait » parce qu'un document le dit. Le verdict doit être dérivé du HEAD exact :

1. code et worktree cohérents ;
2. gates CI obligatoires vertes ;
3. sécurité paper/read-only verte ;
4. couverture sans régression ;
5. gouvernance versionnée conforme ;
6. statut `hypersmart/technical-perfect=success` ;
7. aucune preuve économique surclassée artificiellement.
