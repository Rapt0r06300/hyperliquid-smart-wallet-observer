# AGENTS.md — Alina Smart Flow

Dernière mise à jour : **2026-09-27**.

Contrat d'exécution pour agents de code. Objectif : reprendre et finir Alina correctement avec **un seul agent principal**, **quota modèle minimal**, **aucun PC utilisateur**, aucune architecture parallèle et aucun faux `DONE`.

## 1. Autorité

Ordre de priorité :
1. `SECURITY.md`
2. `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`
3. code + tests + workflows + manifests + receipts du **HEAD courant**
4. `AGENTS.md`
5. `CLAUDE.md`
6. `README.md`
7. documentation ciblée utile au bloc courant

La spec canonique est **unique** et se met à jour en place. Ne pas créer de nouvelle spec `V6.x`, `final`, `vNext`, `bis` ou équivalente. Un ancien rapport, prompt, roadmap ou `DONE` ne peut pas contredire le HEAD, les receipts ou la spec actuelle.

## 2. Repositories

### Principal
`Rapt0r06300/hyperliquid-smart-wallet-observer` — branche finale `main`.

Runtime actif : `src/hl_observer/`.

Responsabilités : orchestration, stratégies, market truth, replay/backtest, OOS/forward, paper execution, PnL, scoreboard, sécurité, operator surface et contrats cross-repo.

### Dataset V2
`Rapt0r06300/alina-smartflow-datasets-v2` — `main`.

Responsabilités : état durable des campagnes cloud lourdes, manifests, leases, checkpoints, catalogue, qualité, gros shards et receipts/evidence Dataset V2.

### Ownership
Un même état mutable n'a qu'une seule autorité. Ne jamais créer un second progress store, checkpoint store, campaign ledger ou manifest mutable concurrent. Le repo principal conserve l'intention/référence ; Dataset V2 conserve l'état durable des campagnes de données lourdes.

## 3. Runtime et architecture

`src/hl_observer/` est le runtime canonique.

`hyper_smart_observer/` est legacy/compatibilité/audit. Ne pas y développer une nouvelle architecture.

Réutiliser avant de créer. Ne pas dupliquer :
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
- Event Intelligence pipeline.

Préférer de petits modules importables sous `src/hl_observer/` et du wiring mince.

## 4. Scope économique

Familles capables de matérialiser du paper PnL canonique :
- `copy_vault`
- `lead_lag`
- `cross_venue_dislocation`

Autorité code : `src/hl_observer/strategies/active_scope.py`.

`funding_carry = DISABLED_BY_SCOPE`.

Objectif final : **>= +4.00 USD NET/jour PROUVÉS par famille séparément**, sans compensation inter-familles.

Statuts honnêtes :
- `PROVEN`
- `MORE_DATA`
- `UNMEASURABLE`
- `KILL`

Ne jamais assouplir artificiellement frais, slippage, latence, qualité ou seuils statistiques pour fabriquer `PROVEN`.

## 5. Sécurité absolue

Alina est **PAPER / READ-ONLY / FAIL-CLOSED**.

Interdit :
- ordre réel ou testnet ;
- activation d'un chemin mainnet/testnet d'exécution ;
- `/exchange` opérationnel ;
- private key, seed, mnemonic ;
- signature ;
- dépôt/retrait/transfert ;
- SDK tiers utilisé pour ordonner ;
- secret permettant de signer un ordre.

Doctrine runtime compatible avec :
- `HL_ENABLE_MAINNET_EXECUTION=0`
- `HL_ENABLE_TESTNET_EXECUTION=0`

Si une donnée requise est absente, stale, contradictoire, partielle, ambiguë ou non causale : refuser ou classer `UNKNOWN/PARTIAL/UNMEASURABLE`. Ne jamais inventer un zéro, un timestamp ou une valeur par défaut.

**Missing != 0. Unknown != healthy.**

## 6. Aucun PC utilisateur dans Work/GitHub

