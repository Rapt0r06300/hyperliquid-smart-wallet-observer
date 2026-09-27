# AGENTS.md — Alina Smart Flow

Dernière mise à jour : **2026-09-27**.

Ce fichier est le **contrat d'exécution compact pour agents de code**. Il doit permettre à un agent de reprendre Alina correctement sans relire tout l'historique du projet ni reconstruire l'architecture à partir d'anciens documents.

Il ne remplace pas la spec canonique. Il explique **comment travailler correctement sur la spec, le HEAD courant et les deux repositories** avec un minimum de quota, sans PC utilisateur, sans architecture parallèle et sans faux `DONE`.

---

## 1. Autorité

Ordre d'autorité :

1. `SECURITY.md`
2. `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`
3. code + tests + workflows + manifests + receipts du **HEAD courant**
4. ce fichier
5. `CLAUDE.md`
6. `README.md`
7. documentation ciblée réellement pertinente au bloc courant
8. anciens rapports, anciennes roadmaps, anciens prompts et anciens addenda

Règles :

- la spec canonique est **unique** ;
- elle est mise à jour **en place** ;
- ne jamais créer une nouvelle spec `V6.x`, `final`, `vNext`, `bis` ou équivalente ;
- les anciens labels de versions dans la spec sont des marqueurs historiques, pas des autorités concurrentes ;
- un ancien rapport `DONE` ne vaut rien face à un HEAD, un receipt ou une preuve actuelle qui dit le contraire ;
- ne jamais inventer une exigence absente de la spec ou du code réel ;
- ne jamais supprimer silencieusement une exigence sous prétexte qu'elle semble ancienne.

---

## 2. Repositories canoniques

### Repo principal

`Rapt0r06300/hyperliquid-smart-wallet-observer`

Branche source de vérité :

`main`

Runtime actif :

`src/hl_observer/`

Responsabilités principales :

- intention opérateur ;
- orchestration sémantique ;
- control plane ;
- stratégies ;
- collecte côté code ;
- market truth ;
- replay/backtest ;
- OOS/forward ;
- simulation/exécution paper ;
- PnL ;
- scoreboard ;
- sécurité ;
- operator surface ;
- contrats cross-repo ;
- preuves et receipts légers associés au code.

### Dataset V2

`Rapt0r06300/alina-smartflow-datasets-v2`

Branche source de vérité :

`main`

Responsabilités principales :

- état durable des campagnes cloud lourdes ;
- manifests ;
- leases ;
- checkpoints ;
- catalogue de données ;
- états `incoming/quarantine/safe/rejected` ;
- replay-compatibility evidence ;
- index et quality state ;
- gros shards immuables publiés via les mécanismes Dataset V2 ;
- evidence/receipts lourds.

### Règle de ownership

Un même objet mutable ne doit avoir **qu'une seule autorité**.

Ne jamais créer :

- un deuxième progress store ;
- un deuxième ledger de campagne ;
- un deuxième checkpoint store ;
- un deuxième manifest mutable concurrent ;
- une copie locale prétendant être l'autorité d'un état Dataset V2.

Le repo principal peut conserver l'intention, la référence, l'identité et le receipt. Dataset V2 conserve l'état durable des campagnes de données lourdes.

---

## 3. Runtime actif et legacy

Le runtime actif est :

`src/hl_observer/`

Le package :

`hyper_smart_observer/`

est **legacy/compatibilité/audit**.

Interdiction de créer une nouvelle architecture dans `hyper_smart_observer/`.

Si une fonction existe déjà dans `src/hl_observer/`, l'étendre ou la câbler avant de créer un système parallèle.

Ne pas créer un deuxième :

- orchestrateur ;
- phase controller ;
- replay engine ;
- PnL truth engine ;
- ledger ;
- RiskEngine ;
- scoreboard ;
- Dataset system ;
- campaign engine ;
- market-truth pipeline ;
- fill engine ;
- event-intelligence pipeline.

Préférer de petits modules importables et du wiring mince vers les callers existants.

---

## 4. Mission économique

Trois familles seulement peuvent matérialiser du paper PnL canonique :

- `copy_vault`
- `lead_lag`
- `cross_venue_dislocation`

Autorité code :

`src/hl_observer/strategies/active_scope.py`

Le scope actuel distingue également des familles `SHADOW`, `RESEARCH_ONLY` ou `DISABLED`.

En particulier :

`funding_carry = DISABLED_BY_SCOPE`

Ne jamais réactiver Carry pour “aider” l'objectif économique.

### Cible

Objectif final :

