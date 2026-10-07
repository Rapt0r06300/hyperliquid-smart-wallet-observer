# Alina Smart Flow

**Moteur de recherche quantitative crypto strictement paper/read-only, conçu pour produire des preuves économiques reproductibles plutôt que de simples backtests positifs.**

Alina Smart Flow — nom historique : **HyperSmart** — collecte et normalise des données de marché réelles, reconstruit les conditions d'exécution, exécute replays/backtests/OOS/forward paper, mesure les coûts et la capacité, puis décide si un edge est réellement démontré.

> **Ligne rouge : aucune exécution réelle.**
>
> Aucun ordre mainnet. Aucun ordre testnet. Aucune clé privée. Aucune signature. Aucun dépôt, retrait ou transfert. Alina reste `PAPER / READ-ONLY / FAIL-CLOSED`.

---

## 1. Source de vérité

La spécification canonique actuelle est :

`docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

Elle est mise à jour **en place**. Les anciens labels `V6.x` présents dans l'historique sont des marqueurs de tranches de recherche ; ils ne constituent pas des specs concurrentes.

Ordre d'autorité pratique :

1. `SECURITY.md`
2. la **spec canonique**
3. le **HEAD courant** : code, tests, workflows, manifests et receipts réellement présents
4. `AGENTS.md`
5. `CLAUDE.md`
6. ce README et les autres documents ciblés

Un ancien rapport, une ancienne conversation ou un ancien `DONE` ne l'emporte jamais sur l'état réel du code et des preuves du HEAD courant.

---

## 2. Objectif économique

Alina ne cherche pas à maximiser un PnL brut. Elle cherche à démontrer un résultat **net, causal, exécutable et reproductible**.

Trois familles économiques seulement peuvent créer des effets paper canoniques :

| Famille | Statut | But |
|---|---|---|
| **Copy-Vault** | `ACTIVE` | Mesurer si les mouvements de leaders/vaults restent copiables après latence, coûts, capacité et exits. |
| **Lead-Lag** | `ACTIVE` | Mesurer des relations causales court-terme entre venues, notamment vers Hyperliquid. |
| **Cross-Venue Dislocation** | `ACTIVE` | Mesurer des écarts réellement exécutables entre venues après profondeur, frais, slippage et non-atomicité. |

Autres statuts encodés dans `src/hl_observer/strategies/active_scope.py` :

- `twap_metaorder`, `ofi_microprice`, `entity_consensus` : `SHADOW`
- `triangular_arbitrage`, `market_making` : `RESEARCH_ONLY`
- `funding_carry`, `external_github_profiles` : `DISABLED`

**Carry / Funding Carry reste `DISABLED_BY_SCOPE`.**

### Cible finale

La cible du projet est :

**>= +5.00 USD NET/jour PROUVÉS pour chacune des trois familles actives, séparément, sur 200 USD de capital paper.**

Aucune compensation n'est autorisée entre familles. Un Copy-Vault négatif ne peut pas être “sauvé” par un Lead-Lag positif.

Les conclusions honnêtes sont :

- `PROVEN`
- `PROMISING`
- `MORE_DATA`
- `UNMEASURABLE`
- `REJECTED`

La cible de +5 USD n'est jamais obtenue en abaissant artificiellement les frais, le slippage, la latence, l'impact, les exigences statistiques ou les gates de qualité.

---

## 3. Architecture générale

Alina fonctionne désormais en **repository unique**. Le code, le control plane, les campagnes,
les manifests, les receipts, les tests et les GitHub Actions vivent tous dans :

`Rapt0r06300/hyperliquid-smart-wallet-observer` — branche `main`.

~~~text
                 OPERATOR INTENT
        ChatGPT / Work / CLI / GitHub API
                         |
                         v
+------------------------------------------------+
| Alina Smart Flow — repository unique           |
|                                                |
| - phase / orchestration / campaign state       |
| - collectors / quality / replay-grade gates    |
| - replay / backtest / OOS / forward paper      |
| - PnL proof / scoreboard / receipts            |
| - manifests / indexes / durable checkpoints    |
| - GitHub Actions GitHub-hosted                  |
+------------------------------------------------+
                         |
                         v
             GITHUB-HOSTED WORKERS
                         |
                         v
        immutable heavy data in GitHub Releases
                         |
                         v
        COLLECT -> QUALITY -> REPLAY -> BACKTEST
                         |
                         v
       OOS -> FORWARD_PAPER -> PNL_PROOF
                         |
                         v
                    SCOREBOARD
~~~

Les gros shards de marché ne sont pas ajoutés à l'historique Git : ils sont publiés comme
**assets immuables de GitHub Releases du même repository**. Git `main` conserve les manifests,
hashes, index, états qualité, leases/checkpoints et receipts nécessaires pour les retrouver et
les valider de façon déterministe.

---

## 4. Repository unique et ancien Dataset V2

### Repository actif — code, data plane, orchestration et économie

`Rapt0r06300/hyperliquid-smart-wallet-observer`

Branche source de vérité : `main`.

Responsabilités :

- runtime Python actif sous `src/hl_observer/`;
- control plane `IDLE / COLLECT / ANALYZE`;
- collecte replay-grade, manifests, catalogues et quality receipts;
- GitHub Releases pour les shards lourds;
- replays et backtests;
- OOS / forward paper;
- Copy-Vault, Lead-Lag et Cross-Venue;
- PnL proof et scoreboard;
- tests et GitHub Actions;
- sécurité paper/read-only et interdiction d'exécution réelle.

Le package historique `hyper_smart_observer/` reste présent pour compatibilité/audit. **Il ne
doit pas devenir une architecture concurrente.**

### Ancien repository Dataset V2

`Rapt0r06300/alina-smartflow-datasets-v2` est **retiré de l'architecture active** et peut être
supprimé sans interrompre Alina. Aucun workflow ni chemin de données actif ne doit en dépendre.
Toute nouvelle collecte, publication de shards, replay, backtest, OOS/forward, preuve PnL ou
scoreboard part du repository Alina unique ci-dessus et de sa branche `main`.

---

## 5. Phase Orchestrator : IDLE / COLLECT / ANALYZE

L'architecture canonique remplace le mélange de campagnes continues par une autorité de phase explicite.

### `IDLE`

- ne crée aucun nouveau travail lourd ;
- laisse l'evidence durable intacte ;
- autorise les opérations de statut/lecture.

### `COLLECT`

- crée uniquement le travail de collecte autorisé ;
- lie le travail à un `phase_epoch` ;
- n'ouvre pas de nouveau replay/backtest/PnL proof.

### `ANALYZE`

- arrête la création de nouvelles collectes ;
- fige un `collection_cutoff` ;
- lie l'analyse au `source_collection_epoch` ;
- draine le travail déjà revendiqué ;
- déroule la chaîne d'analyse.

Pipeline canonique :

`DRAIN -> QUALITY -> REPLAY -> BACKTEST -> OOS -> FORWARD_PAPER -> PNL_PROOF -> SCOREBOARD -> DONE`

### Fondation déjà présente dans le HEAD

`src/hl_observer/control_plane/` contient notamment :

- `phase_state.py`
- `phase_controller.py`
- `phase_cli.py`
- `resumable_campaign.py`
- `dispatch_receipt.py`
- `campaign_adapters.py`
- `module_pnl_proof.py`
- `typed_events.py`

Le campaign schema v2 ajoute les identités de phase/epoch, les checkpoints et les preuves de terminaison nécessaires à l'orchestration durable.

**Important :** la présence de ces fondations ne signifie pas que tous les `OPEN-*`, `WKR-*` et contrats de fermeture de la spec sont déjà terminés. La spec canonique reste l'autorité sur le travail restant.

---

## 6. Cloud-first, GitHub-hosted only

Toute automatisation cloud canonique doit fonctionner sans le PC de l'utilisateur.

### Autorisé

- ChatGPT Work en Cloud
- GitHub API
- GitHub Actions avec runners GitHub-hosted
- `workflow_dispatch`
- `repository_dispatch`
- checkpoints/manifests/receipts persistés dans les repos ou releases autorisés

### Interdit

- `runs-on: self-hosted`
- réveiller le PC utilisateur
- utiliser le PC comme runner
- SSH/tunnel vers le PC
- dépendre d'un fichier ou processus local utilisateur
- exiger que le PC reste allumé
- créer un nouveau service local pour soutenir une automatisation GitHub

Les runners GitHub-hosted standard utilisent des environnements frais pour les jobs. La conception Alina ne suppose donc jamais qu'un fichier local au runner survivra au job suivant : l'état nécessaire doit être persisté durablement.

Les schedules sont traités comme des **watchdogs**, pas comme une horloge exacte. L'absence ou le retard d'une invocation doit changer la latence, pas la correction du résultat.

### Workflows historiques self-hosted

Le dépôt contient encore quelques anciens noms de workflows comportant `self-hosted`/PC. Les versions actuellement inspectées de ces anciens chemins sont **hard-disabled** par `if: false` et utilisent un runner hébergé dans leur job désactivé. Ils sont des artefacts historiques, pas une architecture à réactiver.

Toute nouvelle chaîne canonique doit rester GitHub-hosted.

Références externes vérifiées :

- GitHub-hosted runners : https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- événements `workflow_dispatch` / `repository_dispatch` : https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

---

## 7. Data plane : une donnée n'est utile que si elle est replay-grade

Un workflow vert ne prouve pas qu'une donnée est utilisable économiquement.

Selon la famille et la venue, Alina cherche à préserver ou dériver :

- exchange timestamp
- receive wall-clock timestamp
- monotonic receive timestamp
- clock offset
- RTT
- clock uncertainty
- BBO
- L2
- trades
- snapshot/delta semantics
- sequence IDs
- gaps
- out-of-order events
- duplicates
- native trade IDs
- fallback event identity lorsque nécessaire
- fee provenance
- tick size
- lot size
- minimum notional
- contract multiplier
- quote currency
- depth curves
- VWAP
- capacity
- quote age
- source health
- venue status
- immutable manifests
- checksums

**Missing != 0.**

**Unknown != healthy.**

**Process alive != source healthy.**

---

## 8. Venues et sources de marché

Le code actuel contient des chemins natifs ou dédiés pour :

| Venue | Exemples de surfaces présentes | Rôle |
|---|---|---|
| **Hyperliquid** | REST `/info`, WebSocket, clock evidence, pagination, rate weights | Source principale + Copy-Vault + destination fréquente Lead-Lag/Cross-Venue |
| **Binance** | clock sync, depth/L2, aggTrades, funding/context | Lead-Lag, Cross-Venue, référence marché |
| **Bybit** | native market-data adapter + venue adapter | Cross-Venue / couverture multi-venue |
| **OKX** | native market-data adapter + venue adapter | Cross-Venue / couverture multi-venue |
| **Gate** | market-data adapter + venue adapter | extension native multi-venue |
| **Bitget** | market-data adapter + venue adapter | extension native multi-venue |

La présence du code n'est **pas** une certification automatique de santé : la spec demande encore une matrice de capacité fondée sur l'evidence réellement collectée.

### Hyperliquid

Le runtime officiel utilise les surfaces publiques/read-only. L'API Hyperliquid distingue l'endpoint `/info` utilisé pour lire les données de l'endpoint `/exchange` utilisé pour agir/trader.

Alina n'active jamais ce second chemin.

Les endpoints temporels `/info` doivent être paginés correctement ; la documentation officielle indique qu'une requête de plage temporelle peut être bornée à 500 éléments/blocs distincts.

Références officielles :

- API : https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers
- Info endpoint : https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- WebSocket : https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket

### Archives officielles / fallback

Le système possède également des chemins de backfill historique, notamment pour **Binance USD-M** et **Bybit**, afin de compléter des périodes lorsque certaines surfaces live sont indisponibles depuis l'infrastructure GitHub.

Une archive historique ne reçoit jamais artificiellement un receive timestamp ou un monotonic timestamp qu'elle ne possède pas réellement. Elle reste `PARTIAL` tant qu'un chemin de qualification n'a pas démontré le niveau de preuve requis.

---

## 9. CCXT : discovery only

CCXT est volontairement isolé de l'installation runtime par défaut.

Dans `pyproject.toml`, il se trouve dans l'extra :

`discovery`

Raison : CCXT expose également des APIs d'ordre. Alina n'a besoin de lui que pour la **découverte de marchés/univers** lorsqu'aucun chemin natif n'est requis.

CCXT ne doit pas remplacer :

- les collecteurs natifs
- les horloges de venue
- les reconstructions L2
- les contrats d'exécution
- les preuves replay-grade

---

## 10. Dataset V2 : lifecycle et preuve

Cycle conceptuel Dataset V2 :

~~~text
incoming
   |
   v
quarantine
   | \
   |  \--> rejected
   v
 safe
   |
   +--> replay-compatible ?
   |
   +--> exact selected evidence for one experiment
   |
   +--> economic proof eligibility
~~~

`SAFE` n'est pas synonyme de `PROVEN`.

Une preuve PnL doit être attachée à une **sélection immuable précise** :

- exact shard IDs
- hashes
- time bounds
- schema/version
- dataset/index/catalog hashes
- replay compatibility
- cost evidence
- temporal split evidence

Une qualité globale du repository ne doit jamais remplacer les preuves spécifiques requises par une expérience.

---

## 11. Copy-Vault

Copy-Vault ne cherche pas les leaders au meilleur PnL brut. Il cherche les leaders **copiables par Alina**.

Le code actuel couvre de nombreux problèmes opérationnels, notamment :

- position lifecycle `OPEN / ADD / REDUCE / CLOSE`
- startup/rebootstrap
- state versioning
- exactly-once source fill handling
- reconnect overlap/backfill
- WS/REST disagreement quarantine
- stale open/add rejection
- partial close ratios
- leader state TTL
- per-vault queues
- source execution style
- maker/taker classification
- price-quality attribution
- visible-liquidity sizing
- capacity
- margin/leverage gates
- concentration ceilings
- exit/reduce-only invariants
- copyability erosion
- drift/reconciliation

La preuve finale doit encore démontrer que ces mécanismes produisent un résultat net causal et généralisable sur des données adéquates, avec OOS/forward post-freeze.

---

## 12. Lead-Lag

Lead-Lag vise des relations **causales court-terme**, pas une corrélation rétrospective.

L'architecture comporte notamment :

- Hyperliquid/Binance lead-lag research
- multi-asset tape/scoring
- clock certification
- BBO repricing
- L2/book confirmation
- queue-aware execution
- maker/taker timing experiments
- source alignment
- causal diagnostics/autopsy
- restart/recovery
- effective-independence controls
- measured replay
- shadow economics

La preuve valide doit respecter :

- ordre temporel causal
- horloges/uncertainty
- no-lookahead
- missed fills
- latency
- spread/slippage
- effective-N
- OOS
- forward post-freeze

---

## 13. Cross-Venue Dislocation

Cross-Venue ne juge pas un “spread” au mid-price comme un profit.

L'evidence doit pouvoir inclure :

- BBO simultanés/synchronisés
- L2 reconstructible
- profondeur des deux jambes
- VWAP au notionnel testé
- fees
- tick/lot/min-notional
- contract multiplier
- quote age
- capacity
- non-atomic execution risk
- adverse movement
- convergence/exit rules

Le dépôt contient des composants dédiés de capacity, quotes simultanées, roundtrip, state machine, quote skew, instruments mapping, certified backtests et paper execution.

Un spread observé qui disparaît après coûts est un résultat utile : il doit être rejeté, pas transformé en faux edge.

---

## 14. Event Intelligence — 120 idées

Le dépôt contient un sous-système `src/hl_observer/event_intelligence/` couvrant notamment :

- `ExternalEvent`
- provenance
- archivage
- sources directes
- WorldMonitor
- macro/event clocks
- regimes
- features
- corroboration
- prediction shifts
- price discovery
- market context
- module bridges
- validation/placebos
- outcomes
- scoreboard
- Dataset V2 integration

Le registre humain actuel couvre techniquement les **120 idées** :

`docs/event-intelligence-120-coverage.md`

Mais :

**implémentation technique != wiring live != edge économique prouvé.**

La spec canonique impose une classification machine de chaque idée, par exemple :

- `IMPLEMENTED_AND_WIRED`
- `IMPLEMENTED_BUT_PARTIAL`
- `IMPLEMENTED_BUT_NOT_WIRED`
- `BROKEN`
- `MISSING`
- `NOT_APPLICABLE`

`PROVEN_EDGE` reste une dimension séparée.

---

## 15. Market Truth et canonical paper execution

L'objectif d'Alina est que replay, backtest et forward parlent autant que possible le **même langage économique**.

Chaîne conceptuelle :

`Signal -> Gate -> PaperIntent -> Canonical Execution -> Fill -> Position -> Ledger -> Liquidatable Equity`

Prix et fills ne doivent pas reposer sur un simple mid-price lorsqu'une preuve d'exécution plus réaliste est requise.

Selon la stratégie, le moteur doit tenir compte de :

- BBO/L2 causal
- VWAP
- depth consumption
- partial fills
- missed fills
- latency
- queue model lorsque maker
- fees
- funding pertinent
- exits
- liquidation/capacity constraints

---

## 16. Replay, backtest, OOS et forward

Un résultat économique officiel ne doit pas utiliser une seule période optimisée de bout en bout.

Le pipeline doit distinguer explicitement :

- TRAIN / sélection
- validation lorsque prévue
- OOS
- post-freeze forward/paper
- final economic proof

Le freeze boundary doit être immuable.

Une OOS ou un forward observé puis utilisé pour retuner devient du feedback de recherche ; il ne peut plus être présenté comme une preuve untouched.

Alina contient aujourd'hui de nombreux modules spécialisés sous :

- `src/hl_observer/backtest/`
- `src/hl_observer/backtesting/`
- `src/hl_observer/replay/`
- `src/hl_observer/research/`
- `src/hl_observer/market_truth/`
- `src/hl_observer/simulation/`

---

## 17. Vérité du PnL

Un backtest brut positif ne vaut pas certification.

La preuve économique peut devoir intégrer :

- fees
- spread
- slippage
- latency
- partial fills
- missed fills
- liquidity
- depth
- capacity
- funding lorsqu'il est réellement applicable
- exits
- drawdown
- causal ordering
- no-lookahead
- cluster dependence
- effective sample size
- OOS
- forward post-freeze

Les métriques et le scoreboard doivent être rattachés à la période, aux données et au SHA exacts qui les ont produits.

---

## 18. État d'implémentation — lecture correcte

Ce tableau décrit l'état structurel actuel sans transformer un composant présent en faux “DONE global”.

| Surface | État |
|---|---|
| Scope économique des 3 familles | **Implémenté et autoritaire** |
| Sécurité paper/read-only | **Invariant canonique** |
| Control plane IDLE/COLLECT/ANALYZE | **Fondation implémentée dans le repo principal** |
| Campaign schema v2 / phase epoch | **Fondation implémentée** |
| Dispatch receipts / idempotency primitives | **Fondation implémentée** |
| Dataset V2 resumable manifests/leases/checkpoints | **Actif** |
| Data collection multi-venue | **Code natif présent sur les venues prioritaires** |
| Hyperliquid/Binance clock evidence | **Implémenté dans le code de collecte** |
| Replay data contracts | **Présents** |
| Event Intelligence 1..120 | **Couverture technique présente ; wiring économique à classifier** |
| Exact global unique trade closure | **Ne pas considérer fermé tant que la preuve de complétude n'est pas produite** |
| Whole-corpus SAFE -> replay-compatible closure | **Ne pas considérer fermé tant que le backlog n'est pas classifié** |
| Real two-segment fresh-runner resume proof | **Contrat final requis par la spec** |
| OOS + forward + final PnL proof des 3 familles | **Doit être certifié par evidence, pas supposé** |
| Ordres réels/testnet | **Interdits** |
| Self-hosted / PC cloud dependency | **Interdits** |

Pour connaître le statut exact d'un chantier : lire le HEAD, les manifests/receipts et les sections `OPEN-*` / `WKR-*` de la spec.

---

## 19. Installation développement

Python requis :

**Python >= 3.11**

Depuis la racine du repo :

~~~bash
python -m pip install -e ".[dev]"
python -m hl_observer doctor
python -m hl_observer safety-audit
python -m hl_observer --help
~~~

Le point d'entrée console installé est également :

~~~bash
hl-observer --help
~~~

### Discovery CCXT optionnelle

Seulement si la découverte univers est nécessaire :

~~~bash
python -m pip install -e ".[discovery]"
python -m hl_observer discover-ccxt-universe
~~~

Cette commande sert à la découverte de marchés, pas au hot path d'exécution.

---

## 20. Commandes utiles

### Sécurité

~~~bash
python -m hl_observer doctor
python -m hl_observer safety-audit
python -m hl_observer audit-safety
~~~

### Collecte / marché

~~~bash
python -m hl_observer collect-once --help
python -m hl_observer discover-markets --help
python -m hl_observer scan-markets --help
python -m hl_observer live-user-fills-stream --help
~~~

### Replay / validation / recherche

~~~bash
python -m hl_observer replay-quality --help
python -m hl_observer realtime-replay --help
python -m hl_observer closed-ledger-replay --help
python -m hl_observer walk-forward-profit-validation --help
python -m hl_observer out-of-sample-report --help
~~~

### Diagnostics économiques

~~~bash
python -m hl_observer profitability-diagnostics --help
python -m hl_observer cost-drag-diagnostics --help
python -m hl_observer loss-attribution --help
python -m hl_observer ledger-pnl-calibration --help
~~~

### Control plane — fondation actuelle

~~~bash
python -m hl_observer.control_plane.phase_cli --help
python -m hl_observer.control_plane.phase_cli status
~~~

Cette surface est une **fondation de contrôle**. Le statut cloud final doit refléter l'autorité durable du repository Alina unique, ses manifests/receipts Dataset V2-format et la spec canonique, pas une approximation locale.

---

## 20.1 Reprise complète sur un nouveau PC

Un simple `git clone` récupère l'historique Git, mais Git ne télécharge pas les assets des GitHub Releases. Pour récupérer aussi les trades, L2, preuves de replay/backtest/OOS/forward, scoreboards et snapshots locaux publiés :

~~~text
Windows : RESTORE_ALINA.cmd
Linux/macOS : ./RESTORE_ALINA.sh
~~~

Ces lanceurs exécutent `tools/restore_alina.py --everything`, téléchargent les Releases du repository canonique, vérifient les identités SHA-256 et reconstruisent le dernier snapshot local explicite.

Avant d'abandonner l'ancien PC, les données importantes encore uniquement locales et ignorées par Git peuvent être envoyées une fois vers les Releases avec :

~~~text
BACKUP_LOCAL_ALINA.cmd
~~~

Cette sauvegarde locale est chunkée, reprenable après interruption et couvre aussi les fichiers ignorés utiles hors `data/logs/reports/runtime` (par exemple DB/logs/audits locaux). Elle exclut les secrets/clés ainsi que les caches, environnements et builds reproductibles. Le cloud Alina ne dépend jamais de cette machine : cette commande sert uniquement à sauver des données historiques qui n'existent pas encore sur GitHub.

Voir `docs/DISASTER_RECOVERY.md`.

---

## 21. Tests et CI

Suite locale :

~~~bash
python -m pytest -q
~~~

Lint :

~~~bash
ruff check .
~~~

Le workflow principal `.github/workflows/ci.yml` utilise actuellement des runners GitHub-hosted et contient notamment :

- gate sécurité/imports
- tests Linux shardés
- tests Windows critiques
- replay/runtime parity
- contrôles de portabilité et de wiring

Les actions sont épinglées par SHA dans la CI inspectée.

Pour une mission agent explicitement configurée en **“implémentation totale puis validation finale”**, les tests peuvent être écrits pendant la phase d'implémentation et exécutés ensemble à la fin. Cela ne supprime pas les gates : cela change uniquement leur ordre d'exécution pour économiser quota et temps.

---

## 22. Structure du repository

~~~text
src/hl_observer/
├── control_plane/       # phases, campaigns, receipts, typed control events
├── collection/          # collectors, clocks, books, market data
├── hyperliquid/         # read-only HL REST/WS contracts
├── data_sources/        # acquisition/backfill/provider infrastructure
├── datasets/            # replay workspace / Dataset V2 bridge contracts
├── market_truth/        # executable market truth / replay
├── copy_vault/          # robust Copy-Vault semantics
├── copying/             # leader/copy support
├── arbitrage/           # Cross-Venue components
├── backtest/            # replay/backtest primitives
├── backtesting/         # family-specific research/backtests
├── replay/              # replay data quality
├── paper_trading/       # canonical paper mechanics
├── simulation/          # economics, scoreboard, measured simulation
├── research/            # frozen/causal research surfaces
├── event_intelligence/  # external events / 120-idea system
├── risk/                # risk gates
├── security/            # no-real-trade controls
└── ops/                 # operational deterministic tooling
~~~

Legacy :

`hyper_smart_observer/`

Ne pas étendre comme nouvelle architecture.

---

## 23. Instructions pour agents de code

Documents obligatoires :

- `AGENTS.md`
- `CLAUDE.md`
- `SECURITY.md`
- spec canonique

Principes :

- **un seul agent principal** par défaut
- pas de swarm/subagents sauf demande explicite
- minimum de quota modèle
- calcul déterministe dès que possible
- ne pas relire les gros documents inutilement
- réutiliser les composants existants
- éviter toute architecture en double
- un commit n'est pas une condition d'arrêt
- deux échecs identiques => changer de méthode
- ne jamais prétendre qu'un travail est sauvegardé sans vrai diff/commit
- ne jamais déclarer `DONE` sur simple présence d'un fichier

Le runbook détaillé pour agents de code se trouve directement dans la spec canonique.

---

## 24. Invariants anti-mensonge

Alina refuse les raccourcis suivants :

- donnée synthétique présentée comme vraie
- timestamp fabriqué
- zéro utilisé à la place d'une donnée inconnue
- mid-price présenté comme fill exécutable
- PnL brut présenté comme net
- train présenté comme OOS
- OOS réutilisé pour retuning puis encore appelé untouched
- nombre de fills présenté comme nombre d'observations indépendantes
- workflow “success” présenté comme preuve économique
- module présent présenté comme module câblé
- SAFE global présenté comme autorisation PnL
- profit d'une famille utilisé pour masquer l'échec d'une autre
- suppression/skip/xfail d'un test pour obtenir du vert
- baisse d'une gate pour fabriquer un résultat positif

---

## 25. Ce qu'Alina n'est pas

Alina n'est pas :

- un bot de trading live
- un exécuteur testnet
- un wallet
- un système de copy-trading réel
- une promesse de rendement
- un moteur qui suppose qu'un backtest positif continuera dans le futur

C'est un **système de recherche, de collecte, de simulation paper et de preuve économique**.

---

## 26. Documents clés

| Document | Fonction |
|---|---|
| `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md` | Spec canonique + backlog + runbook + closure matrix |
| `SECURITY.md` | Invariants de sécurité |
| `AGENTS.md` | Routeur compact pour agents |
| `CLAUDE.md` | Instructions de compatibilité agents |
| `docs/event-intelligence-120-coverage.md` | Registre technique Event Intelligence |
| `src/hl_observer/strategies/active_scope.py` | Autorité code du scope économique |
| `src/hl_observer/control_plane/` | Fondation phase/campaign control plane |
| Dataset V2 | Durable data/campaign evidence |

---

## Principe directeur

> **Mesurer l'edge réel sans se mentir.**

La réussite d'Alina ne sera pas “le logiciel tourne”.

Elle sera atteinte lorsque les trois familles actives disposeront chacune d'une preuve indépendante, causale, reproductible, après coûts réels, avec données fiables, capacité, replays rigoureux, OOS/forward post-freeze et fermeture fail-closed — ou lorsqu'Alina aura démontré honnêtement qu'une famille doit rester `MORE_DATA`, `UNMEASURABLE` ou `KILL`.