Pour ChatGPT Work, GitHub Actions et automatisations cloud :
- GitHub-hosted uniquement ;
- aucun self-hosted runner ;
- ne jamais réveiller/utiliser/dépendre du PC utilisateur ;
- aucun SSH/tunnel/service/processus/fichier local utilisateur requis ;
- aucun chemin Windows utilisateur requis.

Un agent local est acceptable uniquement si l'utilisateur le lance explicitement. Une mission Work Cloud ne doit jamais y basculer.

Les anciens workflows dont le nom ou le contenu mentionne self-hosted/PC sont des artefacts historiques. Les versions inspectées à cette date sont hard-disabled. **Ne jamais les réactiver ni réintroduire `runs-on: self-hosted`.**

## 7. Contraintes GitHub Actions utiles

Documentation officielle vérifiée :
- chaque job GitHub-hosted standard utilise une instance fraîche ;
- un fichier local au runner ne doit jamais être considéré comme durable ;
- état inter-segments => Git/Dataset V2/artifact/release/receipt autorisé ;
- durée maximale documentée d'un job GitHub-hosted standard : **6 heures** ;
- campagne longue => segments bornés + checkpoints + reprise idempotente.

Pour les chaînes automatiques, préférer `workflow_dispatch` ou `repository_dispatch` quand un déclenchement explicite est requis. Ne pas supposer qu'un `push` produit par un workflow via son `GITHUB_TOKEN` déclenchera récursivement les autres workflows ; GitHub documente les deux dispatch comme exceptions explicites.

Les `schedule` sont des **watchdogs**, pas une horloge exacte. Un run retardé ou sauté ne doit jamais casser identity/lease/checkpoint/phase.

## 8. Contrat de mission

Quand l'utilisateur demande d'implémenter, corriger, améliorer, continuer ou finir :
- considérer la demande comme une mission complète ;
- établir mentalement objectif, contraintes, surfaces, preuves et Definition of Done ;
- poursuivre tant qu'il reste du travail demandé et réalisable ;
- ne pas s'arrêter après un plan, une recherche, un fichier, un test, un commit ou une PR ;
- ne pas redemander l'autorisation pour poursuivre une mission déjà autorisée.

Après **deux échecs identiques**, changer de méthode ; ne jamais boucler.

Si un vrai blocage de plateforme/service/outillage persiste :
1. finir tout le travail indépendant ;
2. vérifier ce qui est réellement terminé ;
3. laisser un checkpoint exact : HEAD, fichiers, preuves, blocage, travail restant, prochaine action.

Ne jamais prétendre travailler en arrière-plan sans mécanisme réel.

## 9. Préflight avant modification importante

Toujours :
1. lire le HEAD courant de `main` ;
2. vérifier le fichier/branche ciblés ;
3. lire `SECURITY.md` ;
4. lire `AGENTS.md` ;
5. consulter la spec canonique pour le bloc ouvert ;
6. lire les callers et tests du bloc ;
7. lire workflows/manifests/receipts si cloud/data.

Ne jamais travailler depuis un vieux SHA mémorisé sans relire le HEAD.

## 10. Spec et quota minimal

La spec est énorme. Bonne méthode :
1. lecture globale unique au début d'une grosse mission ;
2. construire un petit backlog interne depuis `OPEN-*`, `WKR-*`, runbook et closure matrix ;
3. travailler par sections ciblées ;
4. ne relire ensuite que les sections nécessaires.

Ne pas rescanner l'historique Git, les archives et les gros logs sauf besoin précis.

Utiliser le modèle uniquement pour les décisions qui exigent du raisonnement. Pour le reste privilégier :
- `git`
- `rg/grep`
- parsers/scripts Python
- JSON/jq
- hashes/checksums
- calculs déterministes
- replays/backtests
- tests/lint/static analysis
- GitHub API/Actions ciblés