**>= +4.00 USD NET/jour PROUVÉS pour chacune des trois familles actives, séparément.**

Aucune compensation entre familles.

Un module non prouvé doit rester dans un état honnête :

- `PROVEN`
- `MORE_DATA`
- `UNMEASURABLE`
- `KILL`

Ne jamais modifier les hypothèses, frais, coûts, filtres ou gates uniquement pour obtenir artificiellement `PROVEN`.

---

## 5. Sécurité absolue

Alina est :

**PAPER / READ-ONLY / FAIL-CLOSED**

Interdit :

- ordre réel ;
- ordre testnet ;
- activation d'un chemin mainnet d'exécution ;
- activation d'un chemin testnet d'exécution ;
- endpoint `/exchange` opérationnel ;
- private key ;
- seed ;
- mnemonic ;
- signature ;
- dépôt ;
- retrait ;
- transfert ;
- ordre réel par SDK tiers ;
- secret permettant de signer des ordres ;
- ajout d'une feature qui rend l'exécution réelle atteignable.

La doctrine runtime doit rester compatible avec :

`HL_ENABLE_MAINNET_EXECUTION=0`

`HL_ENABLE_TESTNET_EXECUTION=0`

et les protections équivalentes réellement présentes au HEAD.

### Fail-closed

Si une donnée nécessaire est :

- absente ;
- stale ;
- contradictoire ;
- partielle ;
- mal horodatée ;
- non vérifiable ;
- ambiguë ;
- non causalement ordonnée ;

alors :

- refuser ;
- classer `UNKNOWN`, `PARTIAL`, `UNMEASURABLE` ou état équivalent ;
- ne jamais remplacer par zéro ;
- ne jamais remplacer par une valeur par défaut silencieuse ;
- ne jamais fabriquer un timestamp ;
- ne jamais présenter une donnée synthétique comme vraie.

**Missing != 0.**

**Unknown != healthy.**

---

## 6. Aucun PC utilisateur pour les missions Work/GitHub

Pour ChatGPT Work, GitHub Actions et toute automatisation cloud Alina :

- GitHub-hosted uniquement ;
- aucun self-hosted runner ;
- aucun réveil du PC utilisateur ;
- aucun tunnel vers le PC ;
- aucun SSH vers le PC ;
- aucun service local utilisateur ;
- aucun chemin Windows utilisateur requis ;
- aucun daemon local utilisateur ;
- aucun partage réseau vers le PC ;
- aucune dépendance au fait que le PC soit allumé.

Un agent local explicitement lancé par l'utilisateur peut utiliser son environnement local.

Une mission **Work Cloud / GitHub** ne doit jamais basculer vers ce chemin.

### Workflows historiques

Le dépôt contient encore des artefacts historiques dont le nom ou le contenu mentionne self-hosted/PC, notamment des anciens workflows HyperSmart.

Les versions inspectées au moment de cette mise à jour sont hard-disabled avec une condition de type `if: false` et ne constituent pas la voie canonique.

Ne jamais :

- les réactiver ;
- retirer leur garde-fou pour gagner du temps ;
- réintroduire `runs-on: self-hosted` ;
- reconstruire une liaison GitHub -> PC -> GitHub.

La direction canonique est **GitHub-hosted only**.

---

## 7. Contraintes GitHub Actions à respecter

Règles vérifiées dans la documentation officielle GitHub :

- un job standard GitHub-hosted s'exécute dans une instance fraîche du runner ;
- ne jamais supposer qu'un fichier local au runner survivra au job suivant ;
- persister l'état utile dans Git, Dataset V2, artifacts/releases autorisés ou receipts durables ;
- un job GitHub-hosted standard a une durée maximale documentée de **6 heures** ;
- les campagnes longues doivent donc être segmentées et resumables ;
- checkpoint avant timeout ;
- reprise idempotente depuis l'état durable ;
- aucun résultat correct ne doit dépendre de la mémoire d'un runner précédent.

### Dispatch

Pour les workflows chaînés :

- préférer `workflow_dispatch` ou `repository_dispatch` lorsqu'un déclenchement explicite est nécessaire ;
- ne pas supposer qu'un `push` produit par un workflow avec son `GITHUB_TOKEN` va déclencher récursivement tous les workflows attendus ;
- GitHub documente `workflow_dispatch` et `repository_dispatch` comme exceptions explicites au blocage anti-récursion de `GITHUB_TOKEN`.

### Schedules

Un `schedule` GitHub est un **watchdog opportuniste**, pas une horloge financière exacte.

Le système doit rester correct si :

