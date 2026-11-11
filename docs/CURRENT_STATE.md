# Alina SmartFlow — état courant autoritatif

Dernière mise à jour : **2026-11-11**.

L'ancre **`c40263c8a5188fb6c39d5a92b149635243c6155e`** est un audit historique du 2026-09-10, pas une certification du HEAD actuel. Le scope Copy-Vault-only a été recontrôlé dans le checkout local au HEAD de base **`755441d3b442c9c981d2876d07bf71f9459e1ad5`** ; la copie de travail est modifiée et cette vérification ciblée ne vaut pas validation globale.

Ce document est la **source de vérité lisible actuelle** pour l'état du projet. Il ne remplace pas les contrats exécutables : en cas de divergence, le code, les tests, les gates CI et les registres machine gagnent toujours.

## 0. Nouveautés (2026-11-11) — reprise de mission, point de reprise

Base : HEAD local `391efb93b1a3eab60b9eb8119dce491807eac0fa` (GitHub en avance de 3 commits de reçus
cloud, sans code). Modifications locales non commitées, non poussées. Tout est PAPER / lecture seule.

**Défauts mesurés puis corrigés (chacun avec un test de régression) :**

- **Labo principal : recherche à vide.** Le run `20261110T131434661405Z` a duré 6 h 33 et essayé
  133 676 jeux de paramètres sur une entrée vide. Deux causes : (1) `tools/pipeline_copie_reel.py`
  n'admettait que la source `LIVE_WS` alors que les 5 245 840 fills live du corpus sont `LIVE_POLL`
  (causaux, horloge de réception valide) ; (2) la découpe TRAIN / VALIDATION / OOS portait sur tous
  les jours de signal, dont 768 jours d'historique sans carnet : TRAIN était structurellement vide.
  Corrections : point unique `is_causal_live_source` appliqué partout ; découpe sur les jours
  **évaluables** (`backtesting/copy_vault_signal_alignment.py`) ; arrêt immédiat
  `INSUFFICIENT_EVALUABLE_SIGNAL_DAYS` sans aucun essai ; champ natif `startPosition` pris en compte
  (une fermeture de short n'est plus lue comme une ouverture) ; ruban live lu en flux ; cycles
  reconstruits une seule fois par exécution ; un jour ne porte la découpe que s'il compte au moins
  10 signaux évaluables (quelques signaux isolés d'octobre suffisaient sinon à franchir le minimum
  de jours, avec un TRAIN quasi vide) ; l'exploration « overshoot » n'est plus lancée avant ce
  contrôle. **Mesure après correction, même workspace : verdict en 6 min 43 s** (`MORE_DATA`,
  `INSUFFICIENT_EVALUABLE_SIGNAL_DAYS`, 0 essai), 5 245 840 fills causaux → 2 347 711 entrées →
  698 071 signaux, dont **77 210 évaluables (11 %)** sur 5 jours denses pour 6 requis. Mémoire
  résidente : 13,6 Go.
- **Limite de données n° 1 révélée par cette mesure :** 89 % des signaux des leaders n'ont aucun
  carnet L2 reçu dans les 30 s précédentes : leur coût d'exécution n'est pas mesurable. La
  couverture L2 des coins réellement tradés par les leaders (dex HIP-3 compris) prime sur tout
  nouveau flux.
- **Lanes cloud L2 et marché : symboles mis en majuscules.** `kPEPE`, `kSHIB`, `kBONK`, `kFLOKI`
  devenaient `KPEPE`… (inconnus de l'API) : aucun carnet ni trade collecté pour ces coins. Identité
  native conservée dans `tools/collecter_l2_lane.py` et `tools/collecter_market_lane.py`.
- **Frais dupliqués.** Le détecteur de signaux de copie appliquait 4,0 bps au lieu de 4,5 ; le modèle
  d'exécution PAPER et le plancher de risque recopiaient la valeur. Tous lisent maintenant
  `fees/hyperliquid_fees.py` ; parité vérifiée par `tests/test_frais_source_unique.py`.
- **Porte économique obsolète.** Le repère +5 USD restait une porte dans la preuve PnL par module, la
  certification finale, la certification journalière, le job de famille et la mémoire économique.
  Conformément à la spec canonique : certification = toutes les portes de qualité + net réconcilié
  strictement positif ; le repère est rapporté à part (`reference_target_reached`,
  `reference_target_is_gate=false`). Une preuve héritée sans `certification_policy` reste jugée avec
  l'ancien seuil.

**Nouvelle chaîne collecte → certification → labo :** les courbes valeur / PnL / volume publiées par
`vaultDetails` (des mois d'historique par vault) étaient téléchargées à chaque passe puis jetées.
Elles sont conservées (`collection/vault_portfolio_history.py`, ruban
`runtime/data/vault_portfolio_history.jsonl`), certifiées (famille `vault_portfolio`) et consommées
par `tools/etude_copiabilite.py --persistance` (`backtesting/copy_vault_persistence.py`) : le
classement passé d'un leader prédit-il son rendement suivant, net de la borne haute du coût de
réplication ? Hypothèse `copy_vault_leader_skill_persistence` : **UNMEASURABLE** tant qu'une passe
de collecte n'a pas eu lieu (aucune donnée réelle n'a été collectée pendant cette session).

**Validation exécutée le 2026-11-11 (poste local, Python 3.11, par tranches de 150 fichiers) :**
suite complète 17 645 réussis / 4 échecs / 68 ignorés. Les 4 échecs : trois provenaient d'une
famille ajoutée au certificateur avant son entrée au registre de couverture (corrigé), un d'un test
qui relisait un fichier UTF-8 avec l'encodage du poste (corrigé) ; rejoués verts. Régression ciblée
sur tous les tests touchant aux modules modifiés : 1 293 réussis. Les reçus locaux de la roadmap,
périmés par ces modifications (124), sont revalidés par `tools/revalider_receipts.py` : il rejoue
les tests de chaque reçu puis AJOUTE un reçu rafraîchi ou `REVALIDATION_FAILED`, sans réécrire le
registre (l'ancien `tools/regenerer_receipts.py` rafraîchit les empreintes sans rejouer : à éviter).

**Seconde séquence du 2026-11-11 (lectures ponctuelles autorisées, rien poussé, rien commité) :**

- Faits vérifiés auprès de l'API officielle : identifiants sensibles à la casse (`xyz:XYZ100`, `kPEPE` ;
  `XYZ:XYZ100` et `KPEPE` refusés) ; `l2Book`, `bbo`, `trades` fonctionnent sur les dex HIP-3 ; **un seul
  abonnement invalide fait fermer toute la connexion WebSocket** ; le message `clearinghouseState` du
  WebSocket imbrique l'état (les lanes « contexte » n'avaient jamais écrit une position) ; le PnL des
  fenêtres jour/semaine/mois de `vaultDetails` repart de 0 (recalé sur le cumul, schéma v2).
- Collecte automatique par `LANCER_COLLECTEURS_COPY_VAULT.cmd` : `vault-collector` écrit l'historique de
  portefeuille, balaye l'univers élargi (2 333 vaults dont les fermés, 12 par passe) et relève les
  portefeuilles complets des leaders lents (dex principal + `xyz`) ; nouveau collecteur `l2-leaders`
  (15e, carnets L2 + BBO de 180 coins dont 60 HIP-3, liste régénérée par `tools/generer_coins_lanes.py`,
  chaque nom vérifié par `collection/univers_perps.py`). Essais bornés réels : 180/180 coins servis.
- AlinaSync rapatrie aussi les lanes marché et contexte (`tools/telecharger_lanes_certifiees_github.py`).
- Moteur / labo : parité d'exécution taker vérifiée (`tests/test_parite_execution_labo_moteur.py`) ;
  ordre minimal de 10 USD imposé aux dimensionneurs ; simulateur `copy_vault_replication_paper.py`
  (350 USD, frais, écart, funding, ordre minimal) et modèle `copy_vault_leader_model.py`.
- Balayage complet terminé : 2 333 vaults (1 859 fermés, 474 ouverts), 556 247 points, 0 échec ;
  certifié (164 911 lignes gardées, 0 écartée).
- Persistance sur cet univers élargi (PnL recalé, 86 dates hebdomadaires, 28 configurations) :
  **`MORE_DATA`**. Analyse primaire : corrélation de rang −0,002 [−0,096 ; +0,105] ; meilleur quantile
  moins « copier tout le monde » −13,59 bps/jour [−31,02 ; +1,48], placebo p = 0,976. Leaders lents
  (789 vaults) : −17,24 bps/jour [−46,53 ; +13,42]. Modèle de sélection appris en marche avant :
  corrélation −0,005 [−0,064 ; +0,055]. Lecture : aucun signe que le classement passé d'un vault
  prédise son rendement suivant ; les estimations penchent du côté négatif. Les deux configurations
  à p < 0,05 (sur 27) ne passent pas la correction de multiplicité (seuil 0,0018).
  Rapport : `runtime/reports/copy_vault_quant_lab/copiabilite/20261111T161309284940Z-persistance/`.
- Réplication 350 USD = `MORE_DATA` : aucune journée où le leader est observé ≥ 90 % du temps.
- Magasin de ticks : 281 046 shards vérifiés (27,17 Go), 0 anomalie, état PARTIEL (2 394 dossiers
  restants ; la vérification reprend là où elle s'est arrêtée).
- POUSSER : aperçu à blanc corrigé (`git diff` n'accepte pas `--pathspec-from-file`).

**À faire en premier à la reprise :** (1) rejouer la suite complète et
`tools/revalider_receipts.py` (seuls des tests ciblés ont tourné depuis les dernières modifications) ;
(2) relancer le Certificateur seul : sa vérification du magasin de ticks a échoué une fois
(`database is locked`) parce qu'une vérification des ticks tournait en même temps ; (3) pousser
(décision de l'utilisateur) pour que les lanes cloud prennent la liste de 180 coins et les corrections.
Ne pas lancer `git status` sur ce dépôt sans borne de temps : il dépasse 10 minutes.

**Reste ouvert (liste antérieure, points 1 à 3 traités ci-dessus) :**

1. Une passe `tools/collecter_vaults.py --une-fois` (lecture seule), puis `Certificateur Coffre
   Fort.cmd`, puis `LANCER_LAB_QUANT_COPY_VAULT.cmd copiabilite` → premier verdict de persistance.
2. 61 % du notionnel des leaders porte sur des coins HIP-3 (`xyz:`) sans carnet collecté ;
   `config/copy_vault_coins.json` n'en contient aucun et n'a pas de générateur. À ajouter aux lanes
   seulement après validation en direct du nom d'abonnement `l2Book`.
3. Univers de vaults suivis = survivants (ouverts, TVL ≥ 100 k USD, ≥ 45 jours) : conserver aussi les
   vaults fermés de la liste publique pour mesurer le biais de survie.
4. Le labo ne retire pas encore les robots HFT ni les adresses clones de ses signaux, alors que le
   moteur les refuse : parité d'univers à établir avant toute lecture statistique (pseudo-réplication).
5. Non traités dans cette session : parité complète labo ↔ moteur sur un même jeu d'événements,
   reliquat de vérification du magasin de ticks, durcissement d'AlinaSync et de POUSSER.

## 0 bis. Nouveautés (2026-11-08)

- **Lanes de collecte multi-IP** (franchissent les plafonds par IP d'Hyperliquid) : `userfills-live-lanes.yml`
  (fills `LIVE_WS`), `copy-vault-poll-lanes.yml` (fills `LIVE_POLL`), `copy-vault-l2-lanes.yml` (carnets L2 +
  BBO). Leaders/coins commitables : `config/copy_vault_leaders.json`, `config/copy_vault_coins.json`.
  Rapatriement + fusion automatiques dans `ALINA_SYNC_COMPLETE.cmd` (dédup + fraîcheur).
- **Coffre-fort « données certifiées » 2 tiers** (`Certificateur Coffre Fort.cmd` +
  `src/hl_observer/datasets/coffre_certifie.py`) : tier LOCAL (certifié-local : répare/salvage/quarantaine)
  + tier SAFE-cloud référencé. Le labo charge les deux (`_charger_tier_local` dans `materialize_safe_workspace`,
  SHA-256 revérifié). **Mesuré** : fills causaux chargés `0 → 88 090`, carnets `50 170 → 433 920`.
- **Frontière vérifiée** : le moteur de décision/preuve du labo est **SAFE-provenance-bound** ; le tier
  LOCAL nourrit la recherche exploratoire mais ne peut jamais être « prouvé » (pas de fausse certification).
  La rentabilité prouvée exige du SAFE-cloud frais (que les lanes alimentent).
- **`POUSSER-GITHUB-FORCE.cmd` : défaut = code seul** (push rapide, plus de téléchargement SAFE de 153 Go) ;
  `--full` pour l'ancien comportement complet.

## 1. Périmètre économique actif

Le périmètre canonique est défini par `src/hl_observer/strategies/active_scope.py`.

Famille économique paper active au niveau du runtime :

- `copy_vault` uniquement.

`lead_lag`, `cross_venue_dislocation`, l'arbitrage et les autres familles sont en pause.
Ils ne doivent être exécutés ni par le moteur principal AlinaSmartFlow, ni par la simulation
UI, ni par le laboratoire, les backtests ou les replays tant que ce périmètre temporaire
Copy-Vault-only reste en vigueur.

Toute réactivation exige un changement explicite du scope canonique et des tests associés.

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

### 2.1 Contrat obligatoire avant tout futur trading réel

Le processus doit rester actif en continu pour observer et recalculer les opportunités, mais l'ouverture d'une position reste fail-closed lorsqu'aucun avantage net prouvé ne couvre les coûts et le risque. Le moteur d'exécution réel devra, avant son activation :

- lire le solde et la marge réellement disponibles, sans capital codé en dur, y compris pour un compte initial de 50 USD ;
- dimensionner chaque ordre en fraction du capital et de la liquidité exécutable observée ;
- conserver une réserve de marge et plafonner l'exposition, la perte par trade, la perte journalière et le drawdown cumulé ;
- bloquer uniquement les nouvelles prises de position lorsque ces limites sont atteintes, tout en continuant le scan et la réévaluation des signaux ;
- refuser un ordre si la taille minimale, les frais, le spread, le slippage ou le risque de liquidation empêchent une espérance nette positive dans les limites fixées ;
- ne jamais présenter la conservation du capital ou un rendement quotidien comme garanti.

Ces exigences ne lèvent pas le verrou paper/read-only actuel et ne constituent pas une autorisation de trading réel.

## 3. Chantier des 775 optimisations pré-run

Le registre canonique des **775 optimisations pré-run est scellé 775/775**. Il n'est pas permis de renuméroter, supprimer ou recycler les identifiants 1–775. Toute découverte réellement nouvelle commence à 776+.

La gate `.github/workflows/pre-run-321-775.yml` est désormais la gate technique principale : elle revalide les 775 puis impose aussi gouvernance, audit de vulnérabilités, analyse statique, suite complète et cliquet de couverture avant de publier le vert.

### 3.1 Roadmap technique cumulative V5 / 776+

La roadmap AgiFlow cumulative qui ré-audite et implémente le patrimoine `HYPERSMART_MASTER_ROADMAP_CODING_AGENTS_V5_2026-08-30.md` et les améliorations 776+ est distincte du statut historique `pre-run-775`.

Pour cette roadmap technique :

- un macro-lot est `Done` lorsque ses exigences techniques sont implémentées ou explicitement classées (`déjà-implémenté`, `corrigé`, `SUPERSEDED`, `DUPLICATE`, `KILLED`, `HISTORICAL`, `REJECTED` ou `BLOCKED`) avec preuves adaptées ;
- une stratégie peut rester `KILL`, `MORE_DATA`, négative ou non certifiée économiquement sans empêcher la fermeture d'un lot technique correctement réalisé ;
- **Aucune cible de profit ou PnL positif n'est un critère de Done de cette roadmap technique** ;
- les coûts, l'OOS, le forward, la liquidatabilité, la causalité et les autres invariants scientifiques restent obligatoires lorsqu'un lot touche ces surfaces ;
- aucune idée V5/776+ ne peut disparaître silencieusement : toute exigence doit garder une disposition traçable.

Cette séparation ne modifie pas la mission économique du produit : elle empêche seulement de confondre la complétion d'ingénierie avec la réussite d'une stratégie de trading.

## 4. Vérité économique

Aucune cible économique ne doit être déclarée atteinte sans preuve **LIQUIDATABLE_NET**, coûts complets, OOS, forward, placebo et échantillon suffisant.

Au gel de certification du 12/08/2026, sous un ancien périmètre multi-familles, les verdicts historiques documentés étaient :

- Copy-Vault : `MORE_DATA` ;
- Lead-Lag : `MORE_DATA` ;
- Cross-Venue v2 : `KILL`.

Ces verdicts ne décrivent pas l'état économique actuel. L'objectif économique actif est **l'amélioration continue de Copy-Vault**, avec un repère quantitatif de **+5 USD net/jour sur 350 USD paper**, sans en faire une gate automatique ou une promesse. Chaque gain NET mesuré est gelé comme expérience reproductible ; seuls les champions validés par OOS et forward post-freeze disjoints, coûts complets, causalité et gates de risque sont promouvables. La recherche reprend après chaque gel.
Un résultat exploratoire, TRAIN, synthétique ou simplement observé n'est pas
une preuve de PnL ; le statut actuel doit venir du dernier rapport valide.
Les anciennes références à **+5 USD net/jour sur 200 USD paper** sont historiques ;
le repère opérationnel actuel est 350 USD et ne constitue ni une gate automatique
ni une condition de clôture.

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

Cette certification technique ne prétend jamais que Copy-Vault gagne de
l'argent. La preuve économique garde ses propres gates et son propre verdict.

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

- `docs/archive/root-history/TASKLIST.md` ;
- `docs/archive/root-history/TASKLIST.md.avant_cloture` ;
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