Par défaut : **un seul agent principal**, pas de swarm/subagents/multi-agent.

## 11. Mode “implémentation totale puis tests finaux”

Si l'utilisateur demande explicitement **implémenter toute la spec d'abord puis tester ensemble à la fin** :
- coder, câbler, migrer et adapter tests/workflows/manifests ;
- sauvegarder de vrais diffs ;
- poursuivre immédiatement au bloc suivant ;
- ne pas lancer full pytest, grosse CI, replay/backtest/OOS/forward long entre chaque modification.

Un test ciblé très court reste permis seulement s'il est nécessaire pour comprendre une API/signature/import.

Après épuisement du backlog d'implémentation :
1. lint/static ;
2. sécurité ;
3. tests critiques ;
4. suite globale pertinente ;
5. workflows cloud ;
6. replay/backtest ;
7. OOS ;
8. forward paper ;
9. PnL proof ;
10. scoreboard ;
11. receipts ;
12. closure matrix.

Ce mode change l'ordre, jamais les exigences finales.

## 12. Control plane

Fondation réelle : `src/hl_observer/control_plane/`, dont :
- `phase_state.py`
- `phase_controller.py`
- `phase_cli.py`
- `resumable_campaign.py`
- `dispatch_receipt.py`
- `campaign_adapters.py`
- `module_pnl_proof.py`
- `typed_events.py`

Phases :
- `IDLE`
- `COLLECT`
- `ANALYZE`

### IDLE
Aucun nouveau travail lourd ; lecture/statut possibles.

### COLLECT
Collecte uniquement ; travail lié à `phase_epoch` ; pas de nouveau replay/backtest/PnL proof.

### ANALYZE
Stop création de collecte, fixer `collection_cutoff`, lier `source_collection_epoch`, drainer le déjà-claim puis :

`DRAIN -> QUALITY -> REPLAY -> BACKTEST -> OOS -> FORWARD_PAPER -> PNL_PROOF -> SCOREBOARD -> DONE`

La présence d'un module ne ferme pas automatiquement un `OPEN-*` ou `WKR-*`.

## 13. Campaign schema v2

Les nouvelles campagnes canoniques doivent être traçables, resumables, idempotentes et rattachées à phase/SHA/dataset selection.

Identités attendues selon la spec :
- `campaign_id`
- `campaign_kind`
- `code_sha`
- config/work-plan hashes
- dataset generation
- creation phase
- `phase_epoch`
- `source_collection_epoch`
- collection cutoff
- dataset selection id
- lease
- checkpoint lineage
- terminal evidence digest

Les manifests v1 historiques restent read-only ; ne pas réécrire l'histoire pour leur donner artificiellement un schema v2.

## 14. Dispatch cross-repo

Pattern canonique :

`operator intent -> idempotent dispatch -> Dataset V2 campaign -> worker -> durable receipt -> main status`

Le dispatch doit être explicite, idempotent, hashé/déterministe et lié au SHA, à la phase et à l'epoch.

Ne pas utiliser un simple push de données comme unique mécanisme implicite de réveil cross-repo.

Déclenchement explicite : `workflow_dispatch` ou `repository_dispatch`, avec permissions minimales.

## 15. Resume long GitHub-hosted

Chaque segment doit pouvoir :
- lire son manifest ;
- acquérir/renouveler un lease ;
- reprendre le dernier checkpoint ;
- traiter une portion bornée ;
- écrire un checkpoint atomique ;
- publier l'evidence ;
- libérer/expirer proprement le lease ;
- être rejoué sans duplication logique.

Avant d'annoncer le resume cloud “prouvé”, exiger un vrai scénario :

`fresh runner #1 -> durable checkpoint -> fresh runner #2 -> continuation correcte`

Une reprise sur le même process/disque n'est pas la preuve requise.

## 16. Données replay-grade