- le schedule est en retard ;
- un run est sauté ;
- un runner n'est pas immédiatement disponible.

Un retard peut affecter la fraîcheur ou le temps de complétion. Il ne doit jamais corrompre la logique d'identité, de lease, de checkpoint ou de phase.

---

## 8. Contrat de mission pour un agent

Quand l'utilisateur demande :

- implémenter ;
- corriger ;
- améliorer ;
- continuer ;
- finir ;
- terminer toute la spec ;
- fermer le backlog ;

considérer la demande comme **une mission complète**, pas comme une demande de conseils.

Avant de modifier quoi que ce soit, établir mentalement un petit contrat :

- objectif ;
- contraintes ;
- fichiers/surfaces probables ;
- preuves nécessaires ;
- Definition of Done ;
- travail restant.

Puis exécuter.

### Règles de continuité

- ne pas s'arrêter après un plan ;
- ne pas s'arrêter après une recherche ;
- ne pas s'arrêter après un premier fichier ;
- ne pas s'arrêter après un test vert ;
- ne pas s'arrêter après un commit ;
- ne pas s'arrêter après une PR ;
- ne pas redemander l'autorisation pour poursuivre une mission déjà clairement autorisée ;
- continuer tant qu'il reste du travail demandé et réalisable.

### Échec répété

Si une action échoue **deux fois de la même manière** :

- ne pas boucler ;
- changer de méthode ;
- utiliser une autre API, un autre chemin, un autre parseur, une autre stratégie ou une autre granularité.

### Blocage réel

Si une limite de plateforme/service/outillage bloque une partie du travail :

1. finir tout ce qui est indépendant ;
2. vérifier ce qui est réellement terminé ;
3. produire un checkpoint exact :
   - HEAD ;
   - fichiers modifiés ;
   - preuves disponibles ;
   - blocage exact ;
   - travail restant ;
   - prochaine action.

Ne jamais simuler du travail en arrière-plan.

---

## 9. Préflight obligatoire avant modification importante

Avant une décision technique importante ou une reprise de chantier :

1. lire le HEAD courant de `main` ;
2. vérifier l'état de la branche réellement ciblée ;
3. lire `SECURITY.md` ;
4. lire ce fichier ;
5. lire la spec canonique pour identifier le bloc réellement ouvert ;
6. lire seulement les fichiers nécessaires à ce bloc ;
7. inspecter les callers ;
8. inspecter les tests correspondants ;
9. inspecter les workflows/manifests/receipts correspondants si le bloc est cloud/data.

Ne pas utiliser un ancien SHA de conversation comme vérité sans relire le HEAD.

---

## 10. Usage de la spec avec quota minimal

La spec canonique est très grande.

Bonne méthode :

1. la lire une fois au début d'une grosse mission pour construire la carte du travail ;
2. identifier les sections `OPEN-*`, `WKR-*`, runbook et closure matrix pertinentes ;
3. travailler par blocs ciblés ;
4. revenir uniquement aux sections nécessaires ;
5. ne pas relire toute la spec après chaque commit.

Ne pas scanner :

- tout l'historique Git ;
- toutes les anciennes roadmaps ;
- tous les logs ;
- tous les fichiers archive ;

sauf nécessité précise.

Le HEAD, les manifests et les receipts ont priorité pour reconstruire l'état réel.

---

## 11. Mode quota minimal absolu

Le modèle doit être utilisé là où il apporte une vraie valeur de raisonnement.

Privilégier :

- `git`
- `rg` / `grep`
- parsers
- scripts Python
- JSON
- jq
- hashes/checksums
- diffs
- compteurs déterministes
- replays
- backtests
- tests
- lint
- static analysis
- petites requêtes GitHub ciblées

Éviter :

- plusieurs agents faisant la même chose ;
- relire les mêmes gros fichiers ;
- résumer le projet à chaque étape ;
- générer des rapports intermédiaires non demandés ;
- multiplier les recherches web une fois le contrat technique compris ;
- faire travailler le modèle sur un calcul simple ;
- créer du code exploratoire jetable si un script déterministe suffit.

Par défaut :

**un seul agent principal.**

Pas de swarm, subagents ou multi-agent sauf demande explicite.

---

## 12. Mode “implémentation totale d'abord, tests tous ensemble à la fin”

Si l'utilisateur demande explicitement :

**implémentation totale de la spec d'abord, tests/CI/replays ensuite**

respecter cet ordre.

Pendant la phase d'implémentation :

- coder ;
- câbler ;
- migrer ;
- adapter les tests ;
- adapter les workflows ;
- adapter les manifests/schemas ;
- sauvegarder de vrais diffs ;
- continuer vers le bloc suivant.

