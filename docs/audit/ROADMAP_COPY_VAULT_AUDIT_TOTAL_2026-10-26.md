# CopyVault — chantier d’audit intégral et de fiabilisation

**Version de travail : 2026-10-26** · **Durée planifiée : au moins 5 jours de chantier et 48 h minimum de collecte prospective** · **Statut : proposé, non encore inscrit dans Agiflow**

> Ce plan organise l’exécution; il ne remplace ni `docs/HYPERSMART_CONSTITUTION.md`, ni la spec canonique `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`, ni `SECURITY.md` / `docs/LOIS_MESUREES.md`. La portée reste Copy-Vault uniquement, PAPER / READ-ONLY / FAIL-CLOSED. « Parfait » signifie ici : chemin vérifiable, reproductible, sûr et honnête; aucune feuille de route ne peut garantir une stratégie profitable.

## Objectif final

Auditer, examiner et améliorer chaque fichier suivi qui participe à CopyVault : collecte et normalisation, données SAFE, restauration AlinaSync, contrôle des campagnes, sélection des leaders, signaux, exécution simulée, PnL, replays/backtests/OOS/forward, rapports HTML, lanceurs Windows, GitHub Actions, tests, configuration, dépendances et documentation. Chaque fichier doit recevoir un statut explicite : chemin actif vérifié, dépendance partagée vérifiée, historique/legacy conservé mais inactif, ou défaut à réparer. Chaque liaison entre modules doit avoir une preuve de câblage ou un test.

Les données massives ne seront pas relues manuellement une à une : leur couverture sera établie par inventaires exacts, manifests, tailles, SHA-256, counts/unique counts et contrôles de lecture. Aucun shard ne deviendra une preuve économique par sa seule présence.

## État de départ vérifié

- Dépôt local `main` : `4e9f99b3b5382291668e68bd9dcedf66e65d387e`, avec 31 fichiers de code/tests modifiés et des fichiers runtime locaux à préserver.
- GitHub `main`, vérifié via l’app GitHub et `gh` : `ef22072c5ebbef60bfae379bbe2c82e3d1329428`, 16 commits en avance sur ce HEAD local, sans commits locaux manquants côté distant à la comparaison observée. Le contenu comparé concernait catalogues, reçus, campagnes et plans de collecte. Le SHA distant doit être relu avant toute intégration car les campagnes continuent d’écrire.
- Le `main` distant contient 68 workflows. Les workflows historiques self-hosted examinés sont désactivés (`if: false`); il reste à auditer l’ensemble des workflows, leurs déclencheurs, permissions, dépendances, runners et interactions.
- `collect-copy-vault-v2.yml` est un diagnostic manuel inactif pour la collecte planifiée; la collecte actuelle passe par les campagnes reprenables. Il faut prouver tout le chemin réel plutôt que prendre le nom du workflow pour preuve.
- Actions observées : la régression Windows SAFE restore a échoué sur deux tests de contrat du lanceur Git; le workflow `create-resumable-campaigns` a deux jobs en échec à l’étape de revendication de lease et d’autres jobs restent actifs; `resumable-campaign-controller` est resté longtemps en cours sans mise à jour visible; le watchdog dure plus que sa cadence de 5 min et utilise `cancel-in-progress: true`. Les causes exactes restent à établir.
- Dernière mesure CopyVault disponible : `MORE_DATA`; environ 14 285 fills historiques uniques et 47 834 carnets causaux reconstruits, mais 0 fill live causal admissible. Le replay de secours n’a rejoué que 8 trades sur 4 jours; le résultat d’environ +1,8879 USD/jour est un proxy TRAIN, pas une preuve. Les données invalides/non causales sont exclues, jamais converties en zéros.
- Le rapport antérieur mentionne 15 456 shards SAFE présents/vérifiés; le plan recomptera depuis les index et sources actives. Il distinguera shards présents, admissibles, dédupliqués et réellement utilisés.
- 73 tests ciblés liés au transport de l’audit historique ont passé. La suite complète lancée ensuite n’avait atteint que 11 % et affichait plusieurs marqueurs d’échec; elle n’a pas encore de verdict final.
- Agiflow renvoie `UNAUTHORIZED — This app connection requires reauthentication`; aucun projet ni backlog n’a été modifié. Le présent document est le livrable de lecture provisoire.

## Durée et ordre d’exécution