Selon le chemin, préserver ou prouver :
- exchange timestamp
- receive wall-clock timestamp
- receive monotonic timestamp
- clock offset / RTT / uncertainty
- BBO / L2 / trades
- snapshot/delta semantics
- sequence / gaps / out-of-order / duplicates
- native trade ID ou fallback stable identity
- fee provenance
- tick/lot/min-notional/multiplier
- quote currency
- depth / VWAP / capacity / quote age
- venue/source health
- manifests / hashes / checksums

Une archive exchange-time-only ne devient jamais live-quality par simple normalisation.

## 17. Venues prioritaires

Conserver/vérifier selon la spec :
- Hyperliquid
- Binance
- Bybit
- OKX
- Gate
- Bitget

Le code contient des chemins dédiés pour ces surfaces, mais distinguer strictement :
`FILE_PRESENT != IMPORT_OK != COLLECTOR_ACTIVE != SOURCE_HEALTHY != REPLAY_COMPATIBLE != PNL_READY`.

## 18. Hyperliquid

Runtime officiel : surfaces publiques/read-only.

La documentation distingue :
- `/info` : lecture d'informations ;
- `/exchange` : trading.

`/exchange` ne doit jamais devenir atteignable.

### Pagination
Les réponses time-range de `/info` peuvent être limitées à **500 éléments/blocs distincts**. Paginer depuis le dernier timestamp, détecter stagnation/boucles et prouver la complétude. Un seul appel ne prouve jamais une grande plage complète.

### WebSocket
Gérer disconnect/reconnect/resubscribe comme cas normal. Réconcilier le snapshot, utiliser `isSnapshot` lorsque fourni, dédupliquer et backfiller le gap via `/info` si nécessaire. Reconnect sans reconciliation != collecte fiable.

## 19. CCXT

CCXT reste **discovery-only**. Dans le packaging actuel il est isolé dans l'extra `discovery`.

Rôle autorisé : découverte de venues/markets/intersections/candidats.

Interdit :
- remplacer les collecteurs natifs prioritaires ;
- utiliser ses APIs d'ordre ;
- traiter une découverte CCXT comme preuve replay/PnL.

## 20. Dataset V2

Cycle conceptuel :

`incoming -> quarantine -> safe -> replay-compatible -> selected evidence -> economic proof eligibility`

avec `rejected` si la qualité échoue.

Règles :
- `SAFE != replay-compatible`
- `replay-compatible != economically proven`
- santé globale du repo != preuve de l'expérience sélectionnée.

Une preuve doit référencer exactement shards, hashes, bornes temporelles, schema/version, dataset generation, catalog/index hashes, qualité, coûts et split evidence.

## 21. Exact counts

Si la spec exige `trade_count_exact` ou `unique_trade_count_exact`, exiger :
- couverture complète des shards sélectionnés ;
- identité stable ;
- déduplication déterministe ;
- aucun shard `unknown` ;
- preuve machine-readable.

Un total partiel extrapolé n'est pas exact.

## 22. Copy-Vault

Mesurer **copiabilité**, pas seulement rentabilité historique du leader.

Selon le bloc, préserver :
- fills complets ;
- lifecycle `OPEN/ADD/REDUCE/CLOSE` ;
- startup/rebootstrap ;
- reconnect overlap ;
- exactly-once source fill ;
- state versioning/TTL ;
- queue/backlog ;
- source execution style et maker/taker ;
- leader price quality ;
- target exposure ;
- partial closes / reduce-only / exit semantics ;
- visible liquidity / capacity ;
- margin/leverage/concentration ;
- slippage / latency ;
- copyability erosion ;
- drift/reconciliation.

Le PnL à certifier est celui **d'Alina**, pas celui du leader.

## 23. Lead-Lag

Une corrélation rétrospective n'est pas un edge causal.

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
- latency / spread / slippage / fees ;
- dependence clustering / effective-N ;
- regime stability ;
- OOS ;
- forward post-freeze.

## 24. Cross-Venue Dislocation

