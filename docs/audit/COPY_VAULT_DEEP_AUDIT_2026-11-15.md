# Audit Copy-Vault du 15 novembre 2026

Journal de constats et de correctifs, sans autorité normative. La constitution et la spec canonique restent les seules règles du projet. Périmètre : Copy-Vault sur 350 USD paper, lecture seule, portes fermées si la preuve manque. Le souhait de l'opérateur est **10 USD nets par jour prouvés** ; le repère de recherche inscrit dans la spec reste +5 USD/jour et ne constitue pas une porte automatique. Aucun de ces montants n'est actuellement prouvé.

## État mesuré

1. Le dernier rapport local du labo disponible pour cet audit est `runtime/reports/copy_vault_quant_lab/20261112T160515843663Z/resultat.json`, HEAD `bb41b323af86bd870ec6460afbaa05498424bd34`. Il vérifie 15 256 shards et 4 043 102 fills uniques, mais exécute **0 configuration actuelle**, ne gèle aucun candidat et conclut `MORE_DATA` / `TRAIN_NOT_EXECUTABLE`. Les 81 920 scénarios historiques reposent sur un autre jeu de 8 trades TRAIN ; ils ne constituent ni OOS ni forward de la politique actuelle.
2. Sur 98 138 signaux TRAIN, 0 trade est exécutable pour les horizons testés. Principaux motifs, qui peuvent se chevaucher : référence L2 absente ou périmée 77 008 ; identité de connexion L2 incomplète 14 878 ; sortie L2 absente ou périmée 8 211 ; carnet absent pour le coin 4 355 ; entrée L2 absente ou périmée 1 241 ; signal forward non causal 104. Le rapport cite BTC, HYPE, ZEC, ETH, kPEPE, XRP, SOL et SUI parmi les marchés prioritaires pour comprendre ces refus. Il faut refaire la mesure sur les données postérieures à la mise en route du compagnon causal avant de conclure que l'alignement est réparé.
3. Le reçu `catalog/ANALYSIS_SCOREBOARD_RECEIPT.json` est historique : trois familles dites actives, capital 100 USD, ancien code SHA et 0 position Copy-Vault clôturée. Il était encore identique sur `origin/main` au HEAD `48574b9` du 16 novembre. Le registre `catalog/ECONOMIC_IMPROVEMENT_LEDGER.json` n'a aucun champion Copy-Vault ; son dernier statut est `NON_MESURABLE`. Le rapport distant `docs/alina-closure-report.json` annonce lui-même `copy_vault_status=UNMEASURABLE`, `oos_status=MORE_DATA` et `forward_status=MORE_DATA`. Le `PASS` de `docs/canonical-spec-verification.json` n'est pas une preuve économique. Le nouveau contrôle de scope rejette explicitement le vieux scoreboard.
4. La collecte locale était active avec 18 collecteurs et une lease valide. `userfills-live` émettait le protocole `copy_vault_unbound_ws_l2_v1`, mais aucun `copy-vault-checkpoints` ne tournait. Le compagnon a été attaché à la même lease, sans arrêt des autres collecteurs. Son heartbeat a ensuite annoncé le protocole `copy_vault_checkpoint_companion_v3_native_symbol_identity_for_copy_vault_executable_walk_forward_v8_explicit_l2_gap_identity`. Cela ouvre une **nouvelle époque propre** ; les fills antérieurs ne deviennent pas causaux rétroactivement. Le 16 novembre à 12:55 UTC, le superviseur affichait `ACTIVE`, 20 processus et `causal_protocol_status=OK`. À 13:22 UTC, le fichier d'état du compagnon venait encore d'être mis à jour et comptait 25 875 checkpoints, 43 expirations et une rotation d'entrée. `ACTIVE` décrit la vie des processus, pas la qualité de la preuve.
5. Une certification locale de coffre a terminé sans erreur (`20261115T181617Z_f8a052ab`, 988 004 entrées examinées, 715 980 déposées, 44 287 quarantaines, 227 737 doublons). Les 44 287 rejets sont `timestamp_futur` ou `observed_at_ms_futur`. Le lot figeait son horloge à 18:16:17 UTC alors que les sources vivantes grossissaient pendant le scan : les lignes arrivées après l'ouverture du lot étaient comparées à cette ancienne heure. Cette cause est confirmée par des échantillons, mais chaque ligne doit encore être revérifiée avant récupération. Le niveau `LOCAL` n'est pas la preuve SAFE/OOS/forward ni une preuve comptable.
6. Le HEAD local de départ était `b206107b04bd4a332347f09f06fbc8dccc8b8d3b`. Le 16 novembre vers 13:15 UTC, `main` distant était `48574b92035761d758ee3196f50ae108f0c8c0a1`, 139 commits plus loin. La comparaison ciblée `src/`, `tools/`, `tests/`, `docs/` ne montre aucun changement de code : cinq reçus JSON dans `docs/` ont changé, avec les reçus et campagnes de `catalog/`. Ces publications ne ferment aucune preuve économique par elles-mêmes.

## Correctifs réalisés localement pendant cet audit

- Le watchdog exige désormais `copy-vault-checkpoints` avec `userfills-live`, y compris lorsqu'une liste persistée ou fournie l'omettait. Il accepte qu'un collecteur supplémentaire soit attaché à la lease. Le processus déjà lancé garde son ancien code en mémoire.
- Le collecteur `paper-carry-inverse` a été retiré du registre de lancement et son point d'entrée refuse `DISABLED_BY_SCOPE:carry`, même avec une variable d'environnement favorable. Son code historique reste présent.
- Le marquage des positions UI refuse prix non finis, snapshots périmés ou futurs et un BBO d'un autre dossier de travail. Le writer économique reçoit maintenant le même `current_ms` que la route de statut.
- L'évaluateur économique sépare le repère chiffré des portes de qualité et du net positif. Une preuve incomplète ou invalide reste refusée ; un net strictement positif de qualité n'est plus rejeté seulement parce que +5 USD/jour manque. L'atteinte journalière est rapportée à part et ne peut être affirmée que si le total exact des jours est réconcilié au pool de trades, sans jour incomplet exclu. Le contrat de rapport quotidien a une nouvelle version ; les vieux reçus ne doivent pas être requalifiés silencieusement.
- Les validateurs de scoreboard et les rapports de clôture exigent uniquement Copy-Vault et 350 USD. Lead-Lag et Cross-Venue sont affichés `DISABLED_BY_SCOPE`, sans leur demander de certificat économique.
- L'exécuteur refuse explicitement un checkpoint `REFERENCE` dont l'heure de réception locale est postérieure au signal, y compris lorsqu'il est appelé directement sans le chargeur de carnets. Le chargeur de production utilisait déjà cette heure de réception comme `ts_ms` ; le nouveau motif est `REFERENCE_NOT_AVAILABLE_AT_SIGNAL`.
- En mode exploratoire uniquement, cette référence tardive ne masque plus un triplet de carnets WS continus pré-signal/entrée/sortie avec identité de connexion et époque de gap cohérentes. Le trade porte `CONTINUOUS_CAUSAL_BOOK`, sans writer de checkpoints exacts. Le mode certifiable refuse toujours la référence tardive : ce repli peut aider à mesurer TRAIN, mais ne remplace pas une preuve forward liée aux checkpoints.
- Le watchdog publiera séparément `causal_evidence_status` et le nombre de gaps du heartbeat vérifié, sans confondre `ACTIVE` avec une preuve exploitable. Ce changement attend le prochain démarrage du processus watchdog déjà en cours.
- Le scelleur utilise désormais l'heure de capture **de chaque source** pour tester les timestamps futurs ; `--now-ms` reste fixe pour les tests. Son hash et sa lecture portent sur le même préfixe figé. Une réécriture/rotation de ce préfixe pendant la lecture provoque un échec visible avant publication du shard ou avancement du curseur ; un simple append reste autorisé. Les manifestes indiquent `source_cutoff_ms`. Les motifs complets sont conservés par fichier et agrégés au niveau du lot.
- Le reçu diagnostique `coverage_receipt` du compagnon refuse désormais une couverture `PROVEN` en présence de checkpoints expirés, de débordement de file, de rotation/reconnexion ou de compteur manquant/invalide. Une rotation et son compteur de backfill bloqué sont comptés comme un seul incident. Ce reçu ne répare pas les gaps du run actif ni le problème du carnet de référence post-signal.
- L'exécuteur en mode certifiable exige désormais un `received_at_ms` entier explicite et égal au `ts_ms` de sélection pour chacun des trois checkpoints exacts. Le chargeur normal fournit déjà ce contrat ; un appel direct ne peut plus faire passer une heure de réception absente ou contradictoire pour une observation prouvée.

## Travaux encore nécessaires, par ordre causal

### P0 — Obtenir un échantillon réellement exécutable

Sur les nouveaux événements, suivre le tunnel `fill WS non snapshot -> identité native -> signal reçu -> livre de référence reçu avant le signal -> entrée au délai déclaré -> sortie observée -> coûts complets`. Publier les comptes uniques et les motifs de refus à chaque étape, par coin, leader, jour, protocole et époque de connexion. Ne jamais élargir une fenêtre de fraîcheur pour « sauver » un signal. Comparer la nouvelle époque de checkpoints aux 77 008 refus `STALE_OR_MISSING_REFERENCE_BOOK` et 14 878 refus d'identité, puis isoler les coins qui ont des fills mais aucun carnet. Les sorties absentes restent censurées ; elles ne valent ni PnL zéro ni clôture implicite.

**Bloqueur de conception confirmé le 16 novembre.** `CopyVaultCheckpointTail` ne programme `REFERENCE` qu'après lecture du fill ; sa requête REST est donc reçue après le signal. Dans les 4 000 dernières lignes du tape inspectées, les 51 références REST avaient toutes une réception post-signal (320 à 1 527 ms). Le chargeur les date correctement par leur réception et l'exécuteur les refuse. Ce n'est pas une fenêtre à élargir : il faut binder au métaordre un carnet **déjà reçu avant le signal**. Une inspection de 10 000 lignes récentes a trouvé un carnet WS continu antérieur de même coin dans les 30 s pour 192 des 207 références échantillonnées (âge médian 5 358 ms) ; ce contrôle est exploratoire, pas une preuve de jointure complète. La solution doit copier ou lier ce carnet observé avec hash, offset, identité de connexion, époque de gap et run du writer, puis vérifier le lien au chargement. Les checkpoints ENTRY/EXIT peuvent continuer d'utiliser les observations post-cibles. Ne pas promouvoir les références REST actuelles comme pré-signal.

**Second bloqueur confirmé.** `copy_vault_book_loader.py` exige `collector_gap_count == 0` pour valider l'époque propre entière. La campagne active compte déjà 43 expirations et une rotation ; ainsi tous les checkpoints de ce run sont actuellement non certifiables, même ceux sans gap local. La spec autorise des gaps globaux, mais exige leur quarantaine et des intervalles `EXECUTION_REPLAY_SAFE` sans gap applicable. Il faut segmenter les intervalles ou renouveler l'époque propre sur rupture, conserver la preuve des trous et recalculer le dénominateur de couverture. Aucune remise à zéro de compteur ne peut effacer un gap historique. À ce stade, une relance du seul compagnon sans protocole de segmentation vérifié ne répare pas les 25 875 lignes déjà écrites.

**Récupération du coffre à traiter séparément.** Pour le lot `20261115T181617Z_f8a052ab`, les 18 869 lignes mises en quarantaine sous `runtime/data` ont toutes été retrouvées, avec multiplicité et contenu JSON identiques, dans les tranches `source_octets` de `runtime/archive/session_20261115_213750`. Cela établit un chemin de récupération vérifiable à partir des rubans bruts, mais aucune de ces lignes n'a encore été redéposée : il faut un lot de rattrapage qui recertifie, dédoublonne contre les shards déjà indexés, conserve le lien archive/offset/hash et reste `LOCAL_UNRECONCILED`. Les 25 418 autres lignes viennent de `runtime/research_lab/data/micro_*` ; les fichiers actifs ont depuis tourné et les archives microstructure inspectées s'arrêtent avant ces timestamps. Leur origine brute doit être retrouvée avant toute admission. La quarantaine seule ne vaut pas source SAFE.

### P0 — Fermer la preuve économique sur le HEAD actuel

Rejouer le labo sur les shards SAFE et les checkpoints de cette époque, avec manifest, hashes, counts exacts et provenance. Exiger une politique gelée avant validation, puis OOS indépendant et forward paper strictement post-gel, frais, spread, slippage, latence, profondeur, funding et positions liquidables. La campagne présente ne possède pas encore ces éléments. Le scoreboard et le certificateur doivent refuser toute promotion fondée sur le vieux reçu ou sur le rapport TRAIN approximatif de 200 USD qui figure encore dans `current_copy_vault`.

### P1 — Chercher un edge **après observation** et après coûts

Les lois mesurées du dépôt invalident les stratégies naïves : copie globale −7,97 bps OOS même à coût nul ; 33 745 ouvertures WS observées en moins de 2 s ne laissent au plus que +0,2 bps de dérive, contre 9 bps de seuls frais taker aller-retour ; 29 620 épisodes miroir copiables et mesurables produisent −12,2 bps nets, et 47,2 % des épisodes étaient déjà fermés avant l'observation de leur entrée (`docs/LOIS_MESUREES.md`). **Réduire seulement la latence ou copier plus de fills ne résout pas cette économie.**

Hypothèses à préenregistrer, toutes Copy-Vault, avec tests placebo et correction des essais multiples :

1. Opérateurs lents à inventaire persistant et faible rotation : mesurer des transitions de position et non chaque slice de fill ; exclure les épisodes déjà clos au moment observable ; comparer au miroir simple sur les mêmes marchés et jours.
2. Sous-ensembles rares de contexte où la borne basse du markout **post-observation** dépasse frais + spread + glissement + incertitude : conditionner sur carnet causal, profondeur, volatilité et comportement de l'opérateur, puis vérifier hors échantillon sans retoucher le filtre.
3. Admission coût/capacité dynamique : refuser un signal quand l'edge conservateur par unité de risque est négatif ; tester l'échelle 10/50/100/200/350 USD seulement en diagnostic, avec minimum d'ordre, profondeur et exposition simultanée observés. Ne pas projeter linéairement les 8 trades historiques vers 350 USD.
4. Sélection des 10 abonnements `userFills` par contribution attendue en signaux *copiables* et non par volume brut, avec rotation annoncée à l'avance et journal des pertes/reconnexions. La limite officielle WS de 10 utilisateurs distincts impose d'optimiser la qualité des places, sans contourner la limite.
5. Tester la réplication d'inventaire contre des contrôles sur l'opérateur, le temps, le sens et les coins. Exiger que les gains survivent à des jours et opérateurs indépendants ; une amélioration TRAIN se gèle comme exploration, jamais comme preuve.

### P1 — Quantifier l'écart vers 10 USD/jour sans promesse

10/350 = **2,86 % nets du capital par jour**. À titre de plancher illustratif, un aller-retour taker sur 350 USD avec 0,045 % de frais par côté coûte 0,315 USD avant spread, impact et financement ; les tarifs effectifs dépendent du produit et du niveau de frais. Pour chaque candidat, publier `opportunités causales/jour × taux de fills exécutables × taille réalisable × edge net conservateur`, ainsi que les journées complètes sans trade et les pertes. Si les bornes hautes observées restent sous 10 USD/jour, conclure honnêtement `MORE_DATA` ou `REJECTED` plutôt que modifier les portes.

## Cinq chantiers supplémentaires pour le pont coffre → labo (16 novembre)

Ces chantiers portent le découpage opératoire de 8 à **13**. « Présent dans le coffre » ne signifie ni « utilisé dans un modèle » ni « admissible à la preuve PnL ». Le dernier rapport local date du 12 novembre ; les quantités ci-dessous sont un constat de ce run, pas une mesure du flux actuel.

9. **Matrice de consommation exhaustive.** Pour chaque famille de `COFFRE_INDEX`, `LOCAL_INDEX` et `DATA_INDEX`, publier nombres exacts de shards/lignes uniques, hashes, dates, statuts SAFE/LOCAL, puis la destination réelle : replay, filtre, contexte, diagnostic, exclusion motivée. Rapprocher ces comptes du manifeste d'entrée et du rapport du labo ; faire échouer le run si une famille attendue disparaît sans motif. Les 200 shards SAFE `copy_vault_positions`/`copy_vault_selection` du rapport sont inventoriés mais exclus du PnL par conception ; leurs fichiers locaux y étaient manquants. Vérifier leur rôle de contexte et leur disponibilité avant de les déclarer inutiles.
10. **Brancher réellement les contextes LOCAL aux études Copy-Vault.** Le run du 12 novembre compte **13 354 078** lignes de signaux LOCAL, dont micro BBO/L2/trades, OI/funding, ledger, portfolio et ordres leaders. Dans `copy_vault_local_lab.py`, `_charger_tier_local(..., garder_signaux=False)` ne conserve que les comptes ; `signaux_locaux` est ensuite retiré du résumé et n'alimente pas le chemin principal. Plusieurs études spécialisées peuvent lire ces familles séparément : cartographier lesquelles, puis sélectionner de petites tranches causales par temps/coin/leader pour des hypothèses préenregistrées, avec horloge et qualité explicites. Ne jamais faire passer LOCAL pour SAFE.
11. **Auditer les exclusions et la réduction de densité.** Le même run écarte volontairement **5 121 621** fills d'adresses `ARCHIVE` du replay principal et **736 724** cotations BBO redondantes par seconde. Mesurer, par cohorte et jour, la couverture et l'effet de ces politiques sur l'exécutabilité et les faux négatifs ; conserver la raison et le dénominateur exact. Réviser seulement si une amélioration causale hors échantillon est démontrée, sans saturer la mémoire ni promouvoir les robots non copiables.
12. **Réconciliation LOCAL → SAFE et disponibilité physique.** Séparer clairement lignes brutes, certifiées LOCAL, quarantaines, shards SAFE restaurés et shards effectivement lus par le labo. Pour chaque passage de statut, exiger source native, manifest, taille/hash, comptes exacts et unicité globale. Le coffre LOCAL est une entrée exploratoire ; une présence dans `LOCAL_INDEX` ne donne jamais le droit d'entrer en OOS/forward/PnL. Contrôler les familles SAFE présentes au catalogue mais absentes du disque local et les raisons de rejet du chargeur.
13. **Parité des chemins et fraîcheur.** Comparer sur un même jeu figé les entrées et décisions du labo, du replay exécutable, du moteur paper et du certificateur : mêmes identités, mêmes horloges, mêmes frais, mêmes refus et même scope Copy-Vault. Ajouter une alerte lorsque le dernier lot certifié, le dernier SAFE restauré ou le dernier rapport du labo ne couvre pas la collecte en cours. Un rapport vert sur des données du 12 novembre ne doit pas être présenté comme la preuve du 16 novembre.

Base de ces constats : `src/hl_observer/backtesting/copy_vault_tier_local.py` (familles, filtre ARCHIVE, réduction BBO), `src/hl_observer/backtesting/copy_vault_local_lab.py` (chargement LOCAL, sélection SAFE), `runtime/reports/copy_vault_quant_lab/20261112T160515843663Z/resultat.json` (comptes et exclusions). Les exclusions connues ne sont pas toutes des bugs ; le chantier exige qu'elles soient visibles, testées et justifiées.

### Audit approfondi du câblage coffre → labo (16 novembre, 13:50 UTC)

Le `LOCAL_INDEX.json` était encore modifié pendant cette inspection. Sa lecture vers 13:47 UTC annonçait **5 022 shards, 151 219 817 lignes déposées, 22 familles**. Ce sont des comptes *déclarés par l'index*, non une nouvelle vérification des lignes, de leur unicité ou de leur disponibilité physique. Le dernier résultat du labo principal remonte au **12 novembre** et ne peut qualifier l'état de la collecte du 16.

Le rapport du 12 novembre affiche encore `objective_usd_per_day=5.0` : la constitution et la spec décrivent +5 USD/jour sur 350 USD paper comme **repère de recherche**, sans gate automatique. La demande de l'opérateur vise +10 USD nets/jour **prouvés** ; aucune donnée du rapport actuel ne démontre ce palier. Ne pas modifier le repère canonique en prétendant qu'un seuil changé serait une amélioration économique.

| Familles LOCAL | Chemin constaté | Lacune à traiter |
| --- | --- | --- |
| `fills_forward`, `fills_backfill`, `snapshot`, `book_l2`, `bbo` | Pont LOCAL → rubans de replay exploratoire ; BBO dense réduit à une cotation/coin/seconde | Quantifier la couverture temporelle exécutable et les exclusions par cohorte ; distinguer sans ambiguïté le SAFE du LOCAL. |
| `allmids`, `asset_ctx`, `funding_history`, `candle`, `leader_orders`, `vault_portfolio`, `micro_bbo` | Sélection dans au moins une étude `copiabilite` spécialisée ; le chemin principal ne conserve pas leurs lignes LOCAL | Faire les jointures as-of par horloge de réception, prouver les intervalles connus et mesurer les ablations après gel de l'hypothèse. |
| `liquidation`, `micro_l2`, `micro_trades`, `overshoot`, `position`, `trades_marche`, `vault_ledger`, `venue_book`, `venue_dispersion` | Inventoriés comme signaux par le pont LOCAL ; aucune sélection explicite dans les études `etude_copiabilite.py` examinées ; comptés mais non consommés dans le chemin principal | Créer des études Copy-Vault bornées et causalement datées seulement si une fonction économique est définie ; publier les refus et les dénominateurs. |
| `explorer_tx` | Présent dans l'index mais absent du pont LOCAL et des études de copiabilité examinées | Classer ses transactions par rôle, identité et horloge ; ne pas les promouvoir automatiquement comme signaux de trading. |

Les **dix familles sans sélection explicite dans ces études** sont `explorer_tx`, `liquidation`, `micro_l2`, `micro_trades`, `overshoot`, `position`, `trades_marche`, `vault_ledger`, `venue_book`, `venue_dispersion`. Cela n'exclut pas un autre consommateur SAFE ou diagnostique ailleurs ; le constat porte sur les études LOCAL de copiabilité et le pont principal examinés. En mode habituel `safe`/`once`, le lanceur exécute uniquement l'étude de copiabilité de base (optionnelle), puis le labo principal ; les études `positions`, `retrospectif`, `ouvertures`, `ordres`, `persistance` et `replication-350` demandent le mode explicite `copiabilite`. Les derniers résultats spécialisés trouvés datent aussi du 12 novembre.

