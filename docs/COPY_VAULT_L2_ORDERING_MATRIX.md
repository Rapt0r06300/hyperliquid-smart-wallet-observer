# Matrice d’ordre et de resynchronisation L2 Copy‑Vault

État vérifié sur le runtime local au 29 octobre 2026. Ce document décrit les
contrats effectivement appliqués par les adaptateurs présents et la frontière
d’admission économique; il ne certifie ni la complétude de la collecte ni la
rentabilité.

## Admission dans le replay économique Copy‑Vault

Le chargeur de carnets Copy‑Vault n’admet actuellement que les sources
Hyperliquid `HYPERLIQUID_L2_WS` et
`HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT`, sous réserve des contrôles de
provenance, SAFE, horodatage, intégrité, identité et checkpoint de la chaîne
canonique. Les adaptateurs d’autres plateformes ci-dessous sont des surfaces
de collecte/normalisation; leur présence ne les rend pas admissibles au PnL
Copy‑Vault. Le catalogue SAFE et le chargeur doivent être étendus et prouvés
avant qu’une autre source puisse entrer dans ce replay.

Un compteur local, un numéro de connexion ou l’ordre d’arrivée ne remplace
jamais une séquence native. Si une plateforme ne publie pas de lien entre deux
états, la continuité correspondante reste non prouvée.

## Contrats par flux

| Plateforme et flux | Ordre/temps natifs | Reset, doublon et trou | Resynchronisation appliquée | Admis au PnL Copy‑Vault |
|---|---|---|---|---|
| Hyperliquid WebSocket `l2Book` / `WsBook` | `coin`, `levels`, `time`; aucun `seq`/`prev_seq` documenté | Les messages ne prouvent pas la continuité entre deux observations. Une rupture de collecte ne peut être comblée par un compteur local. | Chaque carnet complet validé est une observation autonome. Après reconnexion, attendre un nouvel état complet; ne pas reconstruire des deltas ni relier artificiellement les snapshots. | Oui, si shard SAFE et toutes les preuves causales requises passent. |
| Hyperliquid `/info` `l2Book` matérialisé en checkpoint causal | `coin`, `levels`, `time` et identifiants/provenance du checkpoint | Pas de séquence native de continuité entre checkpoints. Un checkpoint absent ou incomplet reste une lacune. | Traiter chaque checkpoint validé comme une ancre ponctuelle; exiger l’identité, l’époque, le hash, le cutoff et la provenance attendus. | Oui, seulement via `HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT` et les validations du chargeur. |
| Binance USD‑M diff-depth | `E` (événement), `T` (transaction si fourni), plage `U..u`, `pu` (dernier `u` précédent); snapshot REST `lastUpdateId` | Vérifier le pont snapshot/deltas et `pu` contre le dernier `u`; reset/reconnexion impose une nouvelle base REST et un nouveau pont. Les doublons et régressions ne font pas avancer le carnet. | N’ancrer qu’après le pont documenté; sur gap, vider/invalider le carnet et recommencer le snapshot REST. | Non actuellement. |
| Bybit V5 public orderbook | `ts`, `cts`, `u` (update ID), `seq` (cross-sequence, comparaison entre profondeurs) | Le contrat Full Orderbook décrit `u` consécutif pour les deltas; `seq` peut sauter. `u=1` signale un snapshot de redémarrage, jamais un delta réutilisable. Détection stricte des trous par `u`; ne pas exiger `seq+1`. | Snapshot complet réinitialise; gap, reset, payload invalide ou reconnexion invalide et vide le carnet jusqu’au prochain snapshot. | Non actuellement. |
| OKX `books` | `ts`, `seqId`, `prevSeqId`; `action=snapshot/update` | Les deltas chaînent `prevSeqId` au dernier `seqId`; snapshot avec `prevSeqId=-1`. Tout lien manquant, gap, régression, reset ou payload invalide invalide l’état. | Nouveau snapshot complet seulement. `books5` et `bbo-tbt` sont traités comme observations snapshot, pas comme la chaîne incrémentale de `books`. | Non actuellement. |
| Gate futures `futures.order_book_update` | `t` (ms), plage `U..u`, snapshot complet `full=true`; base REST `id` | Une mise à jour delta doit chevaucher le prochain identifiant attendu (`U <= last+1 <= u`). Reset/gap ou plage/heure absente invalide le carnet. Une delta vide des deux côtés peut être un heartbeat de séquence valide et faire avancer l’heure/l’ID. | Ancrage complet ou pont REST/WS documenté; après invalidation, aucune delta ne réactive le carnet. | Non actuellement. |
| Bitget Classic V2 `books` | Schéma `arg.channel`/`instId`, `ts`, `seq`/`pseq`, `bids`/`asks` | Une delta exige `pseq == dernier seq`; `pseq=0` n’est permis que pour l’ancre snapshot. Connexion ou changement Classic/UTA exige un snapshot. `books1/5/15` ne sont pas consommés comme deltas. | Snapshot complet seulement après gap, reset, niveaux mal formés ou changement de mode. | Non actuellement. |
| Bitget UTA V3 `books` | Schéma distinct `arg.topic`/`symbol`, `ts`, `seq`/`pseq`, `b`/`a` | Même chaîne `pseq` dans son propre mode; ne jamais mélanger une delta UTA avec un snapshot Classic (ou inversement). | Snapshot UTA complet après changement de connexion/mode ou invalidation. Le client actuel n’abonne pas le L2 UTA. | Non actuellement. |