La durée ci-dessous est un minimum de planification, pas une promesse de terminaison à heure fixe. Les tâches bloquées par l’arrivée de nouvelles données restent ouvertes. La collecte prospective doit couvrir **au moins 48 heures complètes** après validation de son horloge, de ses gaps et de son reçu SAFE; 48 h ne suffisent pas à elles seules pour prouver la rentabilité.

### Jour 1 — protéger l’état, inventorier, auditer GitHub et les entrées de données

1. **CV-001 — Établir le baseline immuable.** Capturer les deux HEAD, branches, différences, fichiers modifiés, chemins ignorés, campagnes en cours et empreintes des fichiers sensibles. Critère : aucun reset, clean, stash, force-push ou écrasement des données; runtime/shards exclus des changements de code.
2. **CV-002 — Réconcilier la divergence local/GitHub sans perte.** Relire `origin/main`, comparer chaque commit et chemin, exécuter le CMD sûr d’abord en dry-run, puis intégrer/pousser seulement après revue des conflits. Critère : histories conservées, données runtime hors push, HEAD local = GitHub `main` après vérification.
3. **CV-003 — Construire l’inventaire déterministe des fichiers.** Générer une liste des fichiers suivis sous runtime, outils, tests, `.github`, configuration et docs CopyVault/shared; associer SHA, propriétaire fonctionnel, statut actif/legacy, appelants, tests et décision. Critère : aucun fichier de ces catégories sans disposition; les fichiers de données sont reliés à leurs manifests plutôt que copiés dans le rapport.
4. **CV-004 — Construire la carte de câblage.** Suivre import/call/config depuis `LANCER_LAB_QUANT_COPY_VAULT.cmd` et les workflows GitHub jusqu’aux collecteurs, stockage, restaurateur, moteur, rapport et tests. Critère : toutes les frontières ont un contrat ou une lacune enregistrée; aucun deuxième runtime/orchestrateur créé.
5. **CV-005 — Auditer les 68 workflows depuis GitHub `main`.** Établir déclencheurs actifs, SHA de code, `runs-on`, permissions, secrets, actions externes, concurrency, timeout, artefacts et écriture de commits. Critère : aucun runner local/self-hosted/tunnel/exécution ou permission excessive atteignable; chaque workflow est classé actif, diagnostic, legacy désactivé ou à corriger.
6. **CV-006 — Diagnostiquer les échecs/actions en cours.** Lire les logs complets des deux échecs de lease, du restore Windows et des longues campagnes; séparer défaut actuel, test obsolète, données manquantes et incident distant. Critère : cause racine reproduite pour chaque échec; aucune relance destructive de campagne.
7. **CV-007 — Établir le catalogue des sources.** Pour chaque endpoint REST/WS et backfill : données, champs natifs, cadence, limites, rétention, pagination, rate limits, reconnect/snapshot, coûts et couverture marché. Critère : sources réellement utilisées prouvées par configuration et tests, les autres explicitement hors chemin.

### Jour 2 — rendre les collecteurs et la preuve SAFE exhaustivement vérifiables