**Défauts vérifiés et corrigés localement.** Le pont LOCAL reconnaissait seulement `ts_ms` et `snapshot_ts_ms` dans ses signaux. Les `candle` (`open_ts_ms`), `position` (`received_at_ms`) et `trades_marche` (`exchange_ts_ms`/`received_at_ms`) pouvaient disparaître même de l'inventaire de signaux : il reconnaît maintenant leurs horloges et publie les familles indexées, non chargées, non horodatées et seulement comptées. Un shard sans SHA pouvait être lu ; la présence et la validité de son SHA sont maintenant obligatoires. Le pont et `etude_copiabilite.py` bornent les chemins de shards au coffre LOCAL ; le pont annule les lignes d'un shard si son gzip ou son JSON échoue en cours de lecture. Le `READY` du manifeste exige maintenant des fills **et** des carnets issus de la reconstruction SAFE, tandis que la disponibilité exploratoire mixte reste indiquée séparément.

Deux chargeurs de signaux du labo lisaient la racine du workspace alors que la matérialisation écrit dans `runtime/data/` : le filtre overshoot sur `active_asset_ctx` et le filtre de qualité des leaders sur les fills pouvaient recevoir `[]` sans alarme. Leur chemin est corrigé ; le chargeur de qualité leader refuse les fills LOCAL et les lignes sans marque de manifeste SAFE vérifié. Ce défaut est cohérent avec l'ancien rapport `overshoot_exploration=SKIPPED/NO_ASSET_CTX_POINTS`, mais ce rapport seul ne prouve pas que c'était son unique cause. Les effets économiques des filtres doivent être remesurés sur un run neuf.

Le filtre de qualité leader avait aussi une fuite temporelle potentielle : il associait `closed_pnl` à l'heure d'exécution `ts_ms`, même si le fill n'arrivait au collecteur que plus tard. Le chargeur fournit maintenant à l'index **l'heure de réception vérifiée**, uniquement pour des fills live SAFE non snapshot ; un fill sans cette horloge est écarté. Ainsi le filtre ne peut plus connaître le PnL d'un fill avant sa réception dans le chemin du labo. La politique de traitement des égalités exactes en millisecondes et la continuité après reconnexion restent à tester par campagne.

**Travail encore ouvert dans les chantiers 9–13.** Produire une matrice automatique de consommation par famille avec comptes exacts, présence physique, hash, timestamps et rôle réel ; exécuter des études causales ciblées sur les familles actuellement seulement comptées ; comparer chaque variante à la baseline sur des jours indépendants, avec ablations et contrôle des essais multiples ; rejouer les données de la nouvelle époque de checkpoints et obtenir OOS/forward puis preuve comptable. Aucun compte du coffre ni correction de câblage ne démontre +10 USD nets/jour.

Validation ciblée après ces correctifs : **99 tests passés** (`test_lab_coffre_injection.py`, `test_copy_vault_local_lab.py`, `test_copy_vault_copiability.py`, `test_leader_quality_signal.py`). Le contrôle de whitespace Git est propre avec `cr-at-eol` pour le fichier historique en CRLF. Ce résultat vérifie les cas de code testés, pas une campagne économique récente.

## Vérifications et limites

Les tests ciblés des correctifs UI, collecteurs, scope, exécuteur, coffre et chaîne économique ont passé : **329 tests** dans la sélection élargie finale du 16 novembre. Le contrôle `git diff --check` ciblé est propre avec la convention CRLF du dépôt. Le test complet du dépôt et une nouvelle exécution du labo sur les checkpoints postérieurs à cette collecte restent à faire. Ni le heartbeat, ni la certification locale, ni ces tests ne constituent une preuve de 10 USD nets/jour.

Sources publiques primaires consultées : [frais Hyperliquid](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), [limites API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits), [abonnements WebSocket](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions). Les propositions ci-dessus sont des hypothèses de recherche, pas des résultats observés.

---

## Reprise de l'audit — 16 novembre, session du soir

### État exact revalidé (et non repris des rapports)

| Fait | Valeur mesurée | Comment |
| --- | --- | --- |
| HEAD local | `b206107b04bd` | `git rev-parse HEAD` |
| `main` distant réel | `48574b920357` | `git ls-remote origin main` (lecture seule, aucun fetch) |
| Divergence | **139 commits d'avance pour origin**, 0 pour local | `git rev-list --left-right --count` |
| Code concerné par ces 139 commits | **aucun** : `git diff HEAD origin/main -- src/ tools/ tests/` est **vide** | diff ciblé |
| Nature des 139 commits | reçus de campagne cloud (`campaign: checkpoint market-e8-*`), plus `docs/*.json` et `catalog/` | `git log --oneline origin/main ^HEAD` |
| Modifications locales non commitées | **40 fichiers** de `src/`, `tools/`, `tests/`, `docs/` — tous préservés | `git diff --name-only HEAD` |

`git status --porcelain` ne termine pas sous 120 s sur cet index (défaut connu : index géant). Le
diff ciblé par chemins est la méthode qui répond.

### Défauts NOUVEAUX trouvés et corrigés dans cette reprise

1. **Un test de politique était ROUGE sur `origin/main` lui-même.**
   `test_la_racine_contient_uniquement_les_lanceurs_principaux_et_alinasync` énumère 10 `.cmd`
   autorisés à la racine ; `origin/main` en publie **11** (`CERTIFIER_EN_CONTINU.cmd` n'a jamais
   été déclaré dans `ENTRYPOINT_ROLES`), et le local en a 12 avec `RATTRAPAGE.cmd`. La politique
   n'interdit pas un lanceur d'appoint à la racine : elle interdit un lanceur **non classé**. Les
   deux sont déclarés `MAINTENANCE` dans `entrypoint_topology.py` et admis au test.
   *Un workflow vert ne prouvait donc pas que cette politique tenait.*
2. **`test_tout_ce_que_le_lanceur_demande_existe_dans_le_registre` accusait le registre à tort.**
   Il rougissait sur `copy-vault-checkpoints`, alors que ce collecteur **tourne** (battement frais,
   présent dans la liste `active` du watchdog). Cause : le test ne lisait que `REGISTRE`, tandis
   que la résolution réelle (`bounded_collection._registry`, ligne 46) lit
   `REGISTRE + COLLECTEURS_CAMPAGNE`. Le test interroge désormais la **même union**, en important
   la fonction de résolution, et vérifie en plus que chaque nom a un `script`.
3. **Le lanceur annonçait `19 collecteurs actifs` alors que `DEFAULT_NAMES` en compte 20.**
   La bannière n'avait pas suivi l'ajout du compagnon. L'opérateur lisait un chiffre faux.
4. **`test_eco_011_checkpoint_coverage_requires_exact_counts` était rouge avant cette session** :
   le correctif qui a resserré `coverage_receipt` (refus de `PROVEN` sur compteur manquant) n'avait
   pas mis à jour son test de contrat. Le test vérifie maintenant les deux sens : jeu complet →
   `PROVEN`, compteur absent → `UNMEASURABLE/COUNTERS_INCOMPLETE_OR_INVALID`, expiration → refus.

### Chantier 2, bloqueur 2 — RÉPARÉ : segmentation des trous

`copy_vault_book_loader` exigeait `input_rotations + checkpoints_expired + pending_overflow == 0`.
Ces compteurs sont **cumulatifs sur tout le run** : 43 expirations et une rotation rendaient non
certifiables les 25 875 checkpoints du run, **y compris ceux des minutes sans aucun incident**.

Réparation en trois pièces :

* `src/hl_observer/collection/copy_vault_gap_windows.py` (nouveau, 21 tests) — l'écrivain publie la
  **fenêtre temporelle** de chaque trou ; le lecteur calcule le complément, c'est-à-dire les
  intervalles `EXECUTION_REPLAY_SAFE`, avec une marge de garde de 250 ms.
* `copy_vault_checkpoint_tail.py` — une fenêtre à chacun des trois sites : rotation
  `[dernière ligne ingérée, détection]`, expiration `[cible, maintenant]`, débordement
  `[min cible, max cible]` portant `n = len(additions)`.
* `copy_vault_book_loader.py` — une ligne n'est « époque propre » que si sa **réception** tombe hors
  de toute fenêtre ; le reçu publie `gap_segmentation_reason`, `safe_interval_count`,
  `safe_coverage_ms`, `epoch_span_ms`, `rows_inside_gap_window`.

**Ce qui reste fermé, et c'est l'essentiel.** `receipt_valid` exige que la position de **chaque**
trou soit connue : la somme des fenêtres doit égaler exactement chaque compteur
(`gap_segmentation_reason == "OK"`). Un seul trou de position inconnue referme l'époque entière.
Un état d'écrivain sans journal de fenêtres — **tout processus démarré avant ce code, dont celui du
16/11** — ne rend aucun intervalle sûr : **aucune réparation rétroactive**, et les 25 875 lignes
déjà écrites restent non certifiables. Aucun compteur n'est remis à zéro. Si le journal borné perd
une fenêtre, `gap_windows_dropped` le dit et tout se referme.

Le test `test_file_replacement_is_recovered_but_invalidates_clean_epoch` encodait le bloqueur
lui-même. Il est remplacé par un contrat **plus fort** : le trou reste compté, sa position est
exigée, la ligne reçue **dans** la fenêtre est refusée (`rows_inside_gap_window >= 1`) et celle
reçue **après** est certifiée. Une addition redondante à la porte économique a été retirée : la
protection vit à la source (le lecteur), où elle ne peut pas être contournée.

### Chantier 2, bloqueur 1 — mesuré, module livré, câblage en cours

Faisabilité mesurée sur les données du 16/11, **fenêtres de temps appariées** (195,9 min de carnets
WS contre 194,5 min de fills ; 171 713 lignes de `copy_vault_l2_lane.jsonl` sur 180 coins) :

```
LIABLE A UN CARNET PRE-SIGNAL (<= 30 s) : 10 470 / 10 470 = 100,0 %
age du carnet lie : median 6 637 ms | p90 11 329 ms
```

**Correction d'une sonde fausse de ma part** : une première mesure annonçait 34,2 % ; elle comparait
40 Mo de carnets à 8 Mo de fills, donc des fenêtres de temps différentes. La sonde était fausse,
pas la donnée. Le ruban `copy_vault_l2_lane.jsonl` porte déjà `connection_id` et `l2_gap_epoch`.

`src/hl_observer/collection/copy_vault_reference_binding.py` (nouveau, 19 tests) produit la liaison
revérifiable : source, offset, **SHA-256 de la ligne exacte**, `connection_id`, `l2_gap_epoch`,
horloge de réception. **Question ouverte du journal tranchée** : une égalité exacte à la
milliseconde entre réception du carnet et réception du signal est **refusée** — dans la même
milliseconde l'ordre n'est pas observable, et l'accepter fabriquerait la causalité qu'on mesure.
Au chargement, trois statuts honnêtes : `VERIFIED`, `MISMATCH`, et `UNVERIFIABLE` quand le ruban a
tourné — une preuve absente n'est pas une preuve de faux, mais elle ne certifie rien.

Un âge médian de 6,6 s n'est pas neutre économiquement : le carnet de référence a vieilli avant le
signal. L'exécuteur devra le facturer ; aucune de ces pièces ne crée d'edge.

### Chantier 1 — LE TUNNEL D'EXÉCUTABILITÉ, MESURÉ (`tools/tunnel_executabilite.py`)

Outil neuf, règles **importées** des modules de production (classification d'entrée, liaison
pré-signal) pour qu'une divergence entre la mesure et le moteur soit impossible. Fenêtre lue :
1 143,8 min de carnets (1 002 078 lignes, 180 coins) contre 31 Mo de fills.

| étage | n | part des signaux |
| --- | --- | --- |
| A lignes lues | 40 673 | — |
| B horloges et identité native | 40 673 | — |
| C fill LIVE_WS non snapshot | 40 673 | — |
| D signal d'ouverture | **21 372** | 100,0 % |
| E jugeable dans la fenêtre | 21 355 | 99,9 % |
| F **référence pré-signal** | 21 349 | 99,9 % |
| G carnet d'entrée (+60 s) | 21 347 | 99,9 % |
| H sortie observée (+300 s) | **21 060** | **98,5 %** |

Motifs de refus, comptés **une fois** au premier refus : `PAS_UNE_OUVERTURE` 19 301 (fills qui ne
sont pas des ouvertures), `EXIT_CENSURE` 287 (censurés, ni PnL nul ni clôture implicite),
`HORS_FENETRE_DE_MESURE` 17, `AUCUN_CARNET_POUR_CE_COIN` 6 (ANIME 3, S 3), `ENTRY_BOOK_ABSENT` 2.
Âge du carnet de référence : médiane 6 382 ms, p90 11 340 ms, max 21 389 ms. 16 leaders distincts,
**16 avec chaîne complète**.

**À comparer au rapport du 12/11 : 0 trade exécutable sur 98 138 signaux.** Rien n'a été élargi :
la référence est désormais un carnet réellement reçu avant le signal. Et cela ne mesure que la
**complétude causale de l'observation** — pas une rentabilité.

Limite honnête à retenir : **16 leaders seulement** sur le ruban live (limite WS de 10 abonnements
userFills), là où le registre en suit ~120 via `userfills-poll`. Le chantier 3 (allocation des
places par signaux copiables attendus) reste entièrement ouvert.

### Chantiers 9, 10, 12 — MATRICE DE CONSOMMATION (`tools/matrice_coffre.py`)

5 103 shards, 22 familles, **154 410 731 lignes déposées**, et **tous les shards indexés sont
présents sur le disque** (0 absent, 0 shard sans SHA, 0 divergence d'octets). Destinations lues du
CODE de production, non d'une intention : `REPLAY_PNL` 3 familles, `CARNETS` 2, `CONTEXTE` 16,
**`NON_CHARGEE` 1**.

* `explorer_tx` — 196 shards, **7 914 792 lignes**, 9 jours : indexée et **aucun chemin de
  chargement** dans le pont LOCAL. Ni consommée, ni exclue avec motif. C'est la seule famille dans
  cet état.
* `candle` 2 282 jours et `funding_history` 1 102 jours : la profondeur historique est réelle.
* Les 16 familles `CONTEXTE` ne sont conservées que si `garder_signaux=True` ; le chemin principal
  les **compte puis les jette**. « Inventoriée » n'est toujours pas « consommée ».

### DÉFAUT P0 TROUVÉ PAR LA MATRICE, ET CORRIGÉ : deux familles datées « jour inconnu »

`_ts_primaire` dans `tools/sceller_coffre_local.py` repliait sur `record["ts_ms"]`, champ que deux
familles ne portent pas :

* `position` — 171 shards, 870 142 lignes — n'a que `received_at_ms` ;
* `trades_marche` — 192 shards, 24 095 493 lignes — a `exchange_ts_ms`.

Leurs **363 shards** étaient donc indexés `jours = ["0000-00-00"]`. Conséquence directe sur la
recherche : **aucune étude ne peut les découper par jour**, alors que la seule hypothèse non
réfutée par `docs/LOIS_MESUREES.md` — opérateurs lents, réplication d'inventaire — exige des
**transitions de position sur des jours indépendants**. Le pont du labo avait reçu ce correctif le
16/11 ; le scelleur, non. Corrigé, 5 tests. **Les shards déjà scellés gardent leur sentinelle** :
rien n'est réécrit rétroactivement, et un réindexage explicite reste nécessaire pour les anciens.

Note de méthode : la colonne « jours » de ma première matrice affichait 0 partout — `jours` est une
**liste** dans `LOCAL_INDEX` et un **dictionnaire** dans les manifestes, et je ne traitais que le
dictionnaire. La sonde était fausse ; le défaut `0000-00-00`, lui, est réel et mesuré séparément.
Troisième sonde fausse de la session : les contrôles se vérifient comme le reste.

### L'ÉCART VERS +10 USD/JOUR — arithmétique, sans promesse

Capital 350 USD. +10 USD/jour net = **2,857 % du capital par jour = 285,7 bps/jour**.

Cycle observé par le protocole lui-même : entrée à +60 s (`COPY_DELAY_MS`), sortie mesurée à
+300 s, soit **360 s par aller-retour** → au plus **240 cycles/jour** en séquentiel, capital entier
à chaque fois.

* edge **net** requis par cycle : `10 / (240 × 350)` = **1,19 bps** ;
* frais taker seuls : 0,045 % par côté = **9,0 bps** l'aller-retour, avant spread, impact et
  financement ;
* edge **brut** requis : **≥ 10,2 bps par cycle** ;
* dérive post-observation mesurée sur 33 745 ouvertures vues en moins de 2 s : **borne haute
  d'IC 95 % = +0,2 bps**.

**L'écart est d'un facteur ≈ 51 sur l'edge brut**, pas d'un seuil à déplacer. Le même calcul pour
le repère canonique de +5 USD/jour demande ≥ 9,6 bps brut, soit ≈ 48×. Réduire le nombre de cycles
aggrave l'exigence (24 cycles/jour → 20,9 bps brut). L'entrée maker contournerait les 9 bps, mais
`market_making_spread` est **réfuté** (0 gagnant sur 29 coins à 100 % de fill supposé).

La contrainte qui mord n'est donc pas l'opportunité — 21 060 chaînes complètes en ~19 h — mais le
**capital** et le **coût par aller-retour**.

**Verdict : `REJECTED` pour la copie rapide et le miroir d'épisodes à ces coûts** (déjà réfutés par
la mesure, et l'arithmétique ci-dessus le confirme à 350 USD). **`MORE_DATA` pour la seule porte
non réfutée** — opérateurs lents à rotation ≤ 3× l'exposition par jour, réplication d'inventaire
mesurée sur transitions de position. Condition précise pour trancher : **≥ 20 jours indépendants**
de transitions de position avec jours réellement datés (donc après le correctif d'horloge
ci-dessus **et** un réindexage des 171 shards `position` existants), gel de la politique avant
mesure, puis OOS indépendant et forward strictement post-gel.

### Chantier 10 — plus aucune famille en limbe

`explorer_tx` était dans un troisième état, ni consommée ni exclue : désormais inscrite dans
`FAMILLES_EXCLUES_DU_REPLAY` (`copy_vault_tier_local.py`) avec le motif
`DECOUVERTE_DE_LEADERS : metadonnee d'activite on-chain, sans horloge de marche par coin ; sa
readmission exige une fonction economique ecrite et une jointure as-of prouvee`. Son rôle était
déjà documenté dans `tools/auditer_donnees_collectees.py` ; il est maintenant **lisible depuis la
matrice**. Résultat : `NON_CHARGEE: 0` sur les 22 familles.

`tests/test_matrice_coffre.py` (4 tests) interdit le retour du troisième état : toute famille de
l'index RÉEL doit avoir une destination déclarée, tout motif d'exclusion doit dire ce qui
permettrait une réadmission, et une famille ne peut pas être à la fois chargée et exclue.

### Blocages restants, et leur condition exacte de levée

1. **`test_rig_020_all_current_receipts_are_exactly_revalidated` est rouge** et le reste. Le reçu
   `AUD-044` porte un `sha_kind = working_tree_file_set_sha1_of_sha256_manifest` : il est lié à un
   arbre de travail EXACT. Avec 40 fichiers modifiés non commités avant cette session, il était
   déjà périmé ; il l'est davantage maintenant. Condition de levée : commiter, puis **rejouer la
   vérification de la tâche auditée** pour réémettre le reçu. Signer un reçu pour une tâche que je
   n'ai pas rejouée serait exactement la fabrication de vert que la constitution interdit.
2. **Les 363 shards `position`/`trades_marche` déjà scellés gardent `0000-00-00`.** Le correctif
   d'horloge ne vaut que pour les lots suivants. Condition : un réindexage explicite, traçable,
   qui recalcule l'histogramme de jours depuis les rubans d'archive — à concevoir comme un lot de
   rattrapage, jamais comme une réécriture silencieuse de l'index.
3. **16 leaders sur le ruban live** contre ~120 suivis par `userfills-poll` : la limite de 10
   abonnements WS `userFills` borne la mesure. Condition : allouer ces 10 places par **signaux
   copiables attendus** (chantier 3), avec rotation annoncée et journal des pertes — sans
   contourner la limite de la venue.
4. **Le labo n'a pas encore rejoué cette époque.** Le dernier résultat principal date du 12/11.
   Le tunnel montre que la chaîne d'observation est désormais complète à 98,5 % ; il reste à
   exécuter le replay, geler une politique, puis OOS et forward strictement post-gel.

### DÉFAUT D'HONNÊTETÉ CORRIGÉ : `objective_status = "ATTEINT"` pour 0,90 USD

Trouvé par deux tests rouges que la suite large a fait remonter — et c'est le défaut le plus grave
de la session, parce qu'il portait sur ce que l'opérateur lit.

`evaluate_objective` rendait `objective_status = "ATTEINT"` dès que **les portes de qualité
passaient et que le net était strictement positif**. Un net prouvé de **0,90 USD** s'annonçait donc
`ATTEINT` face à un repère de **5,00 USD/jour**. L'intention du correctif précédent était juste —
un net positif de qualité ne doit pas être rejeté pour la seule raison qu'il est sous le repère —
mais le NOM mentait, et deux fichiers de tests se contredisaient sur le sens d'`ATTEINT`.

**Trois états désormais, et `ATTEINT` veut dire ATTEINT** (`_statut_objectif`) :

| état | condition |
| --- | --- |
| `ATTEINT` | portes de qualité passées **et** repère atteint |
| `POSITIF_SOUS_REPERE` | portes passées, net > 0, repère **non** atteint |
| `NON_ATTEINT` | tout le reste |

Propriétés vérifiées : l'**agrégat** reste `NON_ATTEINT` (les consommateurs qui testaient
`== "ATTEINT"` deviennent strictement plus conservateurs) ; la nuance vit au niveau de la famille ;
`positive_net_proof`, `quality_gates_passed`, `historical_target_reached` et
`reference_target_reached` conservent la séparation que la session précédente voulait. Un total de
8,60 USD dont un jour à 3,99 USD n'atteint PAS un repère exprimé **par jour** : il est désormais
nommé pour ce qu'il est.

Les assertions d'origine de `tests/test_pre_run_pnl_301_313.py` sont **rétablies par le correctif
du code**, non par un assouplissement du test. Chaîne économique complète : **1 474 tests verts**.

---

## Clôture — chantiers 3, 11 et 13 traités