Ne pas lancer systématiquement :

- full pytest ;
- grosse CI ;
- replay long ;
- backtest long ;
- OOS ;
- forward ;
- campagne de collecte longue ;

entre chaque petit changement.

Exception :

un test ciblé extrêmement court est permis si nécessaire pour comprendre une API, une signature ou débloquer une erreur de compilation/import.

### Validation finale

Après épuisement du backlog d'implémentation :

1. lint/static ;
2. sécurité ;
3. tests ciblés critiques ;
4. suite globale pertinente ;
5. workflows cloud nécessaires ;
6. replay/backtest ;
7. OOS ;
8. forward paper ;
9. PnL proof ;
10. scoreboard ;
11. receipts ;
12. closure matrix.

Ce mode change **l'ordre**, pas les exigences finales.

---

## 13. Control plane actuel

Le HEAD contient une fondation réelle sous :

`src/hl_observer/control_plane/`

notamment :

- `phase_state.py`
- `phase_controller.py`
- `phase_cli.py`
- `resumable_campaign.py`
- `dispatch_receipt.py`
- `campaign_adapters.py`
- `module_pnl_proof.py`
- `typed_events.py`

Ne pas recréer ces concepts ailleurs.

### Phases canoniques

- `IDLE`
- `COLLECT`
- `ANALYZE`

### Sémantique

#### IDLE

- aucun nouveau travail lourd ;
- statut/lecture possibles ;
- état durable conservé.

#### COLLECT

- création de travail de collecte uniquement ;
- toute campagne doit être liée à un `phase_epoch` ;
- pas de nouveau replay/backtest/PnL proof.

#### ANALYZE

- geler la création de nouvelles collectes ;
- fixer un `collection_cutoff` ;
- référencer le `source_collection_epoch` ;
- drainer les campagnes déjà revendiquées ;
- exécuter la chaîne d'analyse.

Pipeline :

`DRAIN -> QUALITY -> REPLAY -> BACKTEST -> OOS -> FORWARD_PAPER -> PNL_PROOF -> SCOREBOARD -> DONE`

La présence d'un module ou d'une classe n'autorise jamais à fermer automatiquement un `OPEN-*` ou `WKR-*`.

---

## 14. Campaign schema v2

Les nouvelles campagnes canoniques doivent transporter l'identité suffisante pour être :

- traçables ;
- resumables ;
- idempotentes ;
- rattachées à une phase ;
- rattachées à un SHA ;
- rattachées à une sélection Dataset V2 ;
- fermables avec une preuve.

Selon le contrat canonique, les champs/identités attendus couvrent notamment :

- `campaign_id`
- `campaign_kind`
- `code_sha`
- config/work-plan hash
- dataset generation
- creation phase
- `phase_epoch`
- `source_collection_epoch`
- collection cutoff
- dataset selection id
- lease
- checkpoint lineage
- terminal evidence digest

Les anciens manifests v1 restent historiques/read-only.

Ne pas réécrire l'histoire d'une campagne ancienne pour lui donner artificiellement un schema v2.

---

## 15. Dispatch cross-repo

Pattern canonique :

`operator intent -> idempotent dispatch -> Dataset V2 campaign -> worker -> durable receipt -> main status`

Le dispatch doit être :

- explicite ;
- idempotent ;
- hashé/déterministe ;
- lié au repo ;
- lié au SHA ;
- lié à la phase ;
- lié à l'epoch ;
- rejouable sans duplication logique.

Ne jamais utiliser le fait qu'un commit de données a été poussé comme unique mécanisme implicite de réveil cross-repo.

Lorsque la chaîne doit déclencher un workflow, utiliser un mécanisme explicite compatible GitHub :

- `workflow_dispatch`
- `repository_dispatch`

avec permissions minimales.

---

## 16. Resume des campagnes longues

Toute campagne destinée à dépasser une fenêtre raisonnable de GitHub-hosted doit être segmentée.

Un segment doit pouvoir :

- lire son manifest ;
- acquérir/renouveler un lease ;
- reprendre au dernier checkpoint ;
- traiter une portion bornée ;
- écrire un checkpoint atomique ;
- publier l'evidence ;
- libérer/expirer le lease proprement ;
- être relancé sans doubler les résultats.

Avant d'annoncer le resume “prouvé”, exiger un vrai scénario **fresh runner segment 1 -> durable checkpoint -> fresh runner segment 2 -> continuation**.

Une reprise sur le même process ou le même disque local ne prouve pas le contrat cloud.