8. **CV-008 — Auditer les fills REST et leur pagination.** Vérifier pagination par temps, bornes inclusives, pages pleines, déduplication, limites et trous historiques. La doc Hyperliquid annonce jusqu’à 2 000 fills par réponse et seulement les 10 000 plus récents via `userFillsByTime`; cela doit être intégré aux garanties de couverture.
9. **CV-009 — Auditer le flux WS fills et ses snapshots.** Distinguer `isSnapshot` des nouveaux événements, dédupliquer REST/WS, réconcilier reconnexions et interruptions. Critère : reprise déterministe sans faux doublons ni trous masqués.
10. **CV-010 — Auditer L2/BBO/trades.** Valider timestamp source et réception, niveaux, snapshot/update, profondeur, prix/taille, BBO, séquence, fraîcheur et conflits. Critère : un carnet périmé, incomplet ou désaligné ne produit jamais de fill simulé.
11. **CV-011 — Auditer horloges et identité native.** Contrôler unités ms/s, timezone, monotonicité, dérive, identités de wallet/coin/Dex, alias et provenance. Critère : aucune conversion silencieuse ni rapprochement ambigu.
12. **CV-012 — Auditer gaps, retries et rate limits.** Simuler 429, timeout, WS coupée, événements retardés/désordonnés et panne en cours d’écriture. Critère : backoff borné, checkpoint de reprise et gaps exposés; aucun succès de couverture fabriqué.
13. **CV-013 — Vérifier le corpus SAFE intégralement.** Recompter à partir des index actifs; vérifier chaque fichier éligible par taille/hash, schema, exact counts et unique counts globaux. Classer fichiers SAFE, non-SAFE, auxiliaires, corrompus et inconnus. Critère : chaque exclusion a motif traçable et aucune donnée non-SAFE n’entre dans les preuves.
14. **CV-014 — Auditer restore/AlinaSync de bout en bout.** Vérifier catalogue → téléchargement autorisé → staging → reçu d’extraction → inventaire → activation atomique; tester liens symboliques, traversal, reprise, interruption et ancien état. Critère : restauration bit à bit, SAFE-only, idempotente, fail-closed, sans toucher aux historiques existants.
15. **CV-015 — Auditer catalogue et index partitionné.** Comparer index, manifests, fichiers physiques, campagnes et caches; reconstruire à blanc et comparer les résultats. Critère : aucune perte de shards lors d’une mise à jour ni double comptage après fusion.
16. **CV-016 — Auditer les reçus de collecte.** Vérifier que les audits backfill structurés, hashes et métriques survivent à l’annotation, la publication, l’écriture du reçu et la relecture par le labo. Critère : régression collecte → publication → receipt → labo; les receipts anciens incomplets restent non reconstructibles et non certifiés.
17. **CV-017 — Lancer et contrôler la collecte prospective.** Démarrer uniquement le workflow GitHub-hosted approuvé, vérifier heartbeats, coverage, SAFE promotion et reçu; préserver les campagnes existantes. Critère : au moins 48 h cohérentes avant examen de la couverture forward, avec gaps/freshness visibles.

### Jour 3 — auditer le chemin CopyVault et le moteur de replay

18. **CV-018 — Définir l’événement canonique CopyVault.** Relier fill leader, OPEN/ADD/REDUCE/CLOSE, inventaire des positions et contexte marché. Critère : les identifiants d’événements sont stables et les transitions impossibles rejetées.
19. **CV-019 — Vérifier la reconstruction des positions leader.** Contrôler ordre chronologique, fills partiels, réductions, clôtures, liquidation et snapshots. Critère : reconstruction indépendante, déterministe, comparée aux données source avec résidu expliqué.
20. **CV-020 — Auditer les leaders et leurs appartenances.** Revoir découverte, identité, entités liées/sybils, survivorship, univers complet, whitelist/blacklist et qualité de backfill. Critère : aucune sélection biaisée par les seuls survivants ou les données futures.
21. **CV-021 — Auditer les signaux et le timing.** Vérifier les seuils, causalité stricte, latence, fenêtre de contexte, prix disponible au moment exact et stale guards. Critère : tests adverses démontrent l’absence de look-ahead.
22. **CV-022 — Auditer les entrées/sorties et le leader-exit.** Vérifier sizing, exposition, add/reduce/close, stop, timeout et sortie sur action leader. Critère : règles pures, explicites et identiques dans replay et backtest.
23. **CV-023 — Auditer la liquidatabilité et la capacité.** Comparer taille simulée à la profondeur exécutable à l’instant causal, spread, impact et limites de capital 200 USD. Critère : capacité insuffisante refuse le trade; jamais d’extrapolation silencieuse.
24. **CV-024 — Vérifier le simulateur d’exécution.** Modéliser bid/ask, frais maker/taker, spread, slippage, profondeur, latence, fills partiels, funding et liquidation si applicable. Critère : tests montrent que le mid-touch ne devient pas automatiquement un fill.
25. **CV-025 — Réconcilier le ledger et le PnL.** Vérifier unités, frais, equity, realised/unrealised PnL, positions ouvertes et conversions de capital. Critère : bilan événementiel réconciliable, invariants arithmétiques et absence de double comptage.
26. **CV-026 — Vérifier parité replay/backtest/runtime.** Injecter mêmes événements et config; comparer décisions, fills, coûts et equity. Critère : résultats identiques ou chaque différence liée à un contrat mesuré.
27. **CV-027 — Vérifier partitions temporelles.** Geler les cutoffs et la source epoch; TRAIN seul ajuste; validation/OOS/forward sont évalués sans retour dans le réglage. Critère : test anti-fuite injectant un gagnant OOS n’influence jamais le choix TRAIN.

### Jour 4 — recherche robuste, gel des améliorations et ergonomie du labo