### Chantier 3 — les 10 slots `userFills` vont désormais aux signaux COPIABLES

Composant existant **étendu, non dupliqué** (`subscription_universe.score_activite_leader`, qui
classait par `fills/min` pondéré 3,0 — du volume brut). `docs/LOIS_MESUREES.md` dit pourquoi c'est
le mauvais critère : **61,8 % des fills collectés venaient d'opérateurs HFT non copiables** et
47,2 % des épisodes étaient déjà clos quand leur ouverture devenait observable. Donner un slot rare
au leader le plus bavard, c'est payer pour ce bruit.

* nouveau poids dominant `copiables` (4,0) sur `signaux_copiables_par_jour`, mesuré par le tunnel ;
* un leader dont la copiabilité est **mesurée à zéro** sur ≥ 30 fills rend `-inf` : son volume ne
  peut plus lui acheter un slot ;
* `None` (jamais mesuré) **n'est pas** `0` (mesuré nul) : l'inconnu retombe sur l'activité brute ;
* `PRIME_COPIABILITE_MESUREE` (2,0) préfère explicitement le **mesuré** au **présumé** pour les
  slots CORE — sans elle, un leader jamais mesuré mais bavard devançait un leader prouvé copiable
  (4,92 contre 4,49). L'exploration de l'inconnu reste le rôle des slots CHALLENGERS (UCB).

4 tests. 230 tests verts sur la sélection d'abonnements.

### Chantier 13 — l'alerte de fraîcheur existe et elle tire

`src/hl_observer/ops/fraicheur_preuve.py` (7 tests) compare les horloges de la chaîne de preuve à
l'instant de la collecte réellement en cours. Fail-closed : une date absente n'est pas « récente
par défaut », c'est `INCONNU`, et `INCONNU` ferme. Tolérance 1 h, assez pour absorber une passe de
scellage de 30 min sans crier au périmé.

Câblée dans `tools/tunnel_executabilite.py`. Sortie sur les données réelles du 16/11 :

```
[fraicheur] PERIME — la preuve ne couvre PAS la collecte en cours :
            dernier_rapport_labo=95.9 h de retard.
```

95,9 h, soit exactement l'écart 12/11 → 16/11 que l'audit signalait à la main. Il est maintenant
dit automatiquement, dans la mesure elle-même.

### Chantier 11 — les exclusions MESURÉES, avec leur dénominateur

Plan du 12/11, 222 leaders :

| cadence | n | archétype | n |
| --- | --- | --- | --- |
| ARCHIVE | 75 | HFT | 75 |
| STANDARD | 57 | SWING | 57 |
| DECOUVERTE | 53 | INSUFFICIENT | 53 |
| PRIORITAIRE | 37 | DIRECTIONAL_SLOW | 37 |

**L'exclusion ARCHIVE recouvre exactement la cohorte HFT** — celle que la loi mesurée déclare non
copiable (61,8 % des fills). Elle n'est donc pas arbitraire : elle retire ce que la mesure a déjà
tranché. **Faux négatif identifié : un seul leader** classé ARCHIVE alors que sa rotation est
≤ 3×/jour — à réexaminer nommément avant toute réadmission de cohorte.

**Population de la seule hypothèse non réfutée** (rotation ≤ 3× l'exposition par jour, condition de
réouverture de `copy_miroir_episodes`) :

```
OPERATEURS LENTS : 38 / 222 = 17,1 %   (37 PRIORITAIRE, 1 ARCHIVE)
  rapides (> 3x/jour)      : 141
  sans mesure de rotation  :  43        <- inconnu, PAS « lent »
  exposition mediane des lents : 156 823 USD

LEADERS OBSERVES sur le ruban live : 15
  dont LENTS selon le plan          :  8
  hors plan du 12/11                :  3
```

**8 opérateurs lents sont donc réellement observés**, et le tunnel leur fournit 21 060 chaînes
causales complètes. L'hypothèse devient mesurable — elle n'est pas mesurée. Il manque toujours les
**20 jours indépendants** de transitions de position correctement datées.

### Chantier 10 — « comptées puis jetées » devient « comptées ET utilisables »

Le chemin principal appelait `_charger_tier_local(..., garder_signaux=False)` : les 16 familles de
contexte étaient comptées puis jetées (13 354 078 lignes au run du 12/11). **Ce `False` n'était pas
l'erreur** — garder 154 millions de lignes ferait sauter la machine, et la règle est « on rétrécit,
on ne crashe jamais ». L'erreur, c'est qu'il n'existait **aucun moyen intermédiaire** : tout ou rien.

`src/hl_observer/backtesting/coffre_tranches.py` (19 tests) est ce moyen. L'index du coffre porte
déjà, pour chaque shard, ses `coins`, ses bornes `ts_min_ms`/`ts_max_ms` et son `sha256` : on
sélectionne donc les **seuls** shards qui croisent une fenêtre et une liste de coins.

**Mesure sur le coffre réel** :

```
SANS tranche : funding_history = 54 shards, 3 285 943 lignes, 44,2 Mo
AVEC tranche : BTC+ETH sur 30 jours -> 6 shards retenus (7,8 Mo), 1 440 lignes en 2,0 s
               44 shards ecartes par coin, 4 par le temps, 0 sans bornes
```

**2 282 fois moins de lignes pour la même réponse.**

Quatre garanties, chacune testée :

* **jointure as-of STRICTEMENT antérieure** — une valeur postérieure ne peut jamais entrer, et une
  égalité exacte à la milliseconde est refusée (même règle que la liaison du carnet de référence).
  Un événement sans contexte antérieur reçoit `None`, **jamais un zéro** ;
* **SHA-256 obligatoire** — un shard divergent est refusé entier, avec son motif ;
* **mémoire plafonnée ET dite** — au-delà de `max_lignes`, `tronque=True` ; jamais de troncature
  silencieuse ;
* **un shard sans bornes n'est pas jeté en silence** — il sort dans `sans_bornes`, parce qu'on ne
  peut pas prouver qu'il est hors fenêtre.

Le chemin principal publie désormais `contexte_tranchable` : l'état EXACT de chaque famille, à
trois valeurs plutôt qu'un booléen trompeur.

| famille | état | shards bornés |
| --- | --- | --- |
| `funding_history` | COMPLETE | 54/54 (100 %) |
| `candle` | PARTIELLE | 274/281 (97,5 %) |
| `position` | PARTIELLE | **4/175 (2,3 %)** |
| `trades_marche` | PARTIELLE | **4/196 (2,0 %)** |

Sur 22 familles : **19 COMPLETE, 3 PARTIELLE**. Et les 4 shards bornés de `position` et
`trades_marche` datent tous du 16/11 **après 15 h 57** — c'est-à-dire après le correctif d'horloge
du scelleur. **Le correctif fonctionne en production** ; les 363 shards antérieurs attendent
toujours un réindexage explicite.

### Chantier 10, suite — plus AUCUNE famille silencieuse, et le contrat est testé

**La carte de consommation réelle, extraite de l'AST** de `tools/etude_copiabilite.py` (on lit le
CODE, pas une liste tenue à la main) reproduit **exactement** les dix familles que l'audit avait
identifiées à la main le 16/11. La méthode est donc validée par recoupement.

Trois actions, et un verrou de test :

1. **`select_shards` accepte une sélection bornée** (`coins`, `debut_ms`, `fin_ms`), déléguée à
   `coffre_tranches.selectionner` pour qu'une seule règle de sélection existe dans le dépôt.
   Mesure : `funding_history` 54 shards → **6** en 0,1 s au lieu de 0,4 s, chaque écart motivé
   (`hors_fenetre_ou_hors_coins`, `gardes_sans_bornes_de_temps`). Un shard sans bornes est
   **gardé**, jamais écarté : on ne peut pas prouver qu'il est hors fenêtre.
2. **La famille `position` est branchée** dans `run_positions` ET `run_replication_350` — les deux
   études de l'hypothèse ouverte. Elle n'était lue par **personne**. Mesure réelle :
   **879 541 lignes, 54 vaults, 179 coins, 5,0 jours, 0 ligne sans horloge**, lues en 5,7 s. C'est
   une seconde source, indépendante et par coin, de ce que l'étude déduisait des instantanés
   (300 262 lignes, portefeuille entier). Elle est publiée comme **diagnostic mesuré**, et
   **délibérément non fusionnée** au PnL : deux sémantiques différentes mélangées sans preuve
   fabriqueraient des transitions fantômes.
   *Et ce chiffre tranche l'hypothèse ouverte : **5,0 jours observés, 20 requis**.*
3. **`venue_book` et `venue_dispersion` sortent du pont LOCAL.** Cross-Venue est
   `DISABLED_BY_SCOPE` : le verrou constitutionnel couvre explicitement le labo et les replays,
   donc les offrir à la recherche exploratoire rouvrirait ce scope par la bande. Elles restent
   **inventoriées** par la matrice, qui lit l'index et non le pont : la visibilité est conservée,
   seul le chargement est fermé.

**Le registre `FAMILLES_A_CABLER`** donne aux six familles restantes la fonction économique
qu'elles serviraient ET la condition pour les brancher (`liquidation`, `overshoot`,
`trades_marche`, `micro_l2`, `micro_trades`, `vault_ledger`). Un backlog nommé plutôt qu'un
silence.

**État final des 22 familles :**

```
REPLAY_PNL 3 · CARNETS 2 · CONTEXTE 8 · A_CABLER 6 · EXCLUE_MOTIVEE 3 · NON_CHARGEE 0
```

`tests/test_coffre_tranches.py` (24 tests) interdit le retour du silence : toute famille de
l'index RÉEL doit être consommée, exclue avec motif, ou inscrite au backlog avec sa fonction et sa
condition — et aucune ne peut être dans deux états à la fois. 180 tests verts sur l'ensemble du
pont coffre → labo.

### RÉPARATIONS DU 16/11 AU SOIR — budget, recul, et réindexage

**1. Le budget du rattrapage ne coulait pas.** Mesure du passage de 18:14 : `funding-profond`
avait 26 894 s, s'est arrêté sur `LIMITE_DEBIT` après 2 400 s, et les **24 494 s restantes ont été
perdues** — `bougies-4h`, `bougies-1h` et `bougies-5m` ont affiché « budget épuisé » alors que
6 h 48 dormaient. La répartition était calculée **une fois pour toutes au départ**. Elle est
désormais recalculée après CHAQUE tâche, sur le temps réellement restant : une tâche qui finit tôt
rend son budget, une tâche qui déborde le prend à la suivante — ce qui reste juste, le plan étant
trié par rendement. 2 tests, dont un qui vérifie que le reflux ne devient pas un budget infini.

**2. Deux refus 429 tuaient la passe de funding.** L'AIMD existe pour reculer : chaque refus
divise le débit par deux (600 → 300 → 150 → 100, le plancher). Renoncer au deuxième refus, c'était
abandonner **avant même d'avoir atteint le débit prudent d'origine**. Désormais
`REFUS_AVANT_ABANDON = 5`, avec une attente qui croît à chaque refus et un compteur remis à zéro
dès le premier succès. Une venue durablement fermée arrête toujours la passe : on recule, on ne
s'acharne pas. 2 tests.

**3. Réindexage des shards sans horloge** (`tools/reindexer_shards.py`, 11 tests). Simulation
complète sur le coffre réel :

```
candidats : 370   statuts : {"MESURE": 370}   ecartes : 0   duree : 333 s
par famille : trades_marche 192 · position 171 · candle 7
```

Les 370 shards sont lisibles, leur SHA correspond, et leurs horloges sont retrouvées. L'outil
**ne touche aucun shard** — il ne lit que leurs octets, et seul l'index est réécrit, après
sauvegarde et de façon atomique. Il importe la table d'horloges du scelleur au lieu de la recopier,
il prend le **verrou du scelleur** (réécrire l'index pendant une certification le corromprait), et
il **ne fabrique aucune date** : un shard dont aucune ligne n'est datable garde sa sentinelle.

Effet attendu : `position` passe de 4/175 shards découpables à 175/175, et `trades_marche` de
4/196 à 196/196. La famille de la seule hypothèse ouverte devient enfin découpable par jour.

### Le harnais des lanceurs — deux défauts qui rendaient son « vert » creux

`tools/tester_cmds.py` teste les `.cmd` de la racine, mais **uniquement ceux inscrits à son
registre**. Deux écarts rendaient sa couverture illusoire :

1. **Deux lanceurs racine n'y étaient pas** : `RATTRAPAGE.cmd` (ajouté le 15/11) et
   `CERTIFIER_EN_CONTINU.cmd` (publié sur `origin/main` sans rôle déclaré — le même qui faisait
   rougir le test de politique des entrypoints). Ils n'étaient donc testés par **personne**, et
   rien ne le signalait. Ajoutés : `RATTRAPAGE` en `--plan` (catégorie `sur` : il mesure et
   affiche, zéro requête réseau), `CERTIFIER_EN_CONTINU` en `long` — c'est une boucle de 30 min,
   et la tuer en plein scellage laisserait son verrou en place.
2. **Une entrée mentait sur son effet.** `ALINA_SYNC_preflight` ne passait **aucun argument** :
   le lanceur retombait sur son défaut `--download-safe --all-safe --unpack-safe`, c'est-à-dire le
   téléchargement et la décompression de **tout le corpus SAFE (15 456 lots)**. Une passe de test
   déclenchait donc une récolte complète, et le nom laissait croire à un simple contrôle. Corrigé :
   l'entrée passe `--preflight-only`.

`tests/test_tester_cmds_couvre_tout.py` (6 tests) rend ces deux écarts impossibles : tout `.cmd` de
la racine doit être au registre ; une entrée ne peut pas pointer vers un fichier absent ; un
lanceur à effet externe (`POUSSER-GITHUB-FORCE`, les deux `Noeud HL`) doit rester en `danger` avec
un timeout nul, pour qu'aucune passe automatique ne puisse le déclencher ; un service continu
(collecteurs, moteur, certificateur en boucle) ne peut pas entrer dans la passe `sur`, car le
harnais **arrête les collecteurs** en partant — ce qui tuerait une campagne en cours.

### Le contrôle qualité criait au loup — et déclarait MORT le collecteur le plus critique

Trouvé en lançant le harnais des `.cmd`. `tools/controle_qualite_campagne.py` annonçait
**6 anomalies à chaque passage**, dont celle-ci :

```
!! copy-vault-checkpoints : MORT — journal fige depuis 1320 min ET aucun processus.
   Ce flux est PERDU tant qu'il ne repart pas.
```

**C'était faux.** Au même instant : battement à 0 s, sept processus, et son ruban
`copy_vault_l2_tape.jsonl` écrit à la seconde. Deux causes, dont une déjà rencontrée le matin :

1. `_collecteurs_attendus` lisait **`REGISTRE` seul**, alors que `copy-vault-checkpoints` vit dans
   `COLLECTEURS_CAMPAGNE` — le même piège que le test du lanceur. Son `script` valait `""`, donc
   aucun processus ne pouvait lui correspondre : verdict « MORT » sur le compagnon dont dépend
   **tout** le travail causal.
2. La fraîcheur se jugeait sur le `mtime` d'un **journal**, qui n'est écrit que sur événement.
   `userfills-poll` était annoncé « figé depuis 5 588 min » alors que son ruban pesait 1 051,8 Mo
   et venait d'être écrit.

Correction, par ordre de force du signal : **battement canonique** d'abord (il est écrit POUR dire
« je vis »), puis **la donnée réellement produite** — le dépôt déclare déjà quel script écrit quel
ruban (`couverture_donnees.FLUX`), on lit cette déclaration au lieu de deviner —, puis le journal.

```
AVANT : 6 anomalies, dont 1 faux « MORT »
APRES : collecteurs frais 20 · figes 0 · MORTS 0 · AUCUNE anomalie
```

5 tests, dont un qui vérifie que **le vrai mort reste détecté** : sans battement, sans ruban frais
et sans processus, l'anomalie doit toujours sortir. Une correction qui rendrait le contrôle
complaisant serait pire que le bruit qu'elle supprime.

### Le harnais des `.cmd` : un verdict devenu lisible

Les cinq lanceurs de la passe sûre ressortaient tous « A VOIR », avec 5 à 12 lignes `CRITIQUE`
chacun — **aucune réelle** : `0 refus encaisse(s)`, `status="SUCCESS"` contenant le mot
`critical`, `0 reconnexions`, et les rapports qui *parlent* d'erreurs comptés comme erreurs du
lanceur. Le tri de `rapport_collecteurs` est désormais **importé** par le harnais : une seule règle
dans le dépôt, impossible de les faire diverger.

Deux lignes `CRITIQUE` venaient de **mes propres messages** (`[rattrapage] REFUS :` pour un état
normal, et une explication contenant « ne refuse pas »). Plutôt qu'émousser un détecteur qui a
raison de surveiller ces mots, j'ai corrigé les formulations : deux rattrapages simultanés sont un
ÉTAT attendu (`DEJA EN COURS`), pas un échec.

Reste une ligne `CRITIQUE` **vraie et attendue** : `ALINA_SYNC_FAIL: local CODE files were
modified`. C'est le garde-fou qui fonctionne — il refuse de synchroniser par-dessus du code
modifié non commité, ce qui est exactement l'état du dépôt.

### « Le labo n'est pas prêt pour autant de données » — mesuré, et c'était vrai

Question de Florent, vérifiée plutôt que supposée. Ce que le chemin principal chargerait sur le
coffre du 16/11 au soir :

```
REPLAY (fills + carnets)  1 896 shards |  59 832 338 lignes | 4,08 Go compresses | ~13,9 Go en RAM
SIGNAUX de contexte       2 851 shards |  90 829 507 lignes | 3,99 Go compresses | ~21,1 Go en RAM
TOTAL                     4 747 shards | 150 661 845 lignes | 8,07 Go compresses

Machine : 31,92 Go, dont ~9 Go libres pendant la campagne.
```

**~13,9 Go à charger dans 9 Go libres, et `_charger_tier_local` n'avait AUCUNE garde** : ni
plafond de lignes, ni gouverneur mémoire, ni fenêtre de temps. Il chargeait, et la machine
mourait — exactement ce qui a tué les deux passes du 15/11.

Trois gardes ajoutées, chacune testée :

1. **FENÊTRE** (`depuis_ms`) — un shard entièrement antérieur n'est **ni décompressé ni hashé**.
   C'est le réindexage de ce soir qui le rend possible : tous les shards ont enfin des bornes.
2. **PLAFOND** (`MAX_LIGNES_MATERIALISEES = 8 000 000`, ~2 Go) — au-delà, on s'arrête et on
   publie `chargement_arrete = "PLAFOND_LIGNES"` avec le nombre de shards non lus. Une troncature
   **silencieuse** serait pire que l'arrêt : on mesurerait sur un échantillon inconnu.
3. **MÉMOIRE** — le gouverneur est interrogé tous les 20 shards ; sur ROUGE, le chargement
   s'arrête avec `MEMOIRE_CRITIQUE`. « On ralentit ou on rétrécit, on ne crashe JAMAIS. »

Un quatrième test vérifie que **tant qu'aucune garde ne mord, le comportement est inchangé** : ces
protections ne doivent rien modifier au cas normal.

Ce qui reste ouvert : le plafond de 8 M lignes signifie qu'une étude portant sur tout le corpus
sera **tronquée et le dira**. La bonne réponse n'est pas de lever le plafond mais d'utiliser la
fenêtre — c'est précisément ce que `coffre_tranches` permet maintenant, famille par famille.

---

## 16/11/2026 (3e passe) — EXPLOITER LA MINE : fouille par galeries, et une horloge manquante

### Le défaut mesuré : 37 millions de lignes invisibles au trancheur, en silence

`coffre_tranches.HORLOGE_PAR_FAMILLE` ne couvrait que **9 familles sur 23** et `horloge_de()`
repliait sur `ts_ms`. Or trois familles n'ont pas ce champ — vérifié en ouvrant une ligne de chaque
famille du coffre :

| famille | lignes | horloge réelle | `ts_ms` présent |
|---|---:|---|---|
| `bbo` | 30 392 168 | `recv_wall_ts_ms` | **non** |
| `book_l2` | 6 956 689 | `exchange_ts_ms` | **non** |
| `venue_book` | 200 984 | `snapshot_ts_ms` | **non** |

Dans `charger()`, un instant absent valait `continue`. Le trancheur — l'outil même écrit pour
rendre le coffre exploitable — **ignorait donc chaque ligne de carnet et de cotation et rendait
`n=0` sans aucun motif**. Les deux familles les plus lourdes du replay PnL étaient hors d'atteinte,
et un appelant ne pouvait pas distinguer « aucune donnée dans cette fenêtre » de « je n'ai rien su
lire ». Le module avertissait lui-même de ce risque dans son docstring (« même table que le
scelleur : si les deux divergent... ») : la table avait divergé sans que personne ne le vérifie.

**Corrigé** : table alignée sur `sceller_coffre_local._ts_primaire` pour les 23 familles, replis
déclarés par famille (`trades_marche` seule, comme le scelleur), lignes non datables **comptées**
(`lignes_sans_horloge`) au lieu d'être jetées, et un test refuse qu'une famille indexée n'ait pas
d'horloge déclarée.

### Le plan de fouille : 162 286 723 lignes en 35 galeries

| | shards | lignes | compressé |
|---|---:|---:|---:|
| corpus LOCAL (23 familles) | 5 427 | **162 286 723** | 9,55 Go |
| dont replay PnL (fills + carnets) | 1 925 | 60 649 737 | 4,1 Go |

Le pont du labo plafonne à 8 M lignes matérialisées : il voit **5 % du corpus**, honnêtement
déclaré (`chargement_arrete = PLAFOND_LIGNES`). Lever le plafond tuerait la machine — la règle est
« on ralentit ou on rétrécit, on ne crashe JAMAIS ». `src/hl_observer/backtesting/plan_de_fouille.py`
découpe donc l'axe du temps en **galeries** dont chacune tient dans le budget du moment :

* budget dérivé de la RAM **réellement libre** via `ops.budget_ram`, facteur de pression inclus ;
* galeries contiguës et disjointes, bornes inclusives, `galerie[i].fin_ms + 1 == galerie[i+1].debut_ms` ;
* `couverture()` revérifie trous ET recouvrements — un trou perdrait des lignes, un recouvrement
  les compterait deux fois, et les deux falsifieraient toute mesure agrégée ;