---

## 17. Données replay-grade

Une donnée utile à la recherche n'est pas forcément utilisable comme preuve économique.

Selon le chemin, préserver ou prouver :

- exchange timestamp ;
- receive wall-clock timestamp ;
- receive monotonic timestamp ;
- clock offset ;
- RTT ;
- uncertainty ;
- BBO ;
- L2 ;
- trades ;
- snapshot/delta semantics ;
- sequence ;
- gaps ;
- out-of-order ;
- duplicates ;
- native trade ID ;
- fallback stable identity ;
- fee provenance ;
- tick size ;
- lot size ;
- minimum notional ;
- multiplier ;
- quote currency ;
- depth ;
- VWAP ;
- capacity ;
- quote age ;
- venue status ;
- source health ;
- manifests ;
- hashes/checksums.

Ne jamais inventer ce qui manque.

Une archive exchange-time-only ne devient pas live-quality par simple normalisation.

---

## 18. Venues prioritaires

Sources/venues principales à préserver ou vérifier :

- Hyperliquid
- Binance
- Bybit
- OKX
- Gate
- Bitget

Le code actuel contient des adaptateurs/collecteurs dédiés pour ces surfaces.

Ne pas confondre :

- “fichier présent”
- “import fonctionne”
- “collecteur actif”
- “source healthy”
- “donnée replay-compatible”
- “preuve économique exploitable”

Ce sont des niveaux différents.

---

## 19. Règles Hyperliquid

Chemins publics/read-only uniquement dans le runtime officiel.

La documentation Hyperliquid distingue :

- `/info` pour lire des informations ;
- `/exchange` pour les actions de trading.

Alina ne doit pas rendre `/exchange` atteignable.

### Pagination

La documentation officielle indique que certaines réponses `/info` sur plage temporelle sont limitées à **500 éléments ou blocs distincts**.

Pour une plage plus grande :

- paginer ;
- reprendre depuis le dernier timestamp retourné ;
- détecter stagnation et boucles ;
- prouver la complétude ;
- ne pas supposer qu'un seul appel couvre la période.

### WebSocket

Les clients doivent :

- gérer les disconnects ;
- reconnecter proprement ;
- resubscribe ;
- réconcilier snapshot et état déjà traité ;
- utiliser `isSnapshot` pour les flux qui l'exposent ;
- dédupliquer ;
- backfiller le gap par `/info` si nécessaire.

Un reconnect sans reconciliation n'est pas une collecte fiable.

---

## 20. CCXT

CCXT reste **discovery-only** sauf changement explicite de la spec.

Dans le packaging actuel, il est isolé dans l'extra :

`discovery`

Ne pas utiliser CCXT comme remplacement rapide des collecteurs natifs Hyperliquid/Binance/Bybit/OKX/Gate/Bitget.

Ne pas utiliser ses APIs d'ordre.

Son rôle :

- découvrir venues/markets ;
- enrichir un univers ;
- identifier intersections ;
- détecter de nouveaux candidats.

Pas de PnL proof direct depuis une simple découverte CCXT.

---

## 21. Dataset V2 lifecycle

Cycle conceptuel :

`incoming -> quarantine -> safe -> replay-compatible -> selected evidence -> economic proof eligibility`

avec `rejected` lorsque la qualité ne passe pas.

Règles :

- `SAFE != replay-compatible`
- `replay-compatible != economically proven`
- `repository globally healthy != selected experiment proven`

Une preuve économique doit référencer la sélection exacte utilisée.

Conserver :

- shard IDs ;
- hashes ;
- start/end timestamps ;
- schema/version ;
- dataset generation ;
- catalog/index hashes ;
- quality evidence ;
- replay compatibility ;
- cost evidence ;
- split evidence.

---

## 22. Exact trade counts et unicité

Ne jamais utiliser un nombre approximatif comme fermeture d'un contrat “exact”.

Si la spec exige :

- `trade_count_exact`
- `unique_trade_count_exact`

alors la fermeture exige :

- couverture complète des shards sélectionnés ;
- méthode d'identité stable ;
- déduplication déterministe ;
- absence de shard “unknown” ;
- preuve machine-readable.

Un total partiel + extrapolation n'est pas exact.

---

## 23. Copy-Vault

Objectif :

mesurer si un leader/vault est **copiable**, pas seulement profitable.

Vérifier selon le bloc :