Ne jamais certifier un spread au mid.

Exiger selon le chemin :
- deux jambes causalement observées ;
- BBO suffisamment synchronisés ;
- L2 reconstructible si requis ;
- profondeur/VWAP deux jambes ;
- fees/slippage/latency ;
- quote age ;
- tick/lot/min-notional/multiplier ;
- capacity ;
- non-atomic execution risk ;
- adverse movement ;
- convergence/exit ;
- funding seulement si économiquement pertinent.

Si les coûts dépassent l'écart, **rejeter** est le bon résultat.

## 25. Event Intelligence — 120 idées

Sous-système : `src/hl_observer/event_intelligence/`.

Registre : `docs/event-intelligence-120-coverage.md`.

“Implémenté” dans le registre ne prouve ni wiring, ni collecte live, ni OOS, ni forward, ni edge.

Classification machine attendue selon la spec :
- `IMPLEMENTED_AND_WIRED`
- `IMPLEMENTED_BUT_PARTIAL`
- `IMPLEMENTED_BUT_NOT_WIRED`
- `BROKEN`
- `MISSING`
- `NOT_APPLICABLE`

`PROVEN_EDGE` est une dimension séparée.

## 26. Market Truth / fills

Chaîne cible :

`Signal -> Gate -> PaperIntent -> Canonical Execution -> Fill -> Position -> Ledger -> Liquidatable Equity`

Quand l'exécution réaliste est requise :
- pas de mid comme fill ;
- depth consumption ;
- partial/missed fills ;
- latency ;
- fees/slippage ;
- tick/lot/min-notional ;
- queue model si maker ;
- provenance du modèle de coûts.

Replay et forward doivent parler le même langage économique autant que possible.

## 27. PnL canonique

Un PnL brut n'est pas une preuve.

Selon la famille intégrer :
- fees
- spread
- slippage
- latency
- partial/missed fills
- liquidity/depth/capacity
- funding pertinent
- exits
- liquidation/risk constraints
- drawdown
- causalité/no-lookahead
- dependence/effective-N
- OOS
- forward post-freeze

Scoreboard lié au SHA, dataset selection, phase/epoch, période, config hash et freeze boundary.

## 28. TRAIN / validation / OOS / forward

Ne jamais mélanger :
- TRAIN = recherche/tuning/sélection
- validation = filtre pré-freeze si prévu
- OOS = untouched pour le choix final
- forward paper = post-freeze

Si un segment OOS/forward est observé puis utilisé pour retuner, il devient feedback de recherche et n'est plus untouched.

Le freeze doit identifier config/hash, SHA, dataset selection, cutoff et segments post-freeze.

## 29. Tests et CI

Ne jamais :
- supprimer un test pour faire vert ;
- affaiblir un test strict en smoke ;
- ajouter skip/xfail sans justification normative ;
- masquer une exception ;
- rendre une gate permissive pour fabriquer un résultat positif.

Protéger au minimum : safety, invariants, idempotency, causality, no-lookahead, schemas, replay parity, data quality, PnL accounting et cross-repo contracts.

Workflow CI principal actuel : `.github/workflows/ci.yml`, GitHub-hosted. Étendre l'existant avant de créer une CI concurrente.

## 30. Git discipline

`main` est l'état final canonique.

Avant modification : HEAD + fichiers ciblés + préservation du travail existant.

Éviter `reset --hard`, clean destructeur, rebase destructif et branches parallèles inutiles.

Si l'outil permet l'écriture directe sur `main`, modifier le minimum nécessaire. Si la plateforme impose une PR, utiliser une branche courte ciblant `main`.

Avant d'annoncer “sauvegardé/terminé” :
- lire le HEAD final ;
- vérifier le commit ;
- vérifier les fichiers modifiés ;
- vérifier le diff réel ;
- vérifier qu'il n'est pas vide.

Un commit n'est pas une condition d'arrêt.

## 31. Documentation