* densité mesurée sur l'index (`deposes` réparti sur la durée du shard) : les galeries s'adaptent,
  **12 842 h** pour la queue clairsemée d'avril, **1,5 h** à l'extrémité dense du 16/11 ;
* une galerie qu'on ne peut pas découper est émise seule avec `indivisible=True` — jamais déguisée.

Mesure sur le coffre réel : **35 galeries** couvrent les 162 286 723 lignes (budget 4,74 M), plan
calculé en 2,3 s, couverture complète, écart estimation/index de **4 lignes sur 162 millions**.

Pièces annexes livrées avec :

* `coffre_tranches.flux()` — lecture **en flux**, mémoire plate quel que soit le corpus ;
  `charger()` n'est plus que ce flux matérialisé sous plafond (un seul chemin de lecture) ;
* cache SHA par `(chemin, mtime_ns, taille)` — un shard traversé par plusieurs galeries n'est hashé
  qu'une fois ; si le fichier change d'un octet, la clé change et l'empreinte est recalculée ;
* `_charger_tier_local(..., jusqu_ms=...)` — **la borne haute manquait** : sans fin, une fenêtre ne
  pouvait pas être une galerie, donc le corpus restait inaccessible autrement qu'en une charge
  tronquée ;
* `plan_de_fouille.parcourir()` — journal `fsync` après chaque galerie : Ctrl+C coûte au pire la
  galerie en cours, une reprise saute celles déjà faites ;
* `plan_de_fouille.agreger()` — somme les entiers, fusionne les histogrammes, unit les listes, et
  **refuse** un flottant isolé (`non_agregeable`). Une moyenne de moyennes de tailles différentes
  est un faux, et un faux muet est pire qu'un trou déclaré ;
* `tools/fouille_coffre.py` — `--plan` (aucun shard ouvert) et `--recenser` (parcours réel).

### Une seconde mine, plus grosse, et surtout fermée par la constitution

Le journal du rattrapage a révélé un **magasin de ticks natifs** absent de `LOCAL_INDEX.json`,
donc hors de portée du pont du labo : **467 503 shards, 56,70 Go, 213 098 020 événements**,
vérifiés par SHA-256 et référencés en place. Classé flux par flux :

| motif | flux | événements | taille |
|---|---:|---:|---:|
| `DISABLED_BY_SCOPE:cross_venue` | 15 | 172 192 194 | 50,81 Go |
| `HYPERLIQUID_NATIF_NON_SCELLE` | 8 | 41 265 015 | 5,89 Go |
| `VIDE_AUCUNE_OBSERVATION` | 12 | 0 | 0,00 Go |

**50,81 Go — 85 % du magasin — sont Binance, Bitget, Bybit et Gate.** La constitution ferme la
famille économique Cross-Venue ; les lire pour Copy-Vault rouvrirait par un détour un scope fermé,
exactement le motif qui exclut déjà `venue_book` du pont de replay. Ce n'est pas un câblage
manquant, c'est une décision, et elle est maintenant écrite.

La part Hyperliquid (5,89 Go) est **déjà au coffre sous forme scellée et réduite** : la famille
`bbo` porte déjà `connection_id` et `event_id`, les champs dont la chaîne causale a besoin. Son
seul apport résiduel serait `gap_count` et `local_monotonic_ns` — à sceller **si** une étude les
exige, pas par principe.

### Ce qui reste ouvert, et ce que ça ne prouve pas

* Le plan rend le corpus **atteignable**, il ne mesure **aucune économie**. Le verdict économique
  est inchangé : `REJECTED` pour la copie rapide et la copie miroir, `MORE_DATA` pour les
  opérateurs lents (`position` ne couvre que 5–6 jours sur les ≥ 20 requis).
* L'estimation de densité suppose l'uniformité **dans** un shard, ce qui est faux au détail :
  `parcourir()` publie donc l'écart entre estimation et lignes réellement lues.
* Le rattrapage s'est arrêté à 20:20 sur `MEMOIRE_CRITIQUE` (2,96 Go libres, 9 %) — **le
  gouverneur a fait son travail** : scellement effectué (code 0, 131 s), 160 021 données gardées,
  0 écartée, +23 571 jours-coins de funding gagnés. Il reste 17 458 jours-coins à creuser.

**Tests** : 25 nouveaux (13 `test_plan_de_fouille`, 6 `test_coffre_tranches`, 5
`test_fouille_coffre`, 1 `test_lab_coffre_injection`). **135 verts** sur la sélection coffre/labo.

### Le recensement a tourné sur TOUT le corpus — résultat mesuré

Premier parcours complet du coffre, 21 galeries, **71 minutes**, mémoire plate (0,05 Go) pendant
que la campagne de collecte tournait :

```
etat          : COMPLET   (21 galeries faites, 0 reprise, 0 restante)
lignes lues   : 163 053 257   (estimees 163 053 259 -> ecart -0,00 %)
lignes non datables : 0
shards ouverts : 11 978        (pour 5 427 shards : les shards a cheval sont relus)
jours couverts : 2 281         du 2020-08-19 au 2026-11-16
coins vus      : 1 396
shards refuses : aucun         (SHA-256 verifie sur chacun)
```

Trois choses que ce run prouve et qu'aucune lecture de code ne prouvait :

1. **Le correctif d'horloge tient sur les 22 familles** : `bbo` rend 30 551 552 lignes et
   `book_l2` 6 988 954 — l'ancien trancheur en rendait **zéro**. Et `lignes_non_datables = 0` sur
   163 millions : aucune famille ne perd de lignes faute d'horloge déclarée.
2. **La couverture est exacte, pas approximativement exacte** : 2 lignes d'écart sur 163 millions
   entre l'estimation de densité et les lignes réellement lues, zéro trou, zéro recouvrement.
3. **L'intégrité du coffre est entière** : 11 978 lectures de shard, SHA-256 revérifié, **aucun
   refus**.

Le recensement est écrit dans `runtime/coffre_certifie/FOUILLE_RECENSEMENT.json` : il donne à une
étude, jour par jour et famille par famille, la fenêtre à demander. Densité mesurée des jours
récents, qui dit où chercher : **13/11 = 34 053 223 lignes**, 14/11 = 28 950 912,
15/11 = 27 000 726, 16/11 = 24 819 711.

Reste ouvert, et c'est une optimisation, pas un défaut : **11 978 ouvertures pour 5 427 shards**
(facteur 2,2). Un shard à cheval sur deux galeries est décompressé deux fois — le cache SHA évite
le re-hachage, pas la décompression. Des galeries alignées sur les frontières de shards
supprimeraient ce surcoût au prix de galeries moins régulières.

---

## 17/11/2026 — ITÉRATION 1 : le tunnel mesurait un tampon de lecture, pas la donnée

### Le défaut

`tools/tunnel_executabilite.py` ne lisait que la **queue** des rubans vivants, bornée par un budget
d'octets. Mesure du jour sur les rubans réels (`--octets-fills 120000000
--octets-carnets 400000000`) :

```
fenetre de carnets : 652.4 min            fills : ~3 jours
D_signal_d_ouverture  43 793
E_jugeable            8 554  (19,5 %)
HORS_FENETRE_DE_MESURE   35 239 refus     =  80 % du verdict
```

**Quatre cinquièmes des refus décrivaient la taille de mon tampon de lecture**, pas une propriété
des données. Et le défaut était structurel, pas un mauvais réglage : le labo mesure sur le COFFRE
(6 988 954 lignes de carnets, 21 jours) tandis que le tunnel mesurait sur le ruban vivant. Les deux
dénominateurs ne pouvaient donc pas être réconciliés — précisément ce que la condition de fin
exige de fermer. Vérifié en plus : **personne ne consommait la sortie du tunnel** (`grep` sur tout
le dépôt : une seule mention, dans un commentaire).

### La correction

Le tunnel lit désormais la **même chaîne depuis le coffre certifié**, par shards sélectionnés sur
les bornes de l'index, via `coffre_tranches.flux` (mémoire plate). Une seule boucle de jugement
sert les deux sources — un test l'impose (`source.count("for fill in fills:") == 1`), sinon les
chiffres cesseraient d'être comparables.

Deux horloges, déclarées dans le rapport : les shards se **sélectionnent** sur l'horloge d'index
(celle du scelleur), la causalité se **mesure** sur `received_at_ms`, l'instant où l'observateur a
su. L'écart est le retard d'observation, qui insère légèrement la fenêtre mesurée dans la fenêtre
sélectionnée.

### Après, sur le coffre, fenêtre 13 → 17/11

```
A_lignes_lues            10 275 086
C_fill_live_non_snapshot    165 552
D_signal_d_ouverture         88 131   100,0 %
E_jugeable                   88 131   100,0 %   <- HORS_FENETRE = 0
F_reference_pre_signal       88 041    99,9 %
G_carnet_d_entree            87 985    99,8 %
H_sortie_observee            87 844    99,7 %

age du carnet de reference : median 4 278 ms | p90 10 205 ms | max 20 495 ms
leaders : 31 distincts, 31 avec chaine complete
par jour : 13/11 10 467 | 14/11 15 055 | 15/11 22 541 | 16/11 31 006 | 17/11 9 062 (partiel)
```

**87 844 ouvertures causalement complètes** — 4,2× l'échantillon de 21 060 du 16/11, mesuré sur la
source même du labo. Et deux faits nouveaux rendus visibles par le changement de source :

* `PAS_LIVE_WS = 10 102 027` : la très grande majorité des fills scellés ne sont pas des WS
  causaux (LIVE_POLL, TWAP, backfill). Ce n'est pas un défaut, c'est le dénominateur réel de la
  copie rapide, et il était invisible tant qu'on lisait la queue du ruban live.
* La liaison pré-signal n'est possible qu'à partir du **13/11** : mesuré sur les shards `book_l2`,
  `connection_id` et `l2_gap_epoch` sont présents sur **0,0 %** des lignes avant le 13/11 et sur
  ~100 % ensuite (89,9 % le 16/11, 96,4 % le 17/11, le reste venant du repli REST, correctement
  non liable). La fenêtre admissible à une preuve causale est donc de **5 jours**, pas de 21.

### Tests

`tests/test_tunnel_source_coffre.py`, 5 tests : chaîne complète depuis le coffre ; fenêtre devenue
propriété des données ; shard au SHA divergent **visible** (un tunnel « complet » sur un corpus
amoindri serait un faux) ; règle de jugement unique pour les deux sources ; horloges déclarées.

---

## 17/11/2026 — ITÉRATION 2 : la source de prix mentait sur sa provenance

### Le défaut

Dans `tools/etude_copiabilite.py`, le choix de la source de prix s'écrivait :

```python
price="mids" if "--prix" in (argv or sys.argv) and args.prix == "mids" else "bougies"
```

Les prix **observés** n'étaient donc utilisés que si l'opérateur tapait explicitement `--prix mids`.
En omettant l'option — pourtant documentée comme le DÉFAUT — l'étude retombait **en silence** sur
des bougies 5 min récupérées après coup. Deux études étaient touchées (`--replication-350` et
`--positions`). Le défaut annoncé mentait, et il mentait vers la source de **moindre provenance** :
l'inverse de fail-closed.

Vérifié avant de corriger : `build_candle_panel` ne fait **aucun look-ahead** (la clôture n'est
publiée qu'à `ouverture + intervalle`, provenance marquée `..._RETROSPECTIVE`). Le défaut n'est donc
pas une fuite d'information, mais une perte de résolution et une provenance fausse.

### Ce que ça coûtait, mesuré avant/après sur le MÊME corpus figé

| mesure | bougies 5 min | allMids observés |
|---|---:|---:|
| net moyen | −0,967 USD/jour | **−0,185 USD/jour** |
| sur capital | −27,63 bps/jour | **−5,28 bps/jour** |
| IC 95 % | [−2,77 ; +0,63] | [−1,31 ; +0,81] |
| points de prix | 6 832 | **112 729** |
| jours-leader | 436 | 413 |

La valorisation grossière **surestimait la perte d'un facteur 5** et fabriquait une queue de pertes
extrêmes : le pire leader passait de −21,06 à −8,94 USD/jour. Le sens de l'erreur n'excuse pas
l'erreur ; le verdict reste `MORE_DATA` (5 journées distinctes pour 20 requises).

### La correction

`_panneau_de_prix()` : la source demandée **est** la source utilisée. Si la source observée est trop
pauvre (< 1 000 points), on rend `UNMEASURABLE` en **nommant** le repli explicite (`--prix prints`)
et en disant ce qu'il changerait (péremption 360 s contre 120 s). Jamais de repli pris soi-même.

**Tests** : `tests/test_etude_source_de_prix.py`, 5 verts.

---

## 17/11/2026 — ITÉRATION 3 : le tableau par leader n'avait aucun correctif d'essais multiples

### Le défaut

Le rapport de réplication classait 105 leaders par net/jour et affichait **+18,85 USD/jour sur
350 USD** en tête, soit **+539 bps/jour**. Aucune correction. Prendre le maximum de 105 comptes sur
4 jours produit un sommet élevé même sans aucune compétence — et c'est ce sommet que l'œil retient.
Une politique gelée depuis ce tableau aurait gelé du bruit de sélection.

### La correction

`borne_du_hasard_replication()` compare le meilleur leader RÉEL au meilleur leader **sous placebo**,
en réutilisant `overfit_selection.borne_du_hasard` (déjà écrite, déjà déboguée : elle compare
`max_reel > p95` quel que soit le signe).

**Le null** : le portefeuille EXACT du leader, confronté au chemin de prix d'un AUTRE jour
(décalages −72, −48, −24, +24, +48, +72 h). Coins, tailles, notionnels, rotation, ordre minimal et
frais : identiques. Seul l'alignement décision → prix est détruit.

**Marge additive, et non zéro.** Dépasser le p95 du hasard de 0,50 USD/jour sur 4 jours n'est pas
une preuve : c'est sous le bruit de mesure. La marge est la **demi-largeur de l'intervalle à 95 %**
du net moyen, mesurée sur les mêmes données — pas un seuil choisi à la main. La section se lit
**avant** le tableau par leader : la mettre après équivaudrait à l'enterrer.

**Tests** : `tests/test_replication_essais_multiples.py`, 6 verts.

---

## 17/11/2026 — ITÉRATION 4 : personne n'avait mesuré combien de temps les leaders tiennent

### Le défaut

Tout le modèle de copie rapide repose sur un horizon de détention que **nous** choisissons : le
tunnel mesure la sortie à `entrée + 300 s`, `copy_vault_v5_lifecycle_train` explore une grille de
`max_hold_ms`. Recherche sur tout le dépôt : aucune mesure de la durée réelle. Or le vocabulaire du
coffre la rend directement calculable — mesure du 17/11 sur une journée :

```
Close Long  152 219     Open Short  140 446     Short > Long  4 380
Close Short 146 040     Open Long   137 308     Long > Short  4 295
```

### La mesure

`src/hl_observer/backtesting/copy_vault_detention.py` apparie les ouvertures et les clôtures en
**FIFO par (compte, coin)**, en taille, avec les retournements. Une position encore ouverte en fin
de fenêtre est **CENSURÉE** — jamais une durée nulle. Une clôture sans ouverture observée est une
troncature à gauche, déclarée. Une étiquette inconnue (`Sell`, `Buy`) est comptée et n'apparie rien.

Journée du 16/11, 1 660 493 fills, 1 231 050 paires appariées, part censurée 12,2 % :

```
p10   2,4 min        p50  44,8 min        p90   5,53 h
p25  10,7 min        p75   2,27 h         p99  14,74 h
médiane pondérée par la taille : 30,9 min
160 comptes sur 163 ont une médiane supérieure à 300 s
```

Journée du 17/11 (câblée dans le tunnel, 431 945 paires) :

```
p50 35,9 min · médiane pondérée 60,1 min
horizon du tunnel = 5,0 min = 0,139 fois la médiane réelle
140 comptes sur 148 tiennent PLUS longtemps que l'horizon
```

### Ce que cela change

L'horizon de 300 s tombe **entre le p10 et le p25**. Il ne modélise pas la stratégie des leaders
observés mais une autre, bien plus courte — et sur 9,0 bps de frais aller-retour, la durée de
détention est précisément ce qui décide si les frais s'amortissent. Cela n'invalide pas le tunnel
(il mesure l'observabilité d'une sortie à horizon fixe), mais il interdit de lire « 99,7 % de
chaînes complètes » comme « 99,7 % de stratégies réalistes ». Les deux chiffres sont désormais
publiés côte à côte dans le même rapport.

Fait notable : la médiane pondérée par la taille (60,1 min) tombe exactement sur la cadence de
réalignement de 60 min de l'étude de réplication — la seule hypothèse non réfutée.

**Tests** : `tests/test_copy_vault_detention.py`, 11 verts (FIFO, réduction partielle,
retournement, censure, troncature à gauche, étiquette inconnue, pondération par la taille, horloge
choisie par l'appelant).

### Un défaut d'outillage trouvé au passage

La suite de tests **complète ne peut pas s'exécuter localement** : le fixture `indexed_catalog_audit`
de `tests/test_dataset_policy.py` valide tout le catalogue de données (1,9 M fichiers) et dépasse
tout délai raisonnable. La référence est donc établie avec `--ignore=tests/test_dataset_policy.py`,
et ce test doit être relancé seul, avec son propre budget.

### ITÉRATION 3, mesurée : le sommet du tableau est du bruit de sélection, et le hasard fait MIEUX

Réplication 350 USD, prix observés, placebos par décalage temporel :

```
decalage  leaders  jours   max USD/j   mediane       min
 -72 h       104      4      20.311     0.000   -17.638
 -48 h       104      4      34.632    -0.384   -22.587
 -24 h       104      4      12.797    -0.845   -11.076
 +24 h       104      4      16.556     0.000   -14.433
 +48 h       104      3      15.687     0.088   -16.164
 +72 h       112      2      14.955    -0.289   -18.349