- wallet/vault identity ;
- fills complets ;
- position lifecycle ;
- `OPEN/ADD/REDUCE/CLOSE` ;
- startup bootstrap ;
- reconnect overlap ;
- exactly-once source fill ;
- state versioning ;
- stale leader state ;
- queue/backlog ;
- source execution style ;
- maker/taker ;
- leader price quality ;
- target exposure ;
- partial closes ;
- reduce-only ;
- exit semantics ;
- capacity ;
- visible liquidity ;
- leverage/margin ;
- concentration ;
- slippage ;
- latency ;
- copyability erosion ;
- drift/reconciliation.

Un bon leader brut peut être un mauvais leader copiable.

Le PnL doit correspondre à **Alina**, pas au PnL historique du leader.

---

## 24. Lead-Lag

Objectif :

mesurer un edge causal court-terme entre venues.

Exiger selon le chemin :

- horloges certifiées ;
- exchange/receive timing ;
- causal ordering ;
- no-lookahead ;
- source alignment ;
- BBO ;
- L2/book confirmation si nécessaire ;
- queue economics si maker ;
- missed fills ;
- latency ;
- spread ;
- slippage ;
- fees ;
- dependence clustering ;
- effective-N ;
- regime stability ;
- OOS ;
- forward post-freeze.

Une corrélation rétrospective n'est pas un Lead-Lag prouvé.

---

## 25. Cross-Venue Dislocation

Ne jamais certifier un spread au mid-price.

Exiger selon le chemin :

- deux jambes observées causalement ;
- BBO suffisamment synchronisés ;
- L2 reconstructible lorsque nécessaire ;
- profondeur des deux jambes ;
- VWAP ;
- fees par jambe ;
- slippage ;
- latency ;
- quote age ;
- tick/lot/min-notional ;
- multiplier ;
- capacity ;
- non-atomic execution risk ;
- adverse movement ;
- convergence/exit ;
- funding seulement lorsqu'il est économiquement pertinent.

Si le coût dépasse le spread, le bon résultat est :

**rejeter l'opportunité.**

Ne jamais détendre artificiellement les coûts pour rendre le module positif.

---

## 26. Event Intelligence — 120 idées

Sous-système :

`src/hl_observer/event_intelligence/`

Registre humain :

`docs/event-intelligence-120-coverage.md`

Le fait que le registre indique “implémenté” ne prouve pas :

- le wiring réel ;
- la présence dans le caller économique ;
- la collecte réelle ;
- l'OOS ;
- le forward ;
- l'edge.

Pour la fermeture canonique, utiliser une classification machine explicite, par exemple :

- `IMPLEMENTED_AND_WIRED`
- `IMPLEMENTED_BUT_PARTIAL`
- `IMPLEMENTED_BUT_NOT_WIRED`
- `BROKEN`
- `MISSING`
- `NOT_APPLICABLE`

La preuve économique est séparée :

`PROVEN_EDGE`

Ne jamais transformer un contexte externe en BUY/SELL direct sans chemin causal et économique validé.

---

## 27. Market Truth et fills

Chaîne conceptuelle cible :

`Signal -> Gate -> PaperIntent -> Canonical Execution -> Fill -> Position -> Ledger -> Liquidatable Equity`

Quand un chemin économique exige une exécution réaliste :

- ne pas utiliser un simple mid comme fill ;
- consommer la profondeur ;
- modéliser partial fills ;
- modéliser missed fills ;
- appliquer fees ;
- appliquer slippage ;
- appliquer latency ;
- respecter tick/lot/min-notional ;
- utiliser queue model lorsque maker ;
- conserver la provenance du modèle de coûts.

Replay et forward doivent parler le même langage économique autant que possible.

---

## 28. PnL canonique

Un PnL brut n'est pas une preuve.

Selon la famille, intégrer :

- fees ;
- spread ;
- slippage ;
- latency ;
- partial fills ;
- missed fills ;
- liquidity ;
- depth ;
- capacity ;
- funding pertinent ;
- exits ;
- liquidation/risk constraints ;
- drawdown ;
- causality ;
- no-lookahead ;
- dependence ;
- effective-N ;
- OOS ;
- forward post-freeze.

Le scoreboard doit être rattaché au :

- SHA ;
- dataset selection ;
- phase/epoch ;
- période ;
- coût ;
- config hash ;
- freeze boundary.

---

## 29. TRAIN / validation / OOS / forward

Ne jamais mélanger les rôles.

### TRAIN

Permet :

- recherche ;
- tuning ;
- sélection ;
- rejet d'hypothèses.

### Validation

Si prévue :

- filtre avant freeze ;
- jamais confondue avec OOS.

### OOS

Doit être untouched relativement au choix final.

### Forward paper

