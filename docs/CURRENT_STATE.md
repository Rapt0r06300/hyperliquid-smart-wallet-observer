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

La gate `.github/workflows/pre-run-321-775.yml` est désormais la gate technique principale : elle revalide les 775 puis impose aussi gouvernance, audit de vulnérabilités, analyse statique, suite complète et cliquet de couverture avant de publier le vert.

## 4. Vérité économique

Aucune cible économique ne doit être déclarée atteinte sans preuve **LIQUIDATABLE_NET**, coûts complets, OOS, forward, placebo et échantillon suffisant.

Au gel de certification du 12/08/2026, les verdicts documentés étaient :

- Copy-Vault : `MORE_DATA` ;
- Lead-Lag : `MORE_DATA` ;
- Cross-Venue v2 : `KILL`.

Les campagnes et infrastructures ajoutées depuis peuvent produire de nouvelles preuves, mais **un résultat exploratoire, train, synthétique ou observé n'est pas automatiquement un PnL prouvé**. La cible +4 USD par famille ne doit être annoncée que par la gate économique canonique.

Un verdict économique `KILL`, `MORE_DATA` ou négatif n'empêche pas le logiciel d'être techniquement parfait : au contraire, refuser honnêtement une stratégie non prouvée fait partie de la qualité attendue.

## 5. PARFAIT / TOUT VERT — définition machine

La certification technique est **indépendante du verdict économique**.

La gate technique principale `.github/workflows/pre-run-321-775.yml` est l'unique autorité qui publie sur le SHA exact :

- `hypersmart/pre-run-775` ;
- `hypersmart/technical-perfect`.

Le workflow redondant `.github/workflows/security-quality.yml` publie son propre contexte distinct :

- `hypersmart/security-quality`.

`security-quality` ne doit jamais écrire `hypersmart/technical-perfect`. Cette séparation interdit qu'un workflow secondaire vert écrase le rouge de la gate 775 complète, ou inversement.

`hypersmart/pre-run-775` et `hypersmart/technical-perfect` ne peuvent être publiés `success` que lorsque :

1. 775/775 et les preuves dérivées sont verts ;
2. la gouvernance versionnée est cohérente ;
3. l'audit `pip-audit` est vert ;
4. Ruff ne détecte aucune erreur structurelle bloquante ;
5. les garde-fous sécurité sont verts ;
6. la suite complète sous `coverage` termine sans rouge ;
7. le cliquet de couverture ne descend pas sous la baseline.

`hypersmart/security-quality` certifie séparément gouvernance, supply-chain et couverture. Il complète la gate principale mais ne peut pas la remplacer.

S'il manque l'un des statuts obligatoires ou s'il est rouge, il est interdit de dire « PARFAIT / TOUT VERT » pour ce SHA.

Cette certification ne prétend jamais que les trois familles gagnent de l'argent. La preuve économique garde ses propres gates et ses propres verdicts.

## 6. Contrat Git : main-only

Le dépôt suit un contrat **main-only** : à la clôture d'un chantier, aucune branche de travail ou branche robot ne doit rester en plus de `main`.

En conséquence la surveillance des dépendances fonctionne **sans Dependabot**, car Dependabot crée obligatoirement des branches de PR. La surveillance est assurée par :

- `pip-audit` bloquant dans les gates ;
- le workflow hebdomadaire `security-quality` ;
- les versions exactes des outils CI dans `requirements-ci-tools.txt` ;
- les Actions tierces pinées par SHA et contrôlées par tests.

Une branche automatique détectée est une anomalie de gouvernance à nettoyer, pas une nouvelle branche de travail autorisée.

## 7. CI et certification

La certification globale attend au minimum :

- `hypersmart-ci` ;
- `hyperlab-ci` ;
- `labo-continu-ci` ;
- `alpha-factory` ;
- `portable-release-windows` ;
- `security-quality` ;
- `hypersmart/security-quality=success` ;
- `hypersmart/pre-run-775=success` ;
- `hypersmart/technical-perfect=success`.

La gate 775 principale est volontairement redondante avec `security-quality` sur les contrôles critiques, mais **chaque workflow publie un contexte de statut distinct**. La redondance ajoute une contre-vérification ; elle ne doit jamais créer deux auteurs concurrents pour le même verdict machine.

## 8. Gouvernance GitHub

La protection native de `main` reste un durcissement serveur recommandé lorsqu'elle est compatible avec le workflow main-only du dépôt. Elle est distincte de la perfection technique du code : un réglage administrateur GitHub que le dépôt ne peut pas modifier lui-même ne doit pas créer un faux rouge permanent.

Aucune protection serveur ne doit conduire à recréer une forêt de branches de travail. Les gates et statuts du SHA exact restent obligatoires pour la certification technique.

## 9. Dépendances et supply-chain

- Les GitHub Actions tierces doivent rester pinées sur des SHA immuables.
- La surveillance se fait **sans Dependabot** pour respecter `main-only`.
- `pip-audit` est bloquant et exécuté dans les certifications.
- La release Windows portable reste la chaîne la plus stricte : wheelhouse exact, hashes, SBOM et provenance.
- Les outils CI critiques sont pinés dans `requirements-ci-tools.txt`.
- Chaque passage supply-chain archive l'environnement Python réellement résolu.

## 10. Documents historiques

Les documents suivants sont **historiques** s'ils contredisent ce fichier ou les contrats exécutables actuels :

- `TASKLIST.md` ;
- `TASKLIST.md.avant_cloture` ;
- `docs/TASKLIST_ACTIVE.md` ;
- `docs/ETAT_ET_FEUILLE_DE_ROUTE.md` ;
- `runtime/research/ALPHA_PROGRESS.md` ;
- anciens rapports sous `docs/archive/`, `runtime/audit/` et répertoires de rapports.

Ils restent utiles pour la traçabilité, mais ne doivent plus être utilisés comme état courant.

## 11. Règle de clôture

Le projet n'est jamais déclaré « parfait » parce qu'un document le dit. Le verdict doit être dérivé du HEAD exact :

1. code et worktree cohérents ;
2. **une seule branche finale : `main`** ;
3. gates CI obligatoires vertes ;
4. sécurité paper/read-only verte ;
5. couverture sans régression ;
6. gouvernance versionnée conforme ;
7. `hypersmart/security-quality=success` ;
8. `hypersmart/pre-run-775=success` ;
9. `hypersmart/technical-perfect=success` ;
10. aucune preuve économique surclassée artificiellement.