meilleur REEL   : +18.849 USD/j   (parmi 105 comptes)
hasard moyenne  : +19.156 USD/j   p95 : +34.632 USD/j
VERDICT         : LE_TOP_EST_INDISCERNABLE_DU_HASARD
ensemble        : net -0.185 USD/j · IC95 [-1.314 ; +0.809] · MORE_DATA
```

**La moyenne des maxima sous placebo (+19,156) est quasi identique au maximum réel (+18,849)** —
signature exacte d'un pur bruit de sélection. Et le p95 du hasard (+34,632) *dépasse* le réel : sur
4 jours, choisir le meilleur de 105 comptes produit un sommet plus élevé quand on détruit tout lien
entre les décisions du leader et les prix. Chaque placebo a par ailleurs une médiane ≈ 0
(−0,845 à +0,088), cohérente avec le net d'ensemble de −0,185.

Ce run a été lancé avant l'ajout de la marge de bruit : il porte donc `marge_usd = 0`. Le verdict
ne s'en trouve pas affecté (l'écart au p95 est de **−15,783 USD/jour**, du mauvais côté), mais le
prochain run portera la marge dans son rapport.

---

## 17/11/2026 — ITÉRATION 5 : ma propre mesure de détention comptait des fills en double

### Le défaut, dans l'outil que je venais d'écrire

`fills_forward` contient le même fill d'échange observé par plusieurs sources. Mesuré sur la
journée du 17/11 : **618 264 lignes pour 579 363 fills distincts**, soit 6,3 % de doublons entre
`LIVE_POLL` (596 102), `LIVE_WS` (20 338) et `LIVE_TWAP` (1 824). Ma première version de
`apparier()` ne dédupliquait pas : une ouverture vue deux fois remplissait deux fois la file FIFO.

### Le piège qui aurait fait bien pire

On ne peut **pas** dédupliquer sur `hash` :

* `stable_event_id` n'existe que sur les lignes `LIVE_WS` — **20 338 sur 618 264, soit 3,3 %** ;
* `hash` est le hash de **transaction**, pas du fill : **83 862 hashes portent plusieurs lignes**,
  et le hash sentinelle `0x0000…0000` en porte **40 915** (les sous-fills d'un TWAP). Dédupliquer
  dessus aurait écrasé 40 915 fills distincts en un seul.

Au passage, vérification du tunnel : il déduplique sur `stable_event_id or hash` **après** son
filtre `LIVE_WS`, et toutes les lignes `LIVE_WS` portent un `stable_event_id`. Son appariement est
donc sain — le défaut n'était que dans mon module.

### Correction et effet mesuré

Clé d'identité = `stable_event_id` s'il existe, sinon la clé NATURELLE d'échange
`(compte, coin, horodatage, taille, prix, sens)`. La source n'y entre pas : c'est précisément ce
qu'on veut réunir.

Journée du 16/11, 1 660 493 lignes, **54 304 doublons écartés** :

| mesure | sans dédup | avec dédup |
|---|---:|---:|
| paires appariées | 1 231 050 | 1 189 640 |
| p25 | 10,7 min | 11,7 min |
| **p50** | **44,8 min** | **46,6 min** |
| p75 | 2,27 h | 2,30 h |
| médiane pondérée par la taille | 30,9 min | **35,3 min** |
| part censurée | 0,1221 | 0,1225 |

Les doublons biaisaient la détention **vers le bas** : +4 % sur la médiane simple, **+14 % sur la
médiane pondérée par la taille**. La conclusion de l'itération 4 se renforce : l'horizon de 300 s
du tunnel vaut **10,7 %** de la détention médiane réelle.

**Tests** : `tests/test_copy_vault_detention.py` passe de 11 à **16 verts** (même fill vu par deux
sources, clé naturelle quand `stable_event_id` manque, hash sentinelle jamais utilisé comme
identité, prix distinct = fill distinct, désactivation déclarée).

---

## 17/11/2026 — ITÉRATION 6 : un seul refus de débit tuait encore deux passes sur trois

### Le défaut, mesuré en production

Le rattrapage `--long` lancé le 16/11 à 23:39 (budget 12 h) s'est terminé à 01:08 — **1 h 29**.
Aucun arrêt mémoire (`arret_memoire = None` partout : le correctif de patience tient). Mais :

```
[funding] R5   30/62 CAKE   + 499 points | remonte a 981 j | 36 min ecoulees, 334 restantes
[funding] ARRET : LIMITE_DEBIT -> la passe suivante reprend ici
gagnes  : funding-profond 6 800 jours-coins     restant : 9 872 jours-coins
```

`funding-profond` s'est arrêté à la ronde 5 sur **un unique refus** à 600 u/min, avec **334
minutes** de budget inutilisées. Le correctif du 16/11 (« deux refus ne doivent pas tuer la
passe ») n'avait été posé que sur **un site sur trois** :

| site | avant | après |
|---|---|---|
| funding, front AVANT | 5 refus avec recul géométrique | inchangé (via le helper) |
| funding, front de CREUSAGE | arrêt au **1er** refus | 5 refus avec recul |
| bougies | arrêt au **2e** refus | 5 refus avec recul |

### La correction

La règle vit désormais à un seul endroit, `avec_recul()`, que les trois sites appellent : chaque
refus divise le débit (`cadence.refus()`) et allonge l'attente ; abandon après
`REFUS_AVANT_ABANDON` refus **consécutifs** seulement, nombre publié dans le bilan.

Défaut attrapé à la relecture, dans ma première version du helper : il rejouait la requête
**immédiatement** après le refus, avant toute attente — l'inverse du but, et le comportement qui
fait bannir. Le helper reçoit maintenant le premier résultat déjà obtenu et ne rejoue jamais sans
avoir dormi ; un test verrouille l'ordre exact `dort, appel, dort, appel`.

Un test existant encodait l'ancien contrat sous le nom « on n'insiste pas »
(`siestes == [ATTENTE_REFUS_S]`). Il est renommé et **durci** : attentes croissantes exactes, une
par refus, et `refus_consecutifs` publié.

**Tests** : `tests/test_recul_sur_refus_de_debit.py`, 8 verts (helper ×3, creusage ×2, bougies ×2,
unicité du helper) ; 106 verts sur les suites rattrapage / backfill / débit.

### RECTIFICATION — ce que la mesure de détention NE rouvre PAS

Après l'itération 4, j'ai présenté « mesurer la dérive jusqu'à la sortie réelle du leader » comme
la prochaine expérience à tenter. **C'était une erreur de cadrage, relevée en relisant
`docs/LOIS_MESUREES.md`** : cette expérience existe déjà sous le nom `copy_miroir_episodes`
(« entrée à l'ouverture, sortie à la clôture »), mesurée le 11/11 :

```
205 601 épisodes reconstruits ; 47,2 % déjà clos quand leur ouverture est devenue observable
29 620 copiables et mesurables : brut +0,05 bps, coûts 12,3 bps, net −12,2 bps, 38,3 % gagnants
net moyen par opérateur −8,0 bps, IC 95 % [−11,7 ; −3,8] sur 53 opérateurs
```

Elle est **réfutée**, et sa condition de réouverture est écrite : « un univers d'opérateurs LENTS
(rotation ≤ 3× l'exposition par jour) dont la réplication d'inventaire gagne en marche avant sur
≥ 20 jours indépendants ». La mesure de détention ne satisfait pas cette condition ; elle ne
rouvre donc rien.

De même, l'étude d'événements (`copy_vault_event_study`) mesure déjà des horizons de **1 h, 4 h
et 24 h** avec témoins à −7 et −14 jours. Dire que « le labo mesurait à 300 s » n'était exact que
pour le tunnel et pour `copy_vault_v5_lifecycle_train`, pas pour le labo dans son ensemble.

**Ce que la détention apporte réellement**, et rien de plus :

1. une mesure **par compte** de la lenteur (détention médiane), indépendante de la rotation, qui
   peut servir à définir ex ante l'univers lent exigé par la condition de réouverture — à condition
   de n'être calculée que sur des jours **antérieurs** à ceux où l'on mesure ;
2. l'interdiction de lire le « 99,7 % de chaînes complètes » du tunnel comme une preuve de
   réalisme stratégique : l'horizon du tunnel est un choix d'observabilité.

Écart à expliquer et non à ignorer : 47,2 % d'épisodes « déjà clos à l'observation » le 11/11,
contre un p10 de détention de 2,5 min le 16/11. Les deux mesures ne portent pas sur le même
univers (le 11/11, 61,8 % des fills venaient d'opérateurs à haute fréquence, archivés depuis ; les
abonnements ont été réalloués aux signaux copiables au chantier 3) ni sur la même unité (épisode
plat-à-plat contre tranche FIFO pondérée par la taille). Aucune des deux n'invalide l'autre.

---

## 17/11/2026 — La condition NÉCESSAIRE de l'hypothèse ouverte, rejouée sur le coffre du jour

L'étude de persistance (`copy_vault_persistence`, marche avant, point dans le temps) répond à la
question dont dépend toute copie lente : un vault bien noté sur son passé fait-il mieux ensuite ?
Rejouée le 17/11 — `tools/etude_copiabilite.py --persistance` :

```
2 345 vaults avec courbe (dont 1 864 fermés : biais de survie réduit, non supprimé)
87 dates mesurables · 102 vaults par date (médiane) · 28 configurations essayées,
intervalles élargis en conséquence (niveau 0,9982)

corrélation de rang  note -> rendement suivant : +0,016  [-0,032 ; +0,059]
meilleur quantile - « copier tout le monde »   : -1,05 bps/jour [-15,92 ; +13,04]   placebo p = 0,541
leaders LENTS seulement (787 vaults, 87 dates) : IC +0,009 [-0,049 ; +0,062]
                                                 net +0,39 bps/jour [-11,05 ; +11,64]