Doit être post-freeze.

### Règle de contamination

Si un segment OOS/forward est observé puis utilisé pour retuner :

- il devient feedback de recherche ;
- il n'est plus untouched ;
- il ne peut plus être présenté comme preuve finale indépendante.

---

## 30. Freeze boundary

Une preuve finale doit identifier :

- la config figée ;
- son hash ;
- le code SHA ;
- le dataset selection id ;
- le cutoff ;
- le moment du freeze ;
- les segments post-freeze.

Ne pas modifier silencieusement une config après avoir commencé à accumuler le forward censé la certifier.

---

## 31. Tests

Ne jamais :

- supprimer un test pour faire vert ;
- remplacer un test strict par un smoke faible ;
- ajouter un `skip`/xfail sans justification normative ;
- masquer une exception ;
- rendre une gate permissive pour faire passer un scénario positif.

Les tests doivent protéger :

- safety ;
- invariants ;
- idempotency ;
- causality ;
- no-lookahead ;
- schema ;
- replay parity ;
- data quality ;
- PnL accounting ;
- cross-repo contracts.

---

## 32. CI

La CI canonique doit rester GitHub-hosted.

Le workflow principal actuel est :

`.github/workflows/ci.yml`

Il contient notamment des surfaces de :

- sécurité ;
- imports ;
- tests Linux shardés ;
- tests Windows critiques ;
- replay/runtime parity ;
- portabilité.

Les actions importantes sont actuellement épinglées par SHA dans la CI inspectée.

Ne pas ajouter un nouveau pipeline concurrent si le pipeline existant peut être étendu.

---

## 33. Git discipline

`main` est l'état final canonique.

Avant modification :

- vérifier HEAD ;
- vérifier le fichier ciblé ;
- préserver les changements existants.

Éviter :

- `reset --hard`
- clean destructeur
- rebase destructif
- remplacement massif non nécessaire
- branches parallèles inutiles

Si la plateforme autorise l'écriture directe sur `main`, préférer la modification minimale nécessaire.

Si la plateforme impose une PR, utiliser une branche courte ciblant `main`.

### Commit

Un commit annoncé doit avoir un vrai diff.

Avant de dire “sauvegardé” ou “terminé” :

- lire le HEAD final ;
- vérifier le commit ;
- vérifier les fichiers réellement modifiés ;
- vérifier le diff ;
- vérifier qu'il n'est pas vide.

Un commit n'est jamais une raison de s'arrêter si la mission contient encore du travail réalisable.

---

## 34. Pas de duplication documentaire

Documents d'autorité :

- `SECURITY.md`
- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- spec canonique

Ne pas créer un nouveau document “final” contenant une deuxième version de la même doctrine.

Si une règle change :

- mettre à jour la spec canonique si elle est normative ;
- mettre à jour `AGENTS.md` si elle affecte l'exécution agent ;
- mettre à jour `README.md` si elle affecte la présentation/architecture générale ;
- mettre à jour `CLAUDE.md` pour compatibilité agent si nécessaire.

---

## 35. Ce qui ne constitue PAS un DONE

Ne suffit pas :

- fichier créé ;
- classe créée ;
- import vert ;
- test unitaire vert ;
- workflow vert ;
- commit présent ;
- campagne créée ;
- campaign “claimed” ;
- process alive ;
- SAFE ;
- replay smoke ;
- backtest positif ;
- PnL brut positif ;
- screenshot ;
- texte dans un rapport ;
- “implémenté” dans un registre humain.

Pour être DONE, une feature doit être :

- réellement codée ;
- câblée ;
- appelée ;
- persistée si nécessaire ;
- testée selon le mode de mission ;
- prouvée au niveau exigé par la spec.

---

## 36. Definition of Done globale

La mission globale n'est DONE que si la closure matrix canonique est satisfaite.

La fermeture doit notamment démontrer :

- cohérence repo principal / Dataset V2 ;
- phase authority réelle ;
- campaign schema v2 là où requis ;
- dispatch idempotent ;
- absence de split-brain ;
- resume cloud réel ;
- dataset selection immuable ;
- exact counts lorsque requis ;
- replay compatibility ;
- data source evidence ;
- OOS ;
- forward paper ;
- PnL proof ;
- scoreboard ;
- Event Intelligence wiring status ;
- sécurité paper/read-only ;
- `self_hosted_used = false` ;
- `real_execution_reachable = false`.

---

## 37. Final receipt recommandé

À la fin d'une mission globale, produire ou vérifier un receipt machine-readable contenant au minimum lorsque applicable :