**Bitget `books50` :** au 29 octobre 2026, le changement annoncé vers des
deltas est encore présenté par le changelog officiel comme actif en démo et
prévu en production à partir du 5 novembre. Le collecteur ne doit donc pas
interpréter ce canal comme incrémental en production avant confirmation de sa
mise en service et une fixture live/versionnée. La règle ne s’étend pas
automatiquement à `books1/5/15`.

Les profils de capture d’autres plateformes ne valent pas contrat L2 certifié.
Ils restent hors de cette matrice et hors du replay économique tant qu’un
adaptateur, ses règles natives, ses fixtures et son admission SAFE ne sont pas
prouvés explicitement.

## Sources officielles

- [Hyperliquid — WebSocket subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)
- [Binance — USD‑M diff-depth streams](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/diff-book-depth-streams)
- [Bybit — V5 public orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook) et [Full Orderbook synchronization](https://bybit-exchange.github.io/docs/v5/websocket/public/full-ob)
- [OKX — API V5](https://www.okx.com/docs-v5/en/)
- [Gate — Futures WebSocket API](https://www.gate.com/docs/developers/futures/ws/en/)
- [Bitget — Classic changelog (pseq sur les carnets futures)](https://www.bitget.com/zh-CN/legacy-docs/classic/changelog), [UTA orderbook channel](https://www.bitget.com/zh-CN/api-doc/uta/websocket/public/Order-Book-Channel) et [annonce books50](https://www.bitget.com/docs/uta/update-preview)

## Preuves locales associées

- Adaptateurs: `src/hl_observer/collection/{binance_depth_book,bybit_market_data,okx_market_data,gate_market_data,bitget_market_data}.py`.
- Admission Copy‑Vault: `src/hl_observer/backtesting/copy_vault_book_loader.py` et `_book_row` dans `copy_vault_local_lab.py`.
- Fixtures d’intégrité/récupération: `tests/test_native_orderbook_integrity.py`, `tests/test_native_venue_transport_integrity.py`, `tests/test_binance_depth_book.py`, `tests/test_okx_market_data.py`, `tests/test_data_expansion.py` et `tests/test_collect_cloud_window.py`.

La qualité exploitable d’un adaptateur ne certifie pas à elle seule la
continuité inter-shards, l’exhaustivité des venues, l’absence de latence
inexécutable, ni un PnL. Toute donnée ou frontière non prouvée reste exclue ou
non mesurable.