modèle de sélection appris en marche avant     : IC +0,003 [-0,061 ; +0,072]   placebo p = 0,485
référence « copier tous les vaults »           : +4,49 bps/jour (brut)
```

Verdicts : `copy_vault_leader_skill_persistence` **MORE_DATA**, `copy_vault_leader_selection_model`
**MORE_DATA** — les intervalles sont à cheval sur zéro, donc ni établis ni réfutés. Ce qu'ils
bornent tout de même : la corrélation de rang ne dépasse pas +0,059, et le placebo fait aussi bien
que la note une fois sur deux.

Deux effets ont un signe stable d'une date à l'autre, à garder pour la suite sans leur prêter plus
que leur taille : `anciennete` (+0,043, même signe sur 100 % des dates) et `volatilite_12`
(−0,027, 85 % des dates).

Limite déclarée du rapport, reprise telle quelle : le net de la tête de classement est « n/d »
parce que la rotation n'est connue que pour 1 743 vaults sur 2 345 — rotation inconnue = coût
inconnu, jamais zéro. C'est le comportement fail-closed voulu, pas un défaut.

**Repère d'échelle, sans conclusion** : +10 USD/jour sur 350 USD représentent 285,7 bps/jour. La
seule référence brute mesurée ici, « copier tous les vaults », est de +4,49 bps/jour.

---

## 17/11/2026 — ITÉRATION 7 : la suite COMPLÈTE n'avait jamais tourné sur ce HEAD

### Le constat

Les sessions précédentes validaient par sélections (`-k ...`). La suite entière ne pouvait pas
s'exécuter : le fixture `indexed_catalog_audit` de `tests/test_dataset_policy.py` valide tout le
catalogue (1,9 M fichiers) et dépasse tout délai. Lancée sans lui, sur 4 ouvriers
(`-n 4 --dist loadfile`), elle rend en 22 min 43 s :

```
18 697 réussis · 23 échoués · 63 ignorés · 1 xfail
```

Rejoués en série, **12 échecs sont confirmés**. Dix étaient réparables ; six venaient de mes
propres ajouts des sessions précédentes.

### Les dix défauts corrigés

| # | défaut | origine | correction |
|---|---|---|---|
| 1 | 3 `except: pass` muets (`copy_vault_tier_local`, `plan_de_fouille`, `verrou_pid`) | mes ajouts | `_noter_echec(site, exc)` : même comportement, mais compté |
| 2 | `os.kill(pid, 0)` nu dans `ops/verrou_pid.py` | mes ajouts | passe par `runtime_guards._existe_sous_posix`, physiquement inexécutable sous Windows |
| 3 | 4 fichiers au-dessus de leur plafond de taille | sessions 15–17/11 | **extraction**, aucun plafond relevé (voir ci-dessous) |
| 4 | `CERTIFIER_EN_CONTINU.cmd` et `RATTRAPAGE.cmd` non enregistrés | classement du 16/11 resté à moitié fait | ajout à `ROOT_SUPPORT_ENTRYPOINTS`, l'ensemble que l'audit lit réellement |
| 5 | même cause, vue par l'inventaire de scope | idem | idem |
| 6 | test de barrière READY_CORE cherchant `if errorlevel 1 (` | test en retard sur le HEAD | aligné sur l'idiome réel, **durci** (capture exigée sur la ligne qui suit l'appel) |
| 7 | test d'ouverture de session, même cause | idem | idem |
| 8 | test « fetch puis fast-forward » | en retard sur le raccourci du 13/11 | double de git avec HEAD **en retard** + test neuf verrouillant le raccourci |
| 9 | test « avance non rapide refusée » | idem | idem |
| 10 | test d'aperçu du moteur git lisant la console | terminal devenu COMPACT | preuve prise dans le **reçu** (`git_commands`), plus durable |

Deux précisions qui comptent :

* **Défauts 6 et 7 — la barrière n'avait pas disparu.** `LANCER_HYPERSMART.cmd` capture
  `%ERRORLEVEL%` dans une variable puis branche dessus, parce que l'appel de journalisation
  intercalé écraserait le code. C'est plus sûr que l'ancien `if errorlevel 1`. Le test vérifie
  maintenant que la capture suit immédiatement l'appel.
* **Défaut 4 — écart avec `AGENTS.md`.** Le contrat écrit dit qu'il ne reste à la racine que les
  quatre lanceurs principaux et `ALINA_SYNC_COMPLETE.cmd`. Le code du HEAD en enregistre déjà
  cinq autres comme lanceurs d'appoint ; ces deux-là suivent ce précédent. La phrase d'`AGENTS.md`
  est donc en retard sur le code — à arbitrer par l'opérateur, pas par moi.

### Les extractions (défaut 3) — aucun plafond relevé

| fichier | avant | après | plafond | extrait vers |
|---|---:|---:|---:|---|
| `backtesting/copy_vault_local_lab.py` | 5 101 | 4 931 | 5 009 | `copy_vault_contexte_tranchable.py`, `copy_vault_chargeurs_safe.py` |
| `collection/copy_vault_checkpoint_tail.py` | 968 | 754 | 800 | `copy_vault_checkpoint_socle.py`, `copy_vault_presignal_lane.py` |
| `backtesting/copy_vault_book_loader.py` | 889 | 800 | 800 | `copy_vault_epoch_parsing.py`, `GAPS.segmenter_l_epoque`, `LIAISON.LecteurBorne` |
| `backtesting/copy_vault_executable.py` | 1 324 | 1 286 | 1 304 | `copy_vault_book_index.py` (recherche par le temps) |

Chaque nom déplacé est réimporté sous son nom d'origine : aucun appelant ni aucun test externe
n'a changé de comportement. Validé par **3 048 tests Copy-Vault** (un seul rouge : `rig_020`).

### Un défaut trouvé en chemin, et il venait de ma méthode d'édition

`git diff --stat` affichait `copy_vault_local_lab.py | 10110 +++---` pour ~120 lignes réellement
changées. Cause : `Path.write_text()` sous Windows traduit `\n` en `\r\n`, et le dépôt est en
`core.autocrlf = false` sans règle `*.py`. **20 fichiers suivis avaient basculé** de fins de
ligne, plus 21 fichiers neufs en CRLF. Un commit aurait noyé les vrais changements, et les
empreintes de fichiers source changeaient sans raison.

Réparé octet pour octet, en restaurant pour chaque fichier la convention **de son HEAD** — le
dépôt les mêle (`copy_vault_checkpoint_tail.py` et `copy_vault_executable.py` sont en CRLF,
`copy_vault_book_loader.py` en LF). Contrôle final : 0 bascule, 0 fichier mixte sur 103 touchés.
Toutes les éditions suivantes passent par `newline=""`.

### Ce qui reste rouge, et pourquoi ce n'est pas réparable ici

1. **`test_rig_020`** — le reçu `AUD-044` est lié à un arbre de travail exact. Condition de levée
   inchangée : commiter, puis rejouer la vérification de la tâche auditée.
2. **`test_windows_checkout_preserves_byte_exact_replay_catalog`** — **13 420 fichiers `catalog/`
   diffèrent du HEAD par leur CONTENU** (pas par leurs fins de ligne) : l'arbre local est plus
   ancien (`attempts 124` contre 133 au HEAD, `code_sha` antérieur). C'est l'état de
   synchronisation des données, que gère AlinaSync. Le réaligner à la main pendant une campagne
   écraserait 13 420 fichiers d'état : c'est une décision d'opérateur.
3. **`tests/test_dataset_policy.py`** — non exécutable dans un délai raisonnable ; à lancer seul
   avec son propre budget.

---

## 17/11/2026 — ITÉRATION 8 : la matrice annonçait 0 shard SAFE pour 15 456 réels (chantier 12)

### Le défaut, dans mon outil du 16/11

Le bloc SAFE de `tools/matrice_coffre.py` lisait `lots` ou `shards` à la racine de
`COFFRE_INDEX.json`. Ces clés n'existent pas : l'index range ses tiers sous `tiers`. La matrice
publiait donc `entrees: 0` — et l'écart qui borne toute preuve restait invisible.

### La réconciliation, désormais reproductible (2 secondes)

```
SAFE : 15 456 shards, 66 releases, dernier tag connu 2026-10-18 00:00
  copy_vault_fills           5 shards SAFE | LOCAL 24 399 868 lignes | LOCAL en avance de 30,5 j
  copy_vault_l2         14 642 shards SAFE | LOCAL  7 874 272 lignes | LOCAL en avance de 30,5 j
  copy_vault_snapshot      609 shards SAFE | LOCAL    354 567 lignes | LOCAL en avance de 30,5 j
  copy_vault_positions     100 shards SAFE | LOCAL  1 041 799 lignes | LOCAL en avance de 30,5 j
premier jour où une référence pré-signal est liable : 2026-11-13
fenêtre causale couverte par SAFE : False
```

`premier_jour_liable()` sonde un shard `book_l2` par jour (200 lignes au plus) et rend le premier
jour où la majorité des carnets portent `connection_id` **et** `l2_gap_epoch` — les deux champs
sans lesquels aucune référence pré-signal ne peut être liée. Mesuré : **2026-11-13**.

### Ce que cela établit, sans conclusion économique

LOCAL sert à explorer ; seule une chaîne SAFE peut soutenir OOS, forward et PnL. Or :

* le tier SAFE s'arrête au **18/10** et ne contient que **5 shards de fills** ;
* la fenêtre où la chaîne causale est complète (liaison pré-signal, fenêtres de trous) commence
  le **13/11** — vingt-six jours après ;
* donc **aucune mesure du labo sur la chaîne réparée n'est aujourd'hui prouvable**, quelle
  qu'en soit la valeur.

**Intervention externe précisément identifiée** : une campagne de collecte cloud
(GitHub-hosted, jamais un runner local) postérieure au 13/11, exécutée avec le code du HEAD
actuel poussé sur `main`, puis sa release et sa restauration par AlinaSync. Le push demande
l'autorisation explicite de l'opérateur.

**Tests** : `tests/test_matrice_coffre.py` passe de 4 à **9 verts** (lecture des tiers, avance de
LOCAL en jours, fenêtre causale postérieure au dernier tag, carnets sans identité de connexion
non liables, index sans tier SAFE dit et non compté pour zéro).

### ITÉRATION 7, confirmée : la suite complète après corrections

Deuxième passage complet, en mode verbeux (chaque test nommé, pour survivre à un crash d'ouvrier) :

```
18 902 réussis · 8 échoués · 68 ignorés · 1 xfail · 31 min 03 s · aucun ouvrier tombé
```

| échec | nature | rejoué seul |
|---|---|---|
| `test_rig_020_all_current_receipts_are_exactly_revalidated` | externe : reçu lié à l'arbre de travail | rouge |
| `test_windows_checkout_preserves_byte_exact_replay_catalog` | externe : 13 420 fichiers `catalog/` en retard sur le HEAD | rouge |
| `test_creer_archive_cmd::test_unknown_argument_fails_without_success_banner` | exécuté pendant que j'éditais des fichiers | **vert** |
| `test_dataset_resume_and_snapshot` (2 tests) | idem | **verts** |
| `test_safety_audit_passes_project_baseline` | idem (il balaie les sources) | **vert** |
| `test_metagraph_and_quality_gates` (2 tests) | trop lents sous charge : 7 min 11 s en série, délai de 600 s dépassé à 4 ouvriers | **verts** |

Ce que ce tableau établit, et ce qu'il n'établit pas :

* **2 échecs sont réels sur ce HEAD, et tous deux externes.** Aucun défaut de code connu ne reste
  rouge.
* **[RECTIFIÉ — explication FAUSSE, voir l'itération 13]** **4 échecs sont de ma faute de
  méthode** : j'ai modifié des fichiers du dépôt pendant que la
  suite tournait. Un test qui balaie les sources voit alors un arbre en mouvement. Ils passent en
  série, mais une suite n'est une référence que si rien ne bouge pendant qu'elle tourne ; je ne
  présente donc pas ce passage comme une confirmation propre de ces quatre-là.
* **[RECTIFIÉ — explication FAUSSE, voir l'itération 13]** **2 échecs sont un problème
  d'outillage** : deux tests de portes de qualité prennent plus de
  sept minutes à eux seuls. Ils ne sont pas faux, ils sont incompatibles avec un délai de 600 s
  sous charge parallèle.

Au passage, le rattrapage relancé à 13:46 a rendu : `[funding] profondeur après cette passe :
min 1100 j | médiane 1101 j | max 1102 j (263/263 coins servis)`. Le funding est donc à pleine
profondeur sur tout l'univers. Précision honnête : cette passe-ci n'a creusé aucune page
(« 0 pages creusées en 0 ronde ») — le reste avait été creusé entre-temps par le passage
périodique de la campagne. Le correctif de recul n'a donc pas été exercé en production
aujourd'hui (0 refus) ; il n'est attesté que par ses tests.

---

## 17/11/2026 — ITÉRATION 9 : plus aucune famille en état d'attente (chantier 10, clôture)

### Le défaut de statut

Six familles restaient `A_CABLER` : « déclarées, en attente d'une hypothèse ». C'était un
troisième état, alors que l'objectif exige pour chaque famille un rôle **consommé et mesuré** ou
une **exclusion motivée**. Brancher ces familles dans un modèle sans hypothèse préenregistrée
ajouterait des essais multiples ; la réponse est une **mesure descriptive** par famille, qui
tranche la seule question utile : cette famille peut-elle seulement changer quelque chose ?

`FAMILLES_A_CABLER` est remplacé par `FAMILLES_A_ROLE_MESURE` : chaque fiche nomme un rôle, la
fonction qui le mesure (un test l'importe : une fiche qui nommerait une mesure inexistante serait
un état d'attente déguisé) et sa limite. Module `copy_vault_roles_familles.py`, mode
`tools/matrice_coffre.py --roles`.

### Les mesures, fenêtre 15 → 17/11 — aucun shard refusé à la lecture

| famille | rôle | mesure |
|---|---|---|
| `trades_marche` | capacité | 13 291 471 trades, 180 coins ; **multiple médian 1,51 ×** l'ordre de 350 USD ; **9 coins (5 %)** à capacité large ; **25 coins** où une minute médiane de marché échange moins que l'ordre |
| `liquidation` | risque | 8 036 événements, 28 comptes, concentrés sur **13 jours** (618 par jour actif) |
| `vault_ledger` | flux de capital | 2 270 jours-compte avec flux sur 43 comptes ; retraits 42,75 % ; **65 456 montants inconnus** |
| `overshoot` | résultat seulement | 175 238 événements ; **100 %** portent des prix du futur → exclue comme entrée de décision |
| `micro_l2`, `micro_trades` | applicabilité | 24 coins ; **10 739 / 67 367 ouvertures copiables = 15,9 %** |

Deux de ces chiffres contredisent ce que je tenais pour acquis :

* **La capacité n'est pas une formalité.** Pour le coin médian, une minute de marché n'échange
  qu'une fois et demie l'ordre paper. Le modèle de coût du labo compte frais taker et demi-écart,
  pas l'impact : sur les coins étroits, son net est donc optimiste. À intégrer comme diagnostic
  de la réplication avant toute lecture de son résultat.
* **La microstructure ne peut peser que sur 15,9 % des ouvertures copiables.** Quelle que soit la
  qualité d'un conditionnement OFI, il est structurellement aveugle aux 84 % restants.

### Défaut de collecteur trouvé par la mesure : des perps délistés pris pour des événements

« Réversion nulle sur 69 % » ne ressemblait pas à un marché. Vérifié :

```
175 238 lignes overshoot
les 4 prix futurs TOUS égaux au prix de l'événement : 117 884  (67,3 %)
RNDR, FTM, FXS, HPOS, UNIBOT, OX, FRIEND, SHIA : 3 693 lignes chacun, 100 % figées
ETH, SOL, HYPE : 0 %
```

Ces huit coins sont des perps **délistés** : mark et oracle y sont figés avec un écart permanent
(RNDR : −191,75 bps). Le seuil de 30 bps était donc franchi à chaque cycle, et
`tools/collecter_overshoots.py` écrivait un « dépassement » toutes les deux minutes, pour
toujours. Deux défauts distincts, tous deux corrigés :

1. le collecteur ignorait `isDelisted`, que `collection/univers_perps.py` applique déjà ;
2. `mf = ev.get(...) or m0` recopiait le prix de l'événement quand le prix futur manquait — une
   observation **absente** devenait une réversion de **0,0**. Elle est maintenant `None`, avec
   `reversion_inconnue = True`.

S'y ajoute une marque `prix_fige` : une ligne dont le prix n'a pas bougé d'un tick est gardée et
étiquetée, jamais écartée en silence. Le collecteur tourne ; la correction prendra effet à son
prochain démarrage, et les 117 884 lignes déjà scellées restent telles quelles — la mesure de
rôle les compte désormais à part (`part_chemins_figes`).

**Tests** : `test_copy_vault_roles_familles.py` 11 verts, `test_collecter_overshoots.py` + 6
(28 verts avec les suites overshoot), registre de familles 72 verts.

---

## 17/11/2026 — ITÉRATION 10 : le contrat de l'instantané exigeait encore 200 USD (chantier 8)

### Le défaut, dans la chaîne de preuve

`src/hl_observer/backtesting/copy_vault_snapshot_contract.py` valide l'instantané de restauration
H-T95, l'artefact dont dépend le reçu de restauration. Il exigeait :

```python
elif capital != 200.0:
    invalid.append("search.paper_capital_usd")
```

Or le labo écrit dans chaque instantané `PAPER_CAPITAL_USD = PAPER_EQUITY_USD`, soit **350,0 USD**
depuis le changement de capital paper, et `AGENTS.md` déclare les 200 USD « historiques et
inactifs ». **Tout instantané émis par le labo actuel était donc refusé par son propre
validateur.** Le test du validateur ne le voyait pas : sa fixture portait `200.0`.

C'est le même défaut de fond que la source de prix de l'itération 2 : deux valeurs pour une même
grandeur, dont l'une n'est lue que par un test. Aucun instantané ne pouvait atteindre `PROVEN`
avec le capital opérationnel.

### La correction

Le capital exigé est lu de la source unique du protocole (`copy_vault_protocol.PAPER_EQUITY_USD`),
celle que lisent déjà le labo et `economic_objective`. Un booléen est refusé explicitement
(`True == 1` en Python). La fixture du test lit la même constante.

Au passage, le message opérateur de `tools/alina_quant_lab_console.py` disait « la limite de
200 USD de capital paper » pour le rejet `COPY_V21_PAPER_GROSS_EXPOSURE_LIMIT_EXCEEDED`. Le seuil
appliqué est `MAX_GROSS_EXPOSURE_USD` = 350 USD ; le message en est maintenant dérivé. Le rejet
lui-même est **juste** : le gel v21 local porte `core_notional_usd = 600`, soit 1,71 fois le
capital sans levier. Il n'existe donc aujourd'hui **aucun gel admissible** pour le moteur paper,
et le moteur refuse de s'en fabriquer un — comportement fail-closed attendu.

Balayage complémentaire des constantes de capital du chemin actif : `PAPER_EQUITY_USD = 350.0`
est la seule source ; `STARTING_CAPITAL_USD` et `PAPER_CAPITAL_USD` du labo en dérivent. Les
`1000.0` de la console sont un gabarit remplacé à l'exécution.

**Tests** : `test_copy_vault_snapshot_contract.py` 4 → **7 verts** (le capital que le labo écrit
est accepté ; l'ancien 200 USD est refusé ; un booléen n'est pas un montant) ;
`test_alina_quant_lab_console.py` + 1 (32 verts).

---

## 17/11/2026 — ITÉRATION 11 : une pré-vérification suffisait à faire taire l'alerte de fraîcheur (chantier 13)

### Le défaut, dans mon contrôle du 16/11

L'alerte de fraîcheur compare la collecte en cours aux horloges de la chaîne de preuve. Deux
faiblesses :

1. `dernier_rapport_labo` était l'**heure d'écriture** du dernier `resultat.json`. Or une simple
   pré-vérification du labo (statut `PREFLIGHT_ONLY`, aucun rejeu) écrit un tel fichier. Le 17/11
   à 12:27, le tunnel annonçait « dernier_rapport_labo = 115,4 h de retard » ; ma pré-vérification
   de 13:36 aurait suffi à le faire passer « frais », **sans qu'une seule donnée ait été rejouée**.
2. L'âge du tier SAFE n'entrait pas dans le verdict, alors que seule une chaîne SAFE peut
   soutenir une preuve.

Un contrôle qu'un geste sans effet peut satisfaire ne contrôle rien.

### La correction

`fraicheur_preuve.horloges_de_la_chaine()` lit les horloges dans les **faits** :

* l'horloge du labo est la **fin des données réellement rejouées** par le dernier rapport qui a
  rejoué quelque chose — `min(fill_end_ms, book_end_ms)`, puisqu'une chaîne causale a besoin des
  deux. Un rapport `PREFLIGHT_ONLY` est ignoré ; un rapport sans bornes aussi ;
* `dernier_tag_safe` entre dans le verdict, lu de `COFFRE_INDEX.json` ;
* tout élément illisible vaut `None`, donc `INCONNU`, donc porte fermée.

Résultat sur l'état réel :

```
dernier_lot_certifie   2026-11-17 14:09      (frais)
dernier_rapport_labo   2026-11-12 15:25      118,9 h de retard
dernier_tag_safe       2026-10-18 00:00      734,3 h de retard
statut : PERIME
```

Le tunnel et la matrice délèguent maintenant à ce module ; la lecture des dates de tag n'existe
plus qu'à un endroit.

**Tests** : `test_fraicheur_preuve.py` 7 → **12 verts** (une pré-vérification ne rajeunit rien ;
la fin utile est le plus petit des deux derniers instants ; l'âge de SAFE entre dans le verdict ;
sans fait lisible tout est INCONNU ; un tag à date impossible ne fabrique pas d'horloge).

---

## 17/11/2026 — ITÉRATION 12 : la capacité confrontée au volume répliqué, et quatre lois inscrites

### La capacité, mesurée là où elle compte

L'itération 9 avait établi que, pour le coin médian, une minute de marché n'échange que 1,51 fois
l'ordre paper. Restait la question utile : sur quelle part du volume **réellement traité** par la
réplication cela pèse-t-il ? Le simulateur publie maintenant son volume par coin (ventilation
additive : un test vérifie que la somme égale son volume total), et l'étude le confronte à la
capacité mesurée sur la même fenêtre.

```
volume répliqué total : 366 192 USD sur 99 coins
sur des coins étroits (une minute médiane échange moins que l'ordre) : 2,8 %
sur des coins de capacité inconnue (aucun trade de marché observé)   : 0,6 %
sur des coins de capacité mesurée suffisante                          : 96,7 %
```

**L'inquiétude de l'itération 9 est donc bornée par la mesure** : les leaders tiennent surtout des
coins liquides, et la question de l'impact ne se pose que sur 3,4 % du volume. Je l'avais formulée
plus largement qu'elle ne le méritait ; le chiffre la remet à sa place. Le seuil de 1 × restant
indulgent, les prochains passages publient aussi 10 × et 100 ×, et le volume par coin, pour
qu'un autre seuil se recalcule sans rejouer 45 minutes.

### Le correctif d'essais multiples, avec sa marge de bruit

```
meilleur leader RÉEL        : +18,849 USD/jour (parmi 105 comptes)
meilleur leader SOUS PLACEBO : moyenne +19,156 · p95 +34,632
écart au p95 du hasard      : −15,783 USD/jour   (marge de bruit : +1,061)
VERDICT                     : LE_TOP_EST_INDISCERNABLE_DU_HASARD
ensemble                    : 413 journées-leader sur 5 jours → MORE_DATA
```

### Quatre lois inscrites au registre

`docs/LOIS_MESUREES.md` est généré de `research/lois_mesurees.py` ; il passe de 19 à **23 lois**.
Chacune porte son chiffre et la donnée qui la rouvrirait :

| clé | verdict | ce qu'elle empêche de rejouer |
|---|---|---|
| `replication_meilleur_leader_du_tableau` | réfuté | prendre le sommet du tableau par leader pour un edge |
| `famille_overshoot_comme_entree` | réfuté | utiliser comme entrée une famille qui porte des prix du futur |
| `conditionnement_microstructure` | limite | attendre d'un conditionnement OFI plus que ses 15,9 % de couverture |
| `capacite_ordre_paper` | limite | supposer qu'un ordre de 350 USD passe sans impact partout |

Les mots-clés ont été vérifiés contre les faux rappels : « profit » ne déclenche rien (le mot-clé
OFI est ` ofi ` avec ses espaces, sans quoi il aurait matché « pr**ofi**t »).

**Tests** : `test_lois_mesurees.py` 43 verts (dont l'égalité document ↔ registre),
`test_replication_essais_multiples.py` 7 verts, `test_copy_vault_roles_familles.py` 15 verts.

---

## 17/11/2026 — ITÉRATION 13 : un faux `subprocess.run` survivait à son test — et j'avais deux fois mal expliqué ses effets

### Ce que j'avais écrit, et qui était faux

À l'itération 7, j'ai attribué quatre échecs de la suite complète à mes propres éditions de
fichiers pendant qu'elle tournait, et deux autres à la lenteur des tests de portes de qualité.
**Les deux explications étaient fausses.** Un troisième passage complet, sans aucune édition de ma
part, a rendu les mêmes échecs au même endroit — et quatre de plus. Je les avais « expliqués »
sans lire une seule trace. Les deux passages du journal sont marqués en place.

### La cause, lue dans la trace

```
where 0 = <tests.test_sync_git_robustesse._espionner.<locals>.faux_run.<locals>.Resultat ...>.returncode
```

`tests/test_sync_git_robustesse.py` posait un espion par affectation directe :

```python
module.subprocess.run = faux_run        # faux_run rend returncode = 0, stdout = "ok"
```

`module.subprocess` **est** le module `subprocess` global. Le faux restait donc installé pour tout
le processus, et rien ne le défaisait (un second test du même fichier faisait pareil avec un faux
qui lève `TimeoutExpired`). Chaque test exécuté ensuite sur le même ouvrier recevait ce faux à la
place de son vrai sous-processus :

| test | ce qu'il a reçu |
|---|---|
| `test_safety_audit_passes_project_baseline`, `test_quality_gates_*` (2), `test_doctor_command_passes_baseline` | « `.env is tracked by git` » — l'audit croyait que git avait répondu |
| `test_resumable_campaign_validate_digest_matches_raw_manifest` | `'ok'` à la place de l'empreinte du manifeste |
| `test_v2_legacy_external_dataset_repository_is_refused` | `returncode = 0` pour une commande censée refuser |
| `test_unknown_argument_fails_without_success_banner` | `returncode = 0` pour un lanceur censé refuser |

Reproduit en série en 9,6 s : il suffit de faire passer ce fichier d'abord. Le défaut est dans le
HEAD commité, pas dans mes changements. Deux hypothèses avaient été écartées **par l'expérience**
avant de lire la trace (le drapeau `HYPERSMART_CARRY_HYPE_PAPER`, et neuf fichiers de couverture
voisins) — c'est la trace qu'il fallait lire en premier.

**Le pire n'est pas ces 7 rouges.** C'est le nombre inconnu de tests qui passaient **au vert** pour
la même raison : tout test affirmant `returncode == 0` sur un sous-processus recevait un succès
que personne n'avait produit.

### La correction, et le garde qui empêche la récidive

1. `_espionner(module, monkeypatch)` : le remplacement est défait à la fin du test. Les deux
   affectations directes du fichier sont passées par `monkeypatch.setattr`.
2. `tests/garde_sous_processus.py` + un crochet dans `tests/conftest.py` : à la **frontière de
   chaque module de test**, après la fin des fixtures (donc après que `monkeypatch` a défait ses
   remplacements légitimes), `subprocess.run`, `Popen`, `call`, `check_call` et `check_output`
   doivent être les fonctions réelles. Sinon elles sont **restaurées** et le module **fautif**
   reçoit une erreur qui le nomme — au lieu de huit échecs sans rapport apparent, ailleurs.
3. `tests/test_decision_firehose.py` posait `HYPERSMART_CARRY_HYPE_PAPER = "1"` (une famille hors
   scope) par `os.environ[...]` sans le retirer : passé à `monkeypatch.setenv`. La fixture
   `env_runtime_neutre` neutralisait déjà la fuite au test suivant ; elle n'aurait pas dû exister.

Le garde a été **prouvé sur une fuite volontaire**, sous les deux interpréteurs du projet :

```
ERROR at teardown of test_qui_fuit
FUITE D'ETAT GLOBAL : ce module de test a laisse remplace(s) subprocess.run.
Les fonctions reelles ont ete restaurees.
2 passed, 1 error        <- le module SUIVANT reçoit un vrai sous-processus, et passe
```

Recherche statique d'autres affectations directes sur `subprocess`, `time`, `urllib`, `socket`,
`builtins` ou `os` dans les tests : aucune.

### État de la suite complète

Troisième passage (aucune édition concurrente) : **18 940 réussis, 10 échoués**, 33 min 40 s.

* 2 échecs **externes**, inchangés : `rig_020` et le catalogue de données en retard ;
* **7** échecs dus à la **fuite** ci-dessus, tous sur l'ouvrier `gw1`, tous après le fichier
  fautif. Revérifiés verts en série avec l'ancien coupable passé en premier (27 tests, puis les
  portes de qualité : 12 verts en 7 min 10) ;
* **1** échec dû à la **machine saturée**, et non à la fuite :
  `test_all_official_cmds_resolve_their_own_root_from_foreign_cwd` a tourné sur un autre ouvrier
  (`gw0`), à 99 %, et `cmd.exe` a rendu `3221225794` (`0xC0000142`, initialisation du processus
  impossible) avec une sortie vide. Il passe en série. J'avais d'abord écrit « 8 échecs dus à la
  fuite » avant d'avoir lu cette trace-là : corrigé ici.

Ce passage a été coupé de son enveloppe par le harnais pour mémoire système critique (l'arbre
Python a néanmoins fini et rendu son résumé). La collecte n'en a pas souffert : 20 collecteurs
frais. **Je ne relance pas la suite complète de moi-même** : la confirmation d'ensemble après ce
correctif reste à faire, sur demande et mémoire disponible.

**Tests** : `test_garde_sous_processus.py` 7 verts ; `test_sync_git_robustesse.py` 7 verts.

### Suite de l'itération 13 — rejeu coupé, puis mise en veille du PC (trou de collecte de 42 min)

**Rejeu des tests exécutés derrière la fuite.** Le journal `-v` nomme l'ouvrier de chaque test :
1 454 tests ont tourné sur `gw1` après le fichier fautif (1 441 verts, 6 ignorés, 7 rouges). Je les
ai relancés en un seul processus pour compter les **faux verts**. Le harnais a coupé ce rejeu pour
mémoire système critique **avant le premier résultat** (il en était à la collecte, 119 Mo).
**Non relancé** ; la liste est conservée dans `runtime/logs/tests/derriere_la_fuite.json`.
Le nombre de faux verts reste donc **inconnu**.

**Mise en veille.** Journal système de Windows : `16:25:10` « Le système entre en veille — motif :
Button or Lid » ; `17:07:17` sortie de veille, source « Power Button ». Ni la mémoire ni Alina.

| observé | valeur |
|---|---|
| trou du chien de garde | 16:25:08 → 17:07:42 (2 554 s), puis **nouveau bail** |
| trou du ruban L2 (`copy_vault_l2_lane.jsonl`) | 16:25:04 → 17:07:39 (2 556 s) |
| reprise | 20 collecteurs actifs, protocole causal `OK` à 17:08:14 |
| identités de connexion | **toutes différentes** avant et après le trou |
| `l2_gap_epoch` | 0 avant ; 2 et 3 sur les nouvelles connexions à partir de 17:08:14 |
| horloge | Windows a recalé l'heure de **+1,24 s à 17:08:10** : ~55 s d'horodatage avec une horloge en retard |
| latence réception − échange | avant : médiane 490 ms ; après : 680 à 920 ms, minimum 87 ms, **aucune valeur négative lue** |

**Ce qui n'est PAS vérifié** (à faire, lecture seule d'abord) :

1. que ce trou est bien inscrit dans les fenêtres de trous (`copy_vault_gap_windows`) et dans le
   coffre scellé, et pas seulement visible par le changement de connexion ;
2. que les fills reçus en rattrapage à la reconnexion (snapshot WS, `backfill_vault_fills`) ne
   sont jamais comptés comme signaux copiables — un fill daté de la veille mais reçu 42 min plus
   tard est un signal tardif, pas un signal ;
3. l'effet des ~55 s d'horloge en retard de 1,24 s (17:07:15 → 17:08:10) sur les latences et sur
   l'ordre réception/signal de cette minute-là ;
4. les quatre lignes de connexion à `l2_gap_epoch = 0` entre 17:07:39 et 17:07:41 (148 lignes),
   avant le passage à l'époque 2 : références liables ou non ?

---

## 17/11/2026 — ITÉRATION 14 : le direct ratait le DÉBUT de chaque rafale d'un leader (61 % des fills)

### Les quatre contrôles du trou de 42 minutes (veille du PC), résultats

| contrôle | résultat | état |
|---|---|---|
| le trou est-il déclaré ? | 302 fenêtres `checkpoint_expired`, union 16:25:16 → 17:08:03 = **99,8 %** de la veille | couvert, mais **par accident** : seulement parce que des checkpoints étaient en attente (voir « reste ouvert ») |
| des fills tardifs pris pour des signaux ? | **0** fill daté de la veille dans le ruban direct ; 400 fills reçus dans les 3 min du réveil, tous `LIVE_WS` non-snapshot, retard 295 à 1 183 ms | conforme (l'écrivain refuse tout retard > 30 s) |
| horloge recalée de +1,24 s | aucun retard négatif lu ; un saut **en avant** conserve l'ordre réception/signal | borné ; un saut **en arrière** ne serait pas détecté (voir « reste ouvert ») |
| références reçues à 17:07:39–41 | lignes directes sur de NOUVELLES connexions ; aucune liaison possible avec un signal d'avant la veille | conforme |

Fait relevé au passage : l'état de l'écrivain porte encore 43 expirations et 1 rotation
antérieures au journal de fenêtres. `journal_coherent` rend donc `FENETRES_INCOMPLETES` et cette
époque locale ne certifie rien — c'est le comportement voulu le 16/11 (aucune réparation
rétroactive). Les lignes restent exploitables en exploratoire.

### Le défaut trouvé en suivant ce fil

En vérifiant si un renfort de position (ADD) vu juste après une reprise pouvait être pris pour un
DÉBUT de méta-ordre, j'ai rejoué la logique de l'écrivain sur le ruban direct, puis sur
l'historique COMPLET des fills (`vault_fills.jsonl`, rattrapage REST, par heure d'échange).

**Faux débuts : faible.** Sur 2 090 débuts comparables, 2 022 (96,7 %) sont de vrais débuts ;
65 (3,1 %) sont des continuations, dont la moitié de simples égalités d'horodatage.

**Mais le direct ne voit que 38 % des fills des leaders qu'il suit.** Les 62 % restants ne sont pas
des pertes de transport : **0 fill perdu à l'intérieur d'une connexion**, 0,6 % au bord d'une
connexion. Ils tombent quand le leader n'a pas d'emplacement. Heure par heure, sur un leader :

```
01h : 861 fills réels /   0 vu      02h : 324 /  27      03h : 173 / 169      04h : 89 / 91
01h : 2165        / 192            02h : 754 / 742      03h : 287 / 276      (un autre jour)
```

Une fois abonné, la capture est complète. Ce qui manque est le **début** de chaque rafale.

**Cause.** Hyperliquid plafonne à 10 les utilisateurs suivis en direct. Le collecteur garde les
leaders « actifs » et fait tourner le reste parmi les silencieux. Or `_activite_par_vault` ne
comptait que les fills **vus en direct** : un leader sans emplacement ne pouvait pas être vu, donc
jamais devenir actif. Il attendait que la rotation retombe sur lui.

**Mesure** (`tools/mesurer_decouverte_rafales.py`, 8 leaders, 49 reprises après ≥ 45 min de silence,
11 395 fills) :

| | fills manqués | part |
|---|---|---|
| rotation actuelle | 6 956 | **61,0 %** — 30 rafales sur 49 jamais vues ; découverte en 38, 40, 114 min sur les plus grosses |
| alerte par les fills inférés de l'explorateur | — | **inutilisable** : ne couvre qu'1 leader sur 8 (hypothèse testée, écartée) |
| alerte par le poll REST, promotion à la page suivante | 2 231 | **19,6 %** (borne : un emplacement disponible) |

Le poll REST interroge déjà chaque leader ; sa première ligne sur une rafale arrive 1 à 340 s après
le premier fill.

Second défaut, lié : dès qu'UN emplacement tournait, le collecteur fermait et rouvrait **toutes**
ses connexions — 1 497 connexions en 44 h, un petit trou aveugle toutes les 150 s pour chaque
leader actif.

### La correction

Module neuf `src/hl_observer/collection/slots_userfills.py`, trois retouches dans
`tools/collecter_userfills_vaults.py` (+22 lignes) :

1. **L'activité d'un candidat est le maximum du direct et du poll.** Le poll ne sert qu'à décider
   où regarder : aucun de ses fills ne devient un signal. Lecture bornée de la queue du ruban
   (32 Mo, ~0,18 s), dans un fil pour ne pas retenir la boucle qui horodate les fills.
2. **Un leader classé `ARCHIVE` par le labo n'est jamais promu par le poll**, et les actifs sont
   servis dans l'ordre du plan du labo (PRIORITAIRE, STANDARD, puis le reste). Sans cela, les
   emplacements seraient allés aux plus bruyants : 90 des 142 leaders actifs au poll sont `ARCHIVE`.
3. **Le titulaire garde sa place** à classe égale, et la page garde son ordre.
4. **Les emplacements libres ne tournent plus que parmi les candidats que le poll ne couvre pas**
   (2 sur 73) : eux seuls ont encore besoin du direct pour être découverts.
5. **Repli exact** : poll absent, illisible ou sans ligne depuis 10 min → rotation historique,
   à l'identique. Un indice muet ne doit jamais geler la découverte.
6. **Journal des pages** `runtime/data/userfills_pages.ndjson` : une ligne par cycle, avec les
   leaders abonnés. Avant, « pas abonné » et « abonné mais silencieux » étaient indiscernables.

Simulation sur les données réelles du moment : trois leaders actifs entrent dans la page (dont un à
76 fills en 45 min que l'ancienne règle laissait dehors), et **la page devient identique dès le
deuxième cycle** — le collecteur garde alors ses connexions.

### Tests

`test_slots_userfills.py` 48 (lecture bornée et ses motifs, exclusion `ARCHIVE`, ordre des classes,
titulaires, repli identique à la rotation historique sur 5 × 30 cas, journal, câblage, et **le vrai
superviseur exécuté hors ligne** : page reconduite et sockets ouvertes une seule fois avec un poll
frais ; rotation historique page pour page sans poll) ;
`test_mesurer_decouverte_rafales.py` 15 ; suites existantes du collecteur inchangées
(193 verts au total) ; garde-fous du dépôt 125 verts ; le collecteur retouché se charge sous
l'interpréteur portable de production (3.14.2).

### Ce qui n'est PAS fait

* **La correction ne tourne pas encore.** Le collecteur en service a démarré à 17:07 avec l'ancien
  code ; je ne l'ai pas redémarré, pour ne pas interrompre la collecte. Elle prendra effet à son
  prochain démarrage. Témoin : l'apparition de `userfills_pages.ndjson`.
* **Le gain réel n'est pas mesuré.** 19,6 % est une borne calculée, pas une observation. Relancer
  `python tools/mesurer_decouverte_rafales.py` après quelques jours et comparer à
  `runtime/logs/mesures/decouverte_rafales_avant_20261117.json`.
* **Reste ouvert, mesuré, non corrigé :** reconstruire une seule connexion au lieu de toutes
  quand un emplacement change. Enjeu mesuré : 0,6 % des fills (bords de connexion) et au plus
  3,1 % de faux débuts — et la page devenant stable, les reconstructions deviennent rares. La part
  des cycles `maintenue` du journal des pages dira si le sujet reste ouvert.

### Suite de l'itération 14 — deux défauts de reprise corrigés dans la foulée

**1. Une seule coupure pouvait fermer l'époque pour toujours.** La veille de 42 min a fait expirer
302 checkpoints : 302 fenêtres de trou presque identiques, dans un journal plafonné à 512. Au-delà
du plafond le journal perd des fenêtres, et plus rien n'est certifiable (`FENETRES_PERDUES`) —
alors que tout l'incident tient dans un intervalle. Une coupure d'environ deux heures y suffisait.

* `GAPS.compacter` fusionne les fenêtres de même nature qui se recouvrent ou se touchent, en
  sommant `n`. L'union des intervalles et la somme par nature sont conservées **exactement**
  (vérifié sur 200 tirages aléatoires, et sur l'état réel : 302 fenêtres → 1, même union, somme
  302 → 302). Une fenêtre invalide n'est jamais absorbée.
* Appliqué à chaque ajout et au chargement de l'état de l'écrivain.

**2. L'arrêt de l'écrivain n'était un trou que par accident.** Il n'apparaissait que par les
checkpoints qu'il faisait expirer ; sans checkpoint en attente, aucune fenêtre, et la durée « sûre »
publiée à la porte de preuve (`safe_coverage_ms`) incluait l'arrêt.

* Nouvelle nature `writer_outage`, compteur `writer_outages`, réconciliés comme les autres.
* L'intervalle déclaré est celui où un fill n'aurait PAS pu être pris : de la dernière passe à
  « maintenant − 30 s » (un fill plus récent est encore accepté à la reprise). Ma première version
  allait jusqu'à « maintenant » : un test existant l'a refusée à raison, elle retirait de la preuve
  des lignes parfaitement observées.
* Un état écrit par un code antérieur n'a pas ce compteur : il vaut zéro, l'état reste lisible.
  Présent, il doit être expliqué fenêtre par fenêtre.

**3. Sauts d'horloge : mesurés, puis gardés.** Chaque fill porte une horloge monotone
(`recv_mono_ns`). Sur tout le ruban (92 694 fills, 44 h) : **un seul** écart avec l'horloge murale,
le saut en avant de +1 195 ms du réveil ; **aucun saut en arrière**. Le premier fill après le réveil
a été horodaté après le recalage : aucun signal touché.

* `ops/sauts_d_horloge.py` : détecteur insensible à l'ordre de lecture, qui nomme la fenêtre
  ambiguë d'un recul et compte les signaux qui y tombent — y compris ceux déjà jugés.
* Câblé dans le tunnel d'exécutabilité : signaux d'une fenêtre ambiguë refusés
  (`SAUT_D_HORLOGE_EN_ARRIERE`), bilan publié. Sur le ruban : `OK, 1 en avant, 0 en arrière`. Sur le
  coffre du 17/11 : même verdict, et **888 997 lignes sur 920 171 sans horloge monotone** (les fills
  du poll n'en portent pas) — publié, pas tu.

**Tests** : fenêtres de trou 37 (dont 9 nouveaux), compagnon 31 (dont 4 nouveaux), sauts d'horloge
12 ; 371 verts avec les suites consommatrices (liaison, exécutable, labo local, tunnel, invariants).
Comme pour le collecteur, le compagnon en service tourne encore l'ancien code : effet au prochain
démarrage (la compaction s'applique dès le chargement de l'état).

### Suite de l'itération 14 — faux verts derrière la fuite : bornés, puis vérifiés

Le rejeu des 1 441 tests verts exécutés derrière la fuite de `subprocess.run` avait été coupé par
le harnais (mémoire), et sa relance — même par lots — m'a été refusée tant que l'opérateur ne la
demande pas. J'ai donc borné la question au lieu de la rejouer en entier :

* un test ne peut avoir été faussé par le faux `subprocess.run` que s'il atteint du code qui lance
  un sous-processus ;
* sur les 351 fichiers concernés, **5** citent `subprocess` et **25** importent l'un des 88 modules
  du produit qui en lancent : 30 fichiers, 129 tests verts à l'époque ;
* ces 30 fichiers, rejoués en un processus avec l'ancien coupable passé en premier :
  **140 verts, 2 ignorés, 0 rouge**.

Aucun faux vert trouvé parmi les tests qui pouvaient l'être. Limite : le critère est statique (noms
de modules cités dans le fichier de test) ; un test atteignant un sous-processus par un chemin
d'import plus long échapperait à ce tri. Seule la suite complète le dirait.

Recherche statique élargie des fuites que le nouveau garde pourrait attraper (affectation directe,
`setattr` nu, `patch(...).start()` sur `subprocess`, alias d'import) dans les 87 fichiers de test
qui citent `subprocess` : **aucune** hors du test du garde lui-même.

Pré-vérification du labo après les changements du jour : câblage intact, gel v21 toujours refusé
pour le bon motif. Rejeu `--safe-research --once` lancé à 18:19, mémoire au vert (9,5 Go, 28 %).

---

## 17/11/2026 — ITÉRATION 15 : le labo lisait le début du coffre, abandonnait à la première alerte mémoire, et ne le disait pas

### Activation des corrections de l'itération 14 (accord de l'opérateur)

Les deux collecteurs ont été redémarrés un par un en arrêtant uniquement leur processus ; leur
lanceur les a relancés sous le même bail.

| collecteur | coupure | preuve que le nouveau code tourne |
|---|---|---|
| fills en direct | **~38 s** (et non 5 s : le verrou d'instance restait tenu par le processus arrêté jusqu'à péremption de son battement) | `userfills_pages.ndjson` créé ; première page : **7 leaders PRIORITAIRES actifs** (2 avec l'ancienne règle), 10 abonnements confirmés ; dès le 2ᵉ cycle « ensemble de vaults stable → connexions maintenues », message jamais émis auparavant |
| compagnon de checkpoints | 2,3 s | journal de trous ramené de 302 fenêtres à 1 (`n = 302`) ; compteur `writer_outages` présent ; même époque, même écrivain ; captures qui continuent |

Chien de garde : 20 collecteurs actifs, protocole causal `OK`. Sur les 5 premiers cycles du
collecteur : 3 reconduits sans reconnexion, 2 reconstruits (le démarrage, puis un vrai changement
de page). Avant, chaque cycle reconstruisait tout.

### Le rejeu du labo, et ce qu'il a révélé

`alina_quant_lab_console.py --safe-research --once`, mémoire au vert au lancement. Il conclut
`MORE_DATA / INSUFFICIENT_EVALUABLE_SIGNAL_DAYS` : « trop peu de jours où un signal leader dispose
d'un carnet L2 causal ». Trois défauts derrière cette phrase :

1. **Le pont LOCAL abandonnait à la première alerte mémoire.** Une seule lecture « critique » du
   gouverneur, et tous les shards restants étaient laissés : **60 lus, 6 349 non lus**. Trente
   secondes plus tard la machine avait 9,5 Go libres.
2. **De toute façon il lisait le début du coffre.** Sans fenêtre, le pont suit l'ordre de
   scellement et s'arrête à 8 M lignes : au shard 122 sur 6 409, **jamais au-delà du 10/11**. La
   chaîne causale complète n'existe au coffre qu'à partir du 13/11.
3. **Le verdict ne disait rien de la lecture interrompue.** `chargement_arrete` et `shards_non_lus`
   étaient écrits dans le JSON et lus par personne.

### La correction

`src/hl_observer/backtesting/copy_vault_fenetre_locale.py` :

* `choisir_la_fenetre` : le labo lit à partir du **premier jour liable** (une seule définition,
  partagée avec `tools/matrice_coffre.py`). Sans jour liable ou sans index, lecture comme avant.
* `patienter_sous_pression` : mémoire critique → on **attend** (30, 60, 120, 240 s) si la pression
  vient d'ailleurs ; on s'arrête tout de suite si c'est notre propre charge. Aucun processus tiers
  n'est touché.
* `mention_de_lecture` : le verdict porte la lecture interrompue, avec les comptes.

### Avant / après, sur le coffre réel

| | avant | après |
|---|---|---|
| shards LOCAL lus | 60 | **452** (719 écartés car antérieurs à la fenêtre) |
| attente mémoire | aucune, abandon immédiat | 4 alertes, 176 s d'attente, puis arrêt pour **notre propre charge** |
| signaux évaluables | 14 654 | **64 567** |
| jours avec ≥ 10 signaux évaluables | **4** (17/10, 07/11, 08/11, 09/11) | **3** (17/10, 12/11, 13/11) |
| revues de leaders | 0 (`NO_LEADER_DECISIONS`) | 44, toutes non mesurables |
| verdict | « trop peu de jours » | idem, **suivi de** « lecture du coffre LOCAL interrompue (MEMOIRE_CRITIQUE) : 452 shards lus, 5 118 non lus. Ce verdict décrit ce qui a été lu, pas le coffre. » |

**Ce qui s'améliore** : le labo lit l'ère qu'il sait juger, quatre fois plus de signaux
évaluables, des revues de leaders, et un verdict qui ne ment plus sur sa lecture.

**Ce qui se dégrade, et il faut le dire** : le nombre de jours évaluables passe de 4 à 3. Un seul
jour récent (64 013 signaux évaluables le 13/11) remplit la mémoire du labo, qui s'arrête pendant
ce jour-là. Aucune fenêtre unique ne peut tenir six jours denses : la limite n'est plus le choix
de la fenêtre, c'est la charge en mémoire. Avec l'ancienne règle, le labo restait pour toujours
sur les jours d'avant le 10/11 ; avec la nouvelle, il reste sur le premier jour dense.

**Tests** : `test_copy_vault_fenetre_locale.py` 19 ; 49 verts avec le pont et la matrice ;
imports inutiles laissés par mes extractions retirés (lint propre sur les fichiers touchés).

### Ce que le coffre contient vraiment, mesuré en flux

Le tunnel d'exécutabilité lit le coffre en flux, sans rien matérialiser. Sur 07 → 17/11
(19 576 327 lignes lues, 1 175 shards, 0 refusé) :

| jour (UTC) | signaux d'ouverture en direct | avec carnet reçu AVANT | jusqu'à la sortie observée |
|---|---|---|---|
| 07/11 | 9 225 | 8 885 | 5 552 |
| 08/11 | 10 952 | 10 267 | 9 935 |
| 09/11 | 3 915 | 3 630 | 3 358 |
| 10/11 | 7 085 | 5 345 | 4 947 |
| 11/11 | 2 285 | 1 833 | 1 660 |
| 12/11 | 442 | 435 | 385 |
| 13/11 | 10 467 | 10 444 | 10 444 |
| 14/11 | 15 055 | 15 006 | 14 987 |
| 15/11 | 22 541 | 22 536 | 22 377 |
| 16/11 | 31 006 | 31 004 | 31 004 |
| 17/11 | 17 412 | 17 372 | 17 251 |
| **total** | **130 385** | **126 757 (97,2 %)** | **121 900 (93,5 %)** |

**Onze jours sur onze** dépassent le seuil de 10 signaux évaluables que le labo exige sur six
jours. Le labo, lui, n'en charge que trois ou quatre et conclut `INSUFFICIENT_EVALUABLE_SIGNAL_DAYS`.
La donnée existe ; c'est la charge en une fois qui ne passe pas (environ un jour dense, ~1,7 M
lignes LOCAL, avant que le labo ne sature lui-même la mémoire).

Sauts d'horloge sur ces 10,5 jours : 12 en avant, **0 en arrière** (mesurés sur les fills en
direct ; 19 323 509 lignes du poll ne portent pas d'horloge monotone).

**Prochain travail du labo, identifié et réalisable** : le conduire sur plusieurs jours sans tout
matérialiser. Deux voies, à concevoir sans biaiser l'échantillon : (a) ne garder des carnets que
ceux qu'un signal peut utiliser (référence, entrée, horizons de sortie), ce qui exige d'abord
l'inventaire exact des usages des carnets dans le labo — un carnet de sortie retiré à tort se
lirait comme une sortie absente ; (b) évaluer jour par jour (`plan_de_fouille`) et agréger, en
refusant les moyennes de moyennes. Tant que ce n'est pas fait, le verdict du labo porte la mention
de lecture interrompue.

### Suivi en production de la correction du collecteur (17/11, 18:38 → 19:34) — et un défaut de MA correction

Journal des pages, 23 cycles après le redémarrage : 11 reconduits, 12 reconstruits, 8 pages
distinctes. Les changements, un par un :

| heure | entre | sort | lecture |
|---|---|---|---|
| 18:48, 19:01 | un leader retenu | l'autre leader retenu | le 2ᵉ « retenu » du classement alterne entre deux vaults : comportement antérieur, hors de cette correction |
| 18:56, 19:03, 19:08, 19:21 | un leader actif au poll | un leader dont les fills sont sortis de la fenêtre de 45 min | voulu : la place va à qui trade |
| **19:21 → 19:33, à chaque cycle** | `feab64` puis `e67dbf` puis `feab64`… | l'autre | **défaut de ma correction** |

Ces deux candidats sont les seuls que le poll ne couvre pas. Ma règle les faisait tourner entre
eux sur les emplacements libres — mais avec **un seul** emplacement libre ils alternaient à chaque
cycle, et chaque alternance reconstruisait les dix connexions : le défaut même que la correction
devait supprimer. La simulation ne l'avait pas montré (trois emplacements libres ce jour-là, les
deux y tenaient).

**Corrigé** : quand le poll couvre les autres, les non-couverts tournent par paliers de 12 cycles
(30 minutes). Sans liste du poll, la rotation reste celle d'origine, cycle par cycle. Deux tests
ajoutés, dont le cas exact de 19:21 (130 verts sur les suites du collecteur).

**Non actif** : il faut un second redémarrage du collecteur de fills (~38 s). En attendant, la
découverte par le poll fonctionne ; seule la stabilité de page est perdue quand les non-couverts
sont plus nombreux que les emplacements libres.

### Commit local

`770943331fc` sur la branche locale `alina/objectif-20261117` (130 fichiers, parent `b206107b04b`),
à la demande de l'opérateur, **non poussé**. `main` est inchangé. `git commit` relit les 1,9 million
de fichiers de données modifiés : 12 minutes et 2,7 Go ; le harnais a coupé son enveloppe pour
mémoire critique, le processus a fini seul.

### Arrêt et relance de la campagne par l'opérateur (17/11, 19:58 → 20:06)

L'opérateur a arrêté ses collecteurs (touche `q`) : scellement terminé à 20:01:31, 35 rubans
archivés dans `runtime/archive/session_20261117_200154`, `runtime/data` reparti à zéro. À sa
demande j'ai relancé `LANCER_COLLECTEURS_COPY_VAULT.cmd` : nouveau bail à 20:06:41, 20 collecteurs
actifs. **Trou de collecte : 19:58:32 → 20:06:41, environ 8 minutes.**

| contrôle | résultat |
|---|---|
| données de la session au coffre | index LOCAL passé de 6 409 à 6 524 shards ; fills, carnets L2, BBO et positions scellés jusqu'à 19:58 |
| trou déclaré par le compagnon | `writer_outages = 1` et sa fenêtre `writer_outage`, plus 67 checkpoints expirés (une fenêtre) : nouveau code, premier arrêt réel |
| redémarrage À FROID du collecteur de fills | rubans remis à zéro, journal des liquidations archivé (plus de leader épinglé) : à 20:06:40 le poll ne voyait qu'1 leader actif ; **à 20:09:10 il en voyait 9 et a fait entrer le plus actif (89 fills) dans la page**. Fills en direct à 20:11. Avec l'ancienne règle, cette redécouverte passait par la rotation des silencieux |
| second correctif (paliers) | chargé à 19:57, puis de nouveau à la relance |

**Ce qui se rattrape, et ce qui ne se rattrape pas** (question de l'opérateur) :

| donnée du labo | rattrapable ? | par qui |
|---|---|---|
| fills des leaders, par heure d'échange | oui | collecteur `backfill-fills` de la campagne |
| bougies, funding | oui | `backfill-candles-vaults` (campagne) et `RATTRAPAGE.cmd` (profondeur) |
| carnets L2 / BBO | **non** | l'API ne redonne pas un carnet passé |
| heure de réception en direct d'un fill | **non** | vue en direct ou jamais |

`RATTRAPAGE.cmd` ne lit donc pas le coffre : c'est normal. Son affichage prêtait à confusion
(« remonte à 0 j | 1 au total » ne comptait que l'ajout du passage) : libellés corrigés.

**Mémoire de la machine** : des `git status` reviennent en boucle sur le dépôt (1 à 1,7 Go chacun,
plusieurs minutes sur 1,9 million de fichiers, parfois deux à la fois). Ils sont lancés par
l'application ChatGPT de bureau. Alina n'y touche pas ; c'est à l'opérateur d'en décider.

### Qui remplit la mémoire du labo (mesure du 17/11 au soir, journée du 14/11, en flux)

| | lignes | part |
|---|---|---|
| fills au coffre ce jour-là (201 leaders) | 1 734 349 | 100 % |
| … vus par le poll (`LIVE_POLL`) | 1 706 585 | 98,4 % |
| … vus en direct (`LIVE_WS`) | 27 192 | 1,6 % |
| classés `ARCHIVE` par le plan du 12/11 (non rejoués) | 167 010 | 10 % |
| **gardés par le labo** | **1 567 339** | 90 % |
| … dont les 15 leaders les plus bavards | 1 227 563 | **78 % de ce que le labo garde** |

Ces quinze leaders font de 27 000 à 209 000 fills par jour — un à deux par seconde, toute la
journée — et ne sont vus que par le poll. Le plan du labo, daté du **12/11**, les classe encore
`STANDARD` (« swing ») ou `DECOUVERTE` (« pas encore classé ») : il a été établi sur un ou deux
jours de poll. Le labo charge donc en mémoire, comme signaux à rejouer, les fills de robots qu'il
ne peut pas copier un par un.

**C'est la cause concrète de « le labo ne tient qu'un jour dense ».** Sans eux, une journée pèse
environ 340 000 lignes et cinq jours tiennent dans la mémoire que le labo a utilisée ce soir.

**[RECTIFIÉ — hypothèse RÉFUTÉE par la mesure, voir la section suivante]** **Prochain travail, précis** : rafraîchir le plan par l'étude de copiabilité existante
(`tools/etude_copiabilite.py`, critère inchangé : rotation ≥ 20 × l'exposition, ou épisodes clos
avant observation). Elle charge aujourd'hui TOUS les fills dans un tableau en mémoire
(19,6 millions de lignes) : il lui faut une fenêtre récente bornée avant de la relancer sans
risque. Ne PAS ajouter une seconde règle de tri dans le labo : la classe d'un leader doit garder
une seule source.

### Hypothèse réfutée : ce ne sont pas des robots, et rafraîchir le plan ne libère pas la mémoire du labo

J'avais écrit que les quinze leaders les plus bavards étaient des robots que le plan du 12/11
classait à tort « swing ». Je l'ai vérifié AVANT de toucher au plan : l'étude de copiabilité
existante (`etude_copiabilite.run`, critère inchangé), appelée sur la fenêtre 15 → 17/11 sans rien
écrire (4 345 386 fills, 179 unités, 321 s, pic mémoire 2,99 Go).

| unité | fills (3 j) | rotation / exposition / jour | exposition moyenne | archétype mesuré |
|---|---|---|---|---|
| `31ca83` | 337 391 | 1,8 | 2,9 M USD | `DIRECTIONAL_SLOW` |
| `010461` | 325 581 | 1,7 | 2,9 M USD | `DIRECTIONAL_SLOW` |
| `ecb63c` | 225 732 | 3,2 | 98,6 M USD | `SWING` |
| `7717a7` | 145 453 | 1,9 | 12,0 M USD | `DIRECTIONAL_SLOW` |
| `c179e0` | 123 416 | 8,9 | 15,4 M USD | `SWING` |
| `0eecd6` | 98 320 | 2,6 | 5,8 M USD | `DIRECTIONAL_SLOW` |

**Ce sont de gros opérateurs LENTS qui découpent leurs ordres en centaines de milliers de fills**,
pas de la haute fréquence : leur inventaire ne tourne qu'une à trois fois par jour. Par le critère
du labo (la rotation rapportée à l'exposition), ils sont précisément la cible d'une réplication.

Conséquence mesurée : avec le plan recalculé, le labo garderait **86 %** des lignes de la fenêtre
(1 974 389 sur 2 295 725), contre 87 % avec le plan du 12/11. **Rafraîchir le plan ne résout pas
la mémoire du labo.**

Ce que la mesure apprend à la place :

* le plan du 12/11 est périmé pour une autre raison : 36 unités deviendraient `PRIORITAIRE`, 5 ne
  le seraient plus (dont `c179e0`, le leader épinglé, qui passerait `STANDARD`). Le rafraîchir
  changerait qui occupe les emplacements en direct ; à faire délibérément, par la voie normale
  (l'étude avec une fenêtre bornée, inscrite au registre), pas ce soir en passant ;
* **[piste rectifiée le 18/11 — voir l'itération 16 bis]** la vraie cause de la saturation :
  le labo traite chaque fill enfant comme un signal (64 326 `ADD` évaluables le 13/11 pour
  241 `OPEN`). J'en avais déduit qu'il fallait agréger les fills en méta-ordres au chargement.
  La lecture du code montre que ce serait faux.

---

## 18/11/2026 — ITÉRATION 16 : l'outil de revalidation allait déclarer fausses 103 preuves qu'il n'avait pas rejouées

### Le contexte : la suite complète par lots, et douze lots qui n'ont jamais tourné

La suite a tourné par lots pendant la nuit. Résultat : **6 053 verts, 6 ignorés, 1 rouge**
(`rig_020`) sur les sept premiers lots ; le lot 5 a été arrêté par la garde mémoire ; et **les
douze derniers lots n'ont jamais démarré** — code `3221225794` (`0xC0000142`), journal de 0 octet,
5 secondes chacun. Windows ne pouvait pas créer le processus, faute de mémoire.

Mon pilote a enregistré ces lots `SANS_RESUME` — honnête, il n'a rien prétendu — mais il a enchaîné
douze lots condamnés au lieu de réessayer le même après une attente. Défaut de mon outil, corrigé
(voir plus bas).

### Le défaut grave, trouvé AVANT de lancer l'outil

Le seul rouge du dépôt est `rig_020` : **103 reçus de la roadmap sont périmés** (les fichiers qui
les prouvent ont changé). Le dépôt a l'outil honnête pour ça, `tools/revalider_receipts.py` : il
rejoue les tests cités par chaque reçu et n'ajoute un reçu rafraîchi que s'ils passent.

En lisant son code avant de le lancer, j'ai trouvé ceci :

```python
code = rejouer(tests, root, timeout_s)          # 3221225794 quand le processus NE DÉMARRE PAS
...
raison = ("tests re-run failed" if code not in (0, None) else
          "tests could not be run" if code is None else ...)
_ajouter(path, recu_echec(row, exit_code=code, ...))     # append-only : définitif
```

Tout code non nul devenait `REVALIDATION_FAILED`, et même le cas `None` (exception de lancement)
écrivait un verdict négatif. **Lancé ce matin sur la machine telle qu'elle était cette nuit,
l'outil aurait déclaré fausses les 103 preuves sans en rejouer une seule**, et autant de tâches
auraient cessé d'être comptées comme faites — dans un registre qu'on n'écrit qu'en ajout.

C'est exactement l'interdit de l'objectif, dans sa forme la plus coûteuse : une **absence de
mesure** transformée en **verdict**.

### La correction

* `CODES_NON_LANCE` = `{0xC0000142, 0xC0000017, -9}` : les codes qui disent « le processus n'a pas
  démarré », jamais « les tests ont échoué ».
* `_rejouer` rend `None` sur ces codes, sur exception, **et sur une sortie entièrement vide** —
  pytest écrit toujours quelque chose, même pour refuser.
* La garde vit **au point où l'on écrit la preuve**, pas seulement dans le lanceur : ma première
  version ne protégeait que `_rejouer`, et mes propres tests l'ont refusée en injectant le code
  directement. Un rejeu qui n'a pas eu lieu n'écrit **rien** : le reçu reste périmé et visible,
  `rig_020` reste rouge, et l'opérateur relance quand la machine respire.
* `_souffler()` laisse la mémoire respirer avant chaque groupe (`budget_ram`, API existante).
* Un vrai échec de tests reste un verdict négatif : la correction ne rend pas l'outil complaisant.

**Tests** : 11 nouveaux dans `tests/test_revalider_receipts.py` (chaque code de non-lancement,
sortie vide, exception, respiration mémoire, gouverneur en panne, et **un segfault `-11` qui doit
rester un échec**) ; 39 verts avec les suites voisines.

### Troisième apparition du même code

`0xC0000142` s'est manifesté trois fois en deux jours, et chaque fois il a produit un **faux
négatif** : hier un test de lanceur portable rougi à 99 % de la suite ; cette nuit douze lots
« sans résumé » ; ce matin, 103 preuves qui auraient été invalidées. Sur cette machine, « le
processus n'a pas pu démarrer » doit être traité partout comme une absence de mesure.

### 18/11 — ITÉRATION 16 bis : pourquoi « agréger les signaux » n'est PAS la bonne piste

Lecture de `materialize_safe_workspace` et de `run_local_campaign` (aucune exécution) :

1. le labo charge **deux corpus en mémoire** — le tier SAFE (871 130 fills, 750 263 carnets) et le
   tier LOCAL (945 504 fills, 716 706 carnets) — sous forme de dictionnaires Python, pour les
   dédupliquer par identité et les trier ;
2. il **écrit** ensuite huit rubans sur disque (`vault_fills_live.jsonl`, `copy_vault_l2_tape.jsonl`,
   …) avec leur SHA-256 ;
3. la campagne qui suit **relit ces rubans depuis le disque** (`charger_entrees_alpha_…(workspace)`,
   `load_observed_books(workspace, …)`), et vérifie leurs empreintes.

Donc le pic de mémoire ne vient pas de ce que le labo « garde pour analyser » : il vient de ce
qu'il **garde pour trier et écrire**, alors que l'étape suivante lit le disque. Et agréger les
fills enfants détruirait l'information dont la reconstruction OPEN/ADD/REDUCE/CLOSE a besoin (prix
d'exécution moyen pondéré, tailles, transitions) — on perdrait la justesse pour gagner de la place.

**La piste juste** est donc : produire les rubans **sans tenir le corpus entier en mémoire** — tri
externe par fusion (le coffre est déjà rangé par shard, chacun quasi trié), ou matérialisation
fenêtre par fenêtre avec déduplication sur les seules clés d'identité. Les deux gardent les fills
individuels : rien n'est perdu, seul l'ordre de passage change. Chantier à mener avec un contrôle
d'identité byte-à-byte des rubans produits (les SHA sont déjà publiés dans le manifeste, ce qui
rend la comparaison avant/après exacte).

Je ne l'ai pas entrepris ce matin : la revalidation des 103 reçus occupait la machine, et ce
chantier touche le chemin qui produit les preuves. Il est décrit ici pour être pris de suite, avec
son critère de vérification.

### Résultat de la revalidation, et le défaut qu'elle a révélé : un reçu qui ne peut pas se prouver

Premier passage sur les 103 reçus périmés, avec l'outil corrigé :

```
perimes 103 · rafraichis 102 · echecs 1 · non_mesurables 0 · non_rejouables 0 · encore_perimes 0
```

`rig_020` passe désormais (20 tests verts). **L'unique échec est instructif** : `ASF-RIG-002`, le
reçu de la tâche qui prouve… `rig_020` lui-même. Son test LIT le registre : tant que son propre
reçu est périmé, le test échoue ; donc le reçu ne peut pas être rafraîchi ; donc le test continue
d'échouer. Deux autres reçus étaient enfermés dans la même impasse depuis des sessions
antérieures : `ASF-RIG-010` (14/11) et `ASF-RIG-019` (12/11). L'outil mettait bien ces groupes en
dernier, mais l'ordre ne résout pas l'auto-référence.

**Correction, sans complaisance** : après avoir écrit le verdict négatif — qui retire au reçu son
statut de preuve et lève donc sa propre péremption — le groupe est rejoué **une seconde fois**,
registre dans son état final. Le reçu n'est rafraîchi que si ce second rejeu passe réellement. Un
échec dû à une autre cause échoue deux fois et reste négatif ; un groupe ordinaire n'a jamais de
seconde chance ; un non-lancement n'en déclenche pas (rien n'a été écrit, donc rien n'a changé).

**Et une reprise explicite** : `--reprendre` remet dans la file les reçus déjà
`REVALIDATION_FAILED`. Un verdict négatif peut venir d'un état transitoire (machine saturée,
catalogue de données en retard) ; il n'est jamais levé sans rejeu, et un reçu ne redevient une
preuve que par le même chemin que les autres — tests passés, empreintes recalculées.

**Tests** : 10 nouveaux (seconde chance acceptée puis refusée, pas de seconde chance pour un
groupe ordinaire ni pour un non-lancement, reprise qui restaure, reprise qui échoue encore,
reprise qui ne fabrique pas de preuve sans fichier) ; 24 verts dans ce fichier.

Restaient 16 reçus en échec de sessions antérieures (`LCH-018`, `LCH-031` à `LCH-040`,
`ASF-041` à `ASF-048`), dont les groupes citent `test_sync_complete_clone.py` — le test du
catalogue en retard, blocage externe connu. La reprise dira lesquels échouent encore vraiment.

### Le « blocage externe » du catalogue n'en était pas un — et toute la roadmap est prouvée

Les 8 reçus qui résistaient citaient tous `test_sync_complete_clone.py`, dont le test de parité
byte-à-byte du catalogue de campagnes. Depuis des jours, ce rouge était classé « externe : 13 420
fichiers `catalog/` en retard, à resynchroniser par AlinaSync ». **La mesure dit autre chose.**

Sur les 4 947 manifestes suivis de `catalog/campaigns` :

| état du disque vs le blob Git | nombre |
|---|---|
| identique | 4 729 |
| **absent du disque** | **157** |
| **contenu réellement différent** (pas des fins de ligne) | **61** |

Les 61 fichiers différents sont tous plus PETITS que leur blob (−4 878 octets le plus souvent).
Comparaison du contenu, manifeste par manifeste : l'historique de campagne du disque est un
**sous-ensemble strict** de celui de Git — 128 entrées contre 137, et **zéro entrée locale absente
de Git**, sur les 61 fichiers sans exception. Aucun n'avait été écrit depuis 110,9 heures : rien
ne les produisait.

Donc restaurer l'état commité ne perdait rien, et je l'ai vérifié avant d'agir plutôt que de le
supposer. Les 61 fichiers ont été sauvegardés hors du dépôt, puis `catalog/campaigns` a été
restauré depuis le commit : **4 947 fichiers, 0 absent, 0 différent**. Le test passe (78 verts),
et les 8 reçus se sont rafraîchis au rejeu suivant.

### État des preuves de la roadmap

```
3 120 tâches · 3 120 reçus · 3 120 VERIFIED_DONE
preuves valides sur le HEAD actuel : 3 120 / 3 120 = 100,0 %
familles incomplètes : aucune
```

C'est la première fois de cette mission que chaque tâche de la roadmap porte une preuve **rejouée
et valide sur l'état actuel du code**. Parcours complet : 103 périmés → 102 rafraîchis ; 19 en
échec (dont 3 enfermés dans la circularité) → 11 rafraîchis ; 8 bloqués par le catalogue →
catalogue mesuré, restauré, 8 rafraîchis. Aucun verdict n'a été levé sans rejeu réel.

**Chantier 8 (preuve / certificateur / scoreboard) : clos sur le HEAD actuel.**

---

## 18/11/2026 — ITÉRATION 17 : produire les rubans du labo sans tenir le corpus en mémoire

Module neuf `src/hl_observer/backtesting/rubans_tri_externe.py` (251 lignes), **pas encore
branché** : son contrat devait d'abord être prouvé, et le gain mesuré sur le vrai corpus avant de
toucher au chemin qui produit les preuves.

**Le contrat : les octets produits sont identiques à ceux de l'approche en mémoire.** Deux passes
sur la source (les gagnants d'abord, l'écriture ensuite), des morceaux triés fusionnés en flux
(`heapq.merge`), et la même sérialisation exacte (`sort_keys`, `ensure_ascii=False`) — car cette
sérialisation fixe les empreintes publiées au manifeste, ce n'est pas un détail de forme.

### Deux pièges que les tests ont attrapés AVANT tout branchement

**1. Un dictionnaire Python qui remplace une valeur ne change pas la position de sa clé.** Le labo
remplace un fill vu en snapshot par le même fill vu en direct. Le tri stable d'origine ordonne donc
selon la **première** occurrence tout en écrivant le contenu **préféré**. Ma première version
triait sur l'index de la ligne écrite : l'ordre du ruban changeait dès qu'une préférence
s'appliquait. Le module retient maintenant les deux index. Trouvé par un tirage aléatoire, pas par
relecture.

**2. En Python, `1 == 1.0 == True` donnent la même entrée de dictionnaire.** Une empreinte qui les
distinguerait ferait diverger les deux chemins : deux lignes que le labo comptait pour une seule
deviendraient deux signaux. L'empreinte normalise donc les nombres comme le fait une clé de
dictionnaire — sans jamais faire passer un grand entier (`tid`, une cinquantaine de bits) par un
flottant.

### Ce que le module refuse de faire

Lire deux fois une source qui ne rend pas les mêmes lignes. Si le nombre de lignes change entre
les passes, ou si un gagnant désigné est introuvable, **aucun ruban n'est écrit** et les morceaux
temporaires sont nettoyés — plutôt qu'un ruban incomplet qui serait pris pour le corpus entier.

**Tests** : 21 verts, dont **300 tirages aléatoires** comparant les SHA-256 des deux chemins sur
des corpus mêlant doublons, clés de tri à égalité et snapshots ; la taille des morceaux (1, 2, 3,
7, 100 lignes) ne change pas un octet ; la passe 1 tient moins du tiers du corpus ; une source
instable fait refuser l'écriture ; un lien symbolique est refusé.

### Prochaine étape, et pourquoi elle est conditionnée

Le branchement exige de restructurer la boucle de chargement de `materialize_safe_workspace` en
deux passes par famille. C'est le chemin qui produit les preuves : il ne devait être fait que si
la mesure du gain sur le vrai corpus le justifiait. **Elle le justifie, et plus que prévu.**

### La mesure qui décide : 32,2 Go contre 1,65 Go

Famille `fills_forward` du coffre LOCAL, fenêtre depuis le 13/11, lue en flux (709 s) :

| | |
|---|---|
| lignes lues | 11 698 999 |
| identités distinctes | 9 315 971 (**2 383 028 doublons**) |
| taille d'une ligne en mémoire Python | **3 458 octets** |
| (a) dictionnaire identité → ligne, l'approche actuelle | **~32,2 Go** (extrapolation) |
| (b) passe 1 du tri externe | **1,65 Go** (mesure exacte) |
| gain | **19,5 ×** |

Une ligne de fill pèse 3,5 ko en mémoire — dix fois sa taille sur disque, parce qu'un dictionnaire
Python avec ses chaînes coûte cher. **Le labo essayait donc de tenir 32 Go sur une machine qui en a
32.** Ce n'était pas « un jour dense de trop » : c'était structurellement impossible, et le
`MEMOIRE_CRITIQUE` à 452 shards sur 5 570 en était la conséquence exacte.

Deux conséquences pour la suite :

* le branchement du tri externe est justifié : il fait passer les fills de 32,2 Go à 1,65 Go, et
  les carnets devraient suivre le même rapport. C'est ce qui rend les onze jours atteignables ;
* 2,38 millions de doublons sur la fenêtre : les shards du coffre se recouvrent largement
  (plusieurs voies écrivent les mêmes fills). La déduplication n'est pas un détail d'hygiène, elle
  représente un cinquième du volume.

### Le plan de branchement, et pourquoi il n'est pas fait ce matin

La lecture du code donne la forme exacte du travail, et ses pièges. Il est écrit ici pour être
repris sans refaire l'analyse.

**Ce qu'il faut changer.** `materialize_safe_workspace` charge les deux tiers dans sept
dictionnaires en UNE passe sur les shards, puis trie, puis écrit huit rubans. Le tri externe exige
l'inverse : une **fabrique rejouable par famille**, appelée deux fois.

1. extraire de la boucle SAFE un générateur `lignes_safe(assets, famille)` qui rend les lignes
   transformées (les transformations existent déjà : `_fill_rows`, `_book_row`,
   `_market_context_row`, `_accounting_context_row`) ;
2. ajouter au pont LOCAL le générateur équivalent. Attention : le pont **rejette un shard entier**
   quand son gzip est tronqué (`del _fills[debut_fills:]`). En flux, il faut donc bufferiser par
   shard et ne céder ses lignes qu'une fois le shard lu en entier — un shard tient en mémoire, le
   corpus non ;
3. remplacer l'accumulation par `ecrire_ruban_trie` pour les trois familles lourdes (fills,
   `book_l2`, `bbo`) et garder l'accumulation pour les cinq familles légères.

**Les quatre pièges repérés.**

* **Les compteurs d'audit sont alimentés pendant la transformation** (`payload_audit`,
  `historical_fill_observations`). Deux passes les compteraient deux fois : la seconde passe doit
  recevoir un compteur jetable.
* **Deux rubans sortent du même corpus dédoublonné** : `vault_fills.jsonl` (les snapshots) et
  `vault_fills_live.jsonl` (le direct causal). Il faut donc un prédicat de filtre à l'écriture, et
  non deux déduplications séparées — sinon un fill présent dans les deux formes serait compté deux
  fois.
* **La déduplication des cotations BBO est à état** (une par coin et par seconde) : cet état doit
  vivre dans la fabrique, pas dans la boucle.
* **Les bornes publiées au manifeste** (`fill_start_ms`, `fill_end_ms`, `unique_fills`) se lisent
  aujourd'hui sur les listes triées. En flux, elles se calculent au fil de l'eau — à vérifier
  contre les valeurs actuelles sur un petit corpus.

**Le critère de réussite est déjà écrit** : `ecrire_ruban_en_memoire` reste dans le module comme
référence. Un test d'intégration doit produire le ruban par les deux chemins sur un coffre
synthétique (comme `test_lab_coffre_injection`) et comparer les SHA-256. Tant que ce test n'existe
pas et ne passe pas, le branchement n'est pas acquis.

**Pourquoi pas ce matin** : la machine fait tourner la collecte et la fin de la suite de tests, et
la mesure ci-dessus a demandé à elle seule 12 minutes et 3,8 Go de pic. Restructurer le chemin qui
produit les preuves demande la machine libre et une passe de tests complète derrière. Ce n'est pas
un blocage externe : c'est une fenêtre de calme à prendre.

### Un chiffre absurde dénonce l'instrument, pas la donnée

La même sonde, lancée sur la famille `book_l2`, a rendu : **7 509 693 lignes pour 598 identités
distinctes**. Impossible — cela voudrait dire que le coffre contient 7,5 millions de copies de
598 carnets.

La cause est ma sonde : elle appliquait aux carnets la clé d'identité des **fills**
(`vault, coin, ts_ms, tid, hash, oid, px, sz, signe`). Un carnet ne porte aucun de ces champs sauf
`coin` : toutes les lignes d'un même coin devenaient donc la même identité, et 598 ≈ le nombre de
coins observés. Le labo, lui, utilise la bonne clé
(`coin, received_at_ms, exchange_ts_ms, bid, ask, bids5, asks5`).

Publié tel quel, ce chiffre aurait fait croire à une déduplication massive des carnets et fondé le
dimensionnement du branchement sur une illusion. Corrigé : la sonde choisit désormais la clé de la
famille demandée et refuse de mesurer une famille dont elle ne connaît pas la clé — plutôt que
d'en appliquer une par défaut. La mesure des carnets est relancée.

### Le total, et le feu vert

| famille | lignes | identités | approche actuelle | passe 1 du tri externe | gain |
|---|---|---|---|---|---|
| `fills_forward` | 11 698 999 | 9 315 971 | ~32,2 Go | 1,65 Go | 19,5 × |
| `book_l2` | 7 509 693 | 7 448 613 | ~28,3 Go | 1,39 Go | 20,4 × |
| **total** | **19,2 M** | **16,8 M** | **~60,5 Go** | **3,04 Go** | **20 ×** |

Soixante gigaoctets demandés à une machine qui en a trente-deux. Le labo ne pouvait pas lire la
fenêtre, et aucun réglage de ses seuils n'y aurait rien changé. Avec 3 Go, les onze jours sont à
sa portée. Les carnets ne portent presque aucun doublon (61 080 sur 7,5 M), contrairement aux
fills (2,4 M) : les voies d'écriture des fills se recouvrent, celles des carnets non.

### Les trois briques du chantier, et les cinq pièges qu'elles ont révélés

Le branchement demandait des briques dont le comportement soit identique, au détail près, à celui
du labo. Elles sont livrées et testées (59 tests) :

| brique | rôle |
|---|---|
| `rubans_tri_externe.py` | un ruban trié et dédoublonné en deux passes, morceaux fusionnés en flux, **octets identiques** à l'ancien chemin ; écrit plusieurs rubans en une seule seconde passe |
| `copy_vault_rubans_lourds.py` | expose les deux tiers du coffre comme des générateurs rejouables, et écrit les trois rubans lourds |
| pont LOCAL, `garder_replay=False` | **compte sans matérialiser** ; décomptes prouvés identiques à ceux de la matérialisation |

**Cinq pièges, chacun aurait changé le contenu des rubans, et aucun n'a été trouvé par relecture :**

1. **Un dictionnaire Python qui remplace une valeur ne déplace pas sa clé.** Le tri stable
   ordonnait donc selon la PREMIÈRE occurrence tout en écrivant la ligne préférée. Trouvé par
   tirage aléatoire.
2. **`1 == 1.0 == True` donnent la même entrée de dictionnaire.** Une empreinte qui les
   distinguerait transformerait une ligne en deux signaux. L'empreinte normalise donc les nombres
   comme une clé de dictionnaire, en descendant dans les listes imbriquées (les carnets portent
   leurs niveaux de prix dans leur identité) et sans jamais faire passer un grand entier par un
   flottant.
3. **Une ligne du tier LOCAL ne déloge jamais une ligne SAFE**, pas même un snapshot : le labo
   insérait les lignes SAFE avec remplacement, puis les lignes LOCAL par `setdefault`. Il faut
   donc **trois** rangs de préférence (SAFE direct, SAFE snapshot, LOCAL), pas deux.
4. **Un fill non-snapshot d'une source non causale n'entre dans AUCUN ruban**, tout en comptant
   dans `unique_fills`. Mon premier filtre l'aurait versé au ruban du direct.
5. **Un `isSnapshot` absent, nul ou entier est un refus, pas un « faux »** : `is True` / `is False`
   et non un booléen tronqué.

Un sixième point, de performance : les deux rubans de fills sortent du même corpus dédoublonné et
s'écrivent en **une seule** seconde passe. Les écrire l'un après l'autre relirait onze millions de
lignes une fois de plus — 709 secondes par passe à la mesure du jour.

### La suite complète est VERTE

Passage par lots terminé : **19 lots sur 19**, et le lot qui portait le seul rouge rejoué après la
remise en état des reçus.

```
19 lots  ·  19 086 réussis  ·  68 ignorés  ·  1 attendu en échec  ·  0 ROUGE
```

Le rouge unique du premier passage était `rig_020`, enregistré **avant** la revalidation des
reçus de ce matin ; son lot rejoué donne 1 008 verts. Je l'ai rejoué plutôt que d'affirmer qu'il
était corrigé : un bilan qui garde un rouge périmé n'est pas un bilan.

Rappel de ce que ce passage a coûté en méthode : les douze derniers lots du premier essai n'avaient
jamais démarré (`0xC0000142`, machine saturée) et mon pilote les avait enchaînés au lieu de
réessayer. Corrigé, puis repris : les douze ont tourné.

C'est la première fois de cette mission que la suite complète passe **sans aucun rouge**, et elle
le fait sur un HEAD où les 3 120 preuves de la roadmap sont valides.