- `main_alina_head`
- `dataset_v2_head`
- `canonical_spec_blob`
- `phase`
- `phase_epoch`
- `source_collection_epoch`
- `analysis_stage`
- `campaign_ids`
- `workflow_run_ids`
- `dataset_selection_id`
- `trade_count_exact`
- `unique_trade_count_exact`
- `safe_count`
- `replay_compatible_count`
- `copy_vault_status`
- `lead_lag_status`
- `cross_venue_status`
- `oos_status`
- `forward_status`
- `two_segment_resume_status`
- `event_intelligence_wiring_complete`
- `scoreboard_artifact`
- `paper_read_only`
- `self_hosted_used`
- `real_execution_reachable`
- `remaining_blockers`

Une valeur inconnue doit rester inconnue, pas devenir un faux zéro.

---

## 38. Ordre d'implémentation recommandé pour une fermeture totale

Lorsque la spec demande une fermeture globale et que les blocs sont encore ouverts, privilégier l'ordre suivant sans recréer ce qui existe déjà :

1. phase-state authority ;
2. transitions phase/controller ;
3. campaign schema v2 ;
4. split-brain prevention ;
5. cross-repo dispatch/receipts ;
6. operator surface ;
7. GitHub-hosted firewall ;
8. durable resume/checkpoints ;
9. exact/global unique counts ;
10. SAFE -> replay-compatible migration ;
11. native source capability/evidence ;
12. quality gates ;
13. replay ;
14. backtest ;
15. OOS ;
16. forward paper ;
17. module PnL proofs ;
18. Event Intelligence wiring classification ;
19. scoreboard ;
20. two-segment fresh-runner resume proof ;
21. final dual-repo receipt/closure report.

Toujours re-lire la spec avant de traiter cette liste comme exhaustive : elle reste l'autorité finale.

---

## 39. Règles anti-mensonge

Interdit de présenter comme preuve :

- synthetic data non marqué ;
- timestamp reconstruit sans provenance ;
- moyenne remplaçant une observation manquante ;
- mid-price comme fill ;
- train comme OOS ;
- OOS retuné comme untouched ;
- workflow success comme profit ;
- process alive comme data healthy ;
- module présent comme module wired ;
- SAFE comme PnL-ready ;
- vieux report comme état actuel ;
- fill count comme independent-N ;
- profit d'une famille comme compensation d'une autre ;
- résultat économique sans coûts ;
- conclusion “PROVEN” sans evidence correspondante.

---

## 40. Sources externes vérifiées à connaître

### GitHub Actions

Documentation officielle pertinente :

- GitHub-hosted runners : `https://docs.github.com/en/actions/reference/runners/github-hosted-runners`
- events : `https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows`
- trigger behavior / GITHUB_TOKEN : `https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow`

Points utiles :

- jobs GitHub-hosted sur instances fraîches ;
- persistance externe obligatoire entre segments ;
- limite standard de job documentée à 6h ;
- `workflow_dispatch` et `repository_dispatch` sont les déclenchements explicites à connaître pour les chaînes automatiques.

### Hyperliquid

Documentation officielle pertinente :

- API : `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers`
- Info endpoint : `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint`
- WebSocket : `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket`

Points utiles :

- `/info` = lecture d'informations ;
- `/exchange` = trading, donc non autorisé pour Alina ;
- time-range responses peuvent nécessiter pagination après 500 éléments/blocs ;
- reconnect WS et reconciliation sont des cas normaux à gérer.

---

## 41. Principe directeur

**Mesurer l'edge réel sans se mentir.**

Le but n'est pas :

- d'avoir le plus de fichiers ;
- d'avoir le plus de commits ;
- d'avoir une CI verte à tout prix ;
- de produire un backtest positif ;
- d'obtenir artificiellement +4 USD.

Le but est d'obtenir une chaîne reproductible :

`REAL DATA -> QUALITY -> CAUSAL REPLAY -> REALISTIC PAPER EXECUTION -> OOS -> FORWARD -> NET PNL PROOF -> SCOREBOARD`

avec :

- provenance ;
- coûts ;
- capacité ;
- idempotence ;
- fail-closed ;
- sécurité ;
- reprise cloud ;
- evidence durable.

Lorsque la donnée ne permet pas de prouver l'edge, le bon résultat est de le dire.

Lorsque l'edge n'existe pas après coûts, le bon résultat est de le tuer.

Lorsque l'edge est prouvé, la preuve doit être suffisamment précise pour être rejouée et auditée sans dépendre d'un PC utilisateur ni d'un souvenir de conversation.