Ne pas créer de documents “final/vNext” concurrents.

Si une règle change :
- normative => spec canonique ;
- comportement agent => `AGENTS.md` ;
- architecture/présentation => `README.md` ;
- compatibilité agent => `CLAUDE.md`.

## 32. Ce qui n'est PAS un DONE

Ne suffit pas :
- fichier/classe créé ;
- import vert ;
- test unitaire vert ;
- workflow vert ;
- commit ;
- campagne créée/claimed ;
- process alive ;
- SAFE ;
- replay smoke ;
- backtest positif ;
- PnL brut positif ;
- screenshot/rapport ;
- mention “implémenté”.

Une feature est DONE seulement si elle est réellement codée, câblée, appelée, persistée si nécessaire et validée au niveau exigé par la spec.

## 33. Definition of Done globale

La mission globale est DONE uniquement si la closure matrix canonique est satisfaite.

Elle doit notamment fermer ou qualifier honnêtement :
- cohérence repo principal / Dataset V2 ;
- phase authority ;
- campaign schema v2 ;
- dispatch idempotent ;
- absence de split-brain ;
- resume cloud réel ;
- dataset selection immuable ;
- exact counts si requis ;
- replay compatibility ;
- source evidence ;
- OOS ;
- forward paper ;
- PnL proof ;
- scoreboard ;
- Event Intelligence wiring ;
- paper/read-only ;
- `self_hosted_used = false` ;
- `real_execution_reachable = false`.

## 34. Final receipt

À la fermeture globale, produire/vérifier si applicable :
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

Inconnu reste inconnu ; jamais de faux zéro.

## 35. Ordre recommandé de fermeture

Quand les blocs sont encore ouverts, sans recréer ce qui existe :
1. phase authority ;
2. campaign schema v2 ;
3. split-brain prevention ;
4. cross-repo dispatch/receipts ;
5. operator surface ;
6. GitHub-hosted firewall ;
7. durable resume/checkpoints ;
8. exact/global unique counts ;
9. SAFE -> replay-compatible ;
10. source capability/evidence ;
11. quality gates ;
12. replay ;
13. backtest ;
14. OOS ;
15. forward paper ;
16. module PnL proofs ;
17. Event Intelligence wiring classification ;
18. scoreboard ;
19. two-segment fresh-runner proof ;
20. final dual-repo receipt.

Toujours reconsulter la spec : elle reste exhaustive.

## 36. Règles anti-mensonge

Ne jamais présenter comme preuve :
- donnée synthétique non marquée ;
- timestamp fabriqué ;
- zéro remplaçant l'inconnu ;
- mid comme fill exécutable ;
- train comme OOS ;
- OOS retuné comme untouched ;
- workflow success comme profit ;
- process alive comme source healthy ;
- module présent comme wired ;
- SAFE comme PnL-ready ;
- vieux rapport comme état actuel ;
- fill count comme independent-N ;
- profit d'une famille pour masquer une autre ;
- résultat économique sans coûts.

## 37. Références externes vérifiées

GitHub :
- `https://docs.github.com/en/actions/reference/runners/github-hosted-runners`
- `https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows`
- `https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow`

Hyperliquid :
- `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket`

## 38. Principe directeur

**Mesurer l'edge réel sans se mentir.**

Chaîne cible :

`REAL DATA -> QUALITY -> CAUSAL REPLAY -> REALISTIC PAPER EXECUTION -> OOS -> FORWARD -> NET PNL PROOF -> SCOREBOARD`

avec provenance, coûts, capacité, idempotence, fail-closed, reprise cloud et evidence durable.

Si la donnée ne suffit pas : `MORE_DATA/UNMEASURABLE`.

Si l'edge disparaît après coûts : `KILL`.

Si l'edge est réellement prouvé : la preuve doit pouvoir être rejouée et auditée sans dépendre du PC utilisateur ni d'un souvenir de conversation.