28. **CV-028 — Définir l’espace de recherche utile.** Inventorier les paramètres autorisés, hypothèses actives/tuées, coûts de calcul et mécanismes causalement testables. Critère : aucune recherche infinie illusoire; recherche reproductible, arrêtable et bornée par données/ressources.
29. **CV-029 — Auditer l’optimisation adaptative.** Vérifier balayage, graines, déduplication, cache, parallélisme et reprise; mesurer temps et mémoire. Critère : chaque configuration est identifiée et rejouable; les erreurs ne sont pas avalées.
30. **CV-030 — Contrôler l’overfit et les comparaisons multiples.** Inclure baseline, contrôles aléatoires, corrections de sélection, stabilité de fenêtres et régimes. Critère : un score TRAIN isolé n’est jamais présenté comme amélioration validée.
31. **CV-031 — Réconcilier les métriques économiques.** Produire net/jour, rendement, drawdown, perte extrême, nombre de trades/jours, capacité, incertitude et capital utilisé. Critère : candidat et champion comparés à coûts, capital, période et qualité égaux.
32. **CV-032 — Geler chaque amélioration admissible.** Archiver hash code/config/data, seeds, périodes, résultats bruts, métriques et provenance pour chaque nouveau palier, même provisoire. Critère : rien n’est écrasé par un score ultérieur; candidat distinct du champion.
33. **CV-033 — Vérifier le gate de promotion.** N’autoriser promotion qu’après critères OOS/forward et risque préenregistrés; conserver champion si candidate échoue. Critère : aucun résultat n’est forcé en `PROVEN`; statuts `PROVEN/PROMISING/MORE_DATA/UNMEASURABLE/REJECTED` justifiés.
34. **CV-034 — Auditer le lanceur exact `LANCER_LAB_QUANT_COPY_VAULT.cmd`.** Suivre sa chaîne réelle, son environnement Python, son code retour, les erreurs préalables et l’ouverture HTML. Critère : le CMD lance le labo/replay CopyVault, pas une simple suite de tests ou un autre collecteur.
35. **CV-035 — Rendre la boucle longue observable et reprenable.** Valider que la recherche tourne jusqu’à Ctrl+C, publie régulièrement progression/checkpoint, reprend sans dupliquer, et s’arrête proprement. Critère : aucun arrêt silencieux après quelques secondes; chaque phase explique ce qu’elle fait.
36. **CV-036 — Simplifier et vérifier le rapport HTML en direct.** Afficher état, corpus utilisé, métriques, baseline approximative avec incertitude, candidat, gain comparable, exclusions, durée, erreurs et historique gelé. Critère : « non mesurable » plutôt que zéro inventé; HTML lisible localement sans serveur nécessaire.
37. **CV-037 — Rendre les journaux compréhensibles.** Relier chaque ligne console au run ID, étape, compteur, durée, avance et rapport; garder logs techniques séparés. Critère : une personne non développeuse identifie progression, attente de données et cause d’arrêt.

### Jour 5 et suite — GitHub, sécurité, robustesse, preuve et fermeture honnête

38. **CV-038 — Corriger les contrats Windows/Git Sync.** Aligner les tests du push et restore sur l’interface effectivement retenue; vérifier forwarding d’arguments, dry-run, erreurs, conflits et pause CMD. Critère : aucune force/reset/clean/stash; aucune donnée runtime envoyée; erreur distante propagée.
39. **CV-039 — Réparer et durcir les leases de campagne.** Reproduire les deux jobs rouges; contrôler clé d’idempotence, epoch, propriétaire, expiry, clock, retries et race de claims. Critère : un seul propriétaire actif par shard, reprise sûre après expiration.
40. **CV-040 — Corriger la cadence du watchdog.** Comparer sa durée observée à son cron de 5 min et évaluer `cancel-in-progress: true`. Critère : les campagnes et reçus ne peuvent pas être interrompus par un tick suivant; heartbeats frais et absence de split-brain démontrées.
41. **CV-041 — Vérifier le budget et la visibilité des campagnes longues.** Auditer timeout, heartbeat, logs, statut de job, partitions et récupération des jobs en retard. Critère : aucun `in_progress` silencieux sans deadline, reçu ou signal explicite de blocage.
42. **CV-042 — Audit de sécurité statique/dynamique.** Scanner voies d’ordre, clés, endpoints execution, permissions, secrets, logs, dépendances/actions et runners. Critère : PAPER/READ-ONLY démontré à chaque entrée; tous self-hosted restent inatteignables; actions épinglées par SHA complet.
43. **CV-043 — Tests de défaillance et propriétés.** Tester corrompu, tronqué, symlink, répétition, ordre inversé, panne à chaque écriture, 429/timeout, kill/reprise et concurrence. Critère : échec sûr, reprise idempotente et preuve d’absence de faux PnL.
44. **CV-044 — Tests différentiels et déterminisme.** Rejouer corpus/config identiques sur process isolés, machines/versions supportées et ordre d’index différent. Critère : manifest, signaux, trades et ledger reproductibles.
45. **CV-045 — Profil de performance.** Mesurer temps par étape, débit shards/fills/books, CPU, mémoire, I/O, cache et coûts Actions. Critère : optimiser seulement après mesure et préserver la parité de résultat.
46. **CV-046 — Vérifier dépendances, packaging Windows et environnement vierge.** Installer depuis verrou, contrôler versions Python, chemins avec espaces/accents, droits et erreurs. Critère : lancement sur clone propre et diagnostic explicite si prérequis absent.
47. **CV-047 — Rejouer la suite complète et les matrices pertinentes.** Unitaires, intégration, CMD, reprise SAFE, workflow hosted, sécurité, replay et rapport. Critère : résultats exact-SHA, logs complets, aucun test pertinent omis; échecs préexistants séparés des régressions.
48. **CV-048 — Faire une revue adversariale du diff et des historiques.** Comparer baseline, tous changements locaux, commits distants intégrés et artefacts générés. Critère : aucun changement utilisateur ou shard perdu; chaque suppression justifiée.
49. **CV-049 — Produire le dossier de preuves.** Joindre inventaire fichiers, graphe de câblage, reçu data, rapports tests/Actions, rapport de replay et résumé des écarts. Critère : chaque déclaration renvoie à une preuve, un SHA et un run.
50. **CV-050 — Évaluer l’économie sans biais.** Si la couverture causale/forward reste insuffisante, garder `MORE_DATA`; si les données permettent l’évaluation, calculer incertitude, coût net et risque hors-échantillon. Critère : jamais de promesse ni de promotion motivée uniquement par un grand nombre de scénarios.
51. **CV-051 — Synchroniser Agiflow.** Après réauthentification, choisir le projet existant, lire les statuts et doublons, puis enregistrer les tâches en Planning avec critères d’acceptation et dépendances. Critère : un seul backlog traçable; aucune tâche dupliquée ou classée prête avant grooming.
52. **CV-052 — Clôture de l’audit.** Relire HEAD local et GitHub, vérifier le diff, les runs/actions exacts, les SAFE manifests et les statuts économiques. Critère : annoncer séparément travaux techniques terminés, preuves économiques disponibles et blocages externes; `DONE` seulement selon la spec canonique.

## Portes d’admission / arrêt

- Une donnée absente, stale, non causale, non vérifiée ou contradictoire bloque le calcul qui en dépend; elle est affichée comme telle, jamais remplacée par zéro ou un timestamp inventé.
- TRAIN sert à la recherche; validation/OOS/forward demeurent held-out jusqu’au gel. Une candidate ne remplace pas le champion sans comparaison indépendante et reproductible.
- Des milliers de shards ou de configurations ne remplacent pas une couverture temporelle, un alignement fill/L2, des coûts réalistes et un échantillon indépendant.
- Toute simulation reste `PAPER / READ-ONLY`; aucune commande, clé, SDK ou permission de workflow ne doit rendre une exécution réelle atteignable.
- À la fin des 48 h prospectives, si les observations sont toujours insuffisantes, la sortie correcte reste `MORE_DATA`, avec preuve des gaps et prochaine action de collecte.

## Sources primaires à prendre en compte

- [Hyperliquid — Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint) : pagination/limite des fills et snapshot L2.
- [Hyperliquid — WebSocket subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) : snapshots `isSnapshot`, fills stream, `l2Book`, trades et BBO.
- [GitHub — Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use) : privilège minimal, secrets et épinglage d’actions.
- [GitHub — Workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency) : effets de `cancel-in-progress`, files pending et groupes de concurrence.

## État Agiflow

La connexion Agiflow a répondu `UNAUTHORIZED` et demande une réauthentification. Le plan ci-dessus est prêt à être transformé en tâches Agiflow, mais n’y a pas été écrit. Une fois la connexion rétablie, il faudra d’abord lire le projet, les statuts et les tâches existantes pour éviter les doublons, puis créer les tâches dans `Planning`.
