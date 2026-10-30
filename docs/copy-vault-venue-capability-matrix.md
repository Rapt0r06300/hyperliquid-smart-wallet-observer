# Copy‑Vault — matrice officielle des capacités venues

Cette matrice est une règle d’admission, pas un indicateur de présence de fichier ou de santé réseau. Elle sépare strictement l’activité d’un portefeuille des données de marché publiques.

| Venue | Discovery/classement leader | Historique wallet | Flux wallet | BBO/L2/trades publics | Règle Copy‑Vault |
|---|---|---|---|---|---|
| Hyperliquid | PARTIAL : adresse connue, aucun classement public supposé | SUPPORTED : adresse maître/sous-compte réelle, fenêtres bornées | PARTIAL : flux utilisateur soumis aux limites documentées | SUPPORTED | Seuls les endpoints utilisateur réellement causaux peuvent fournir une preuve leader. |
| Binance | UNAVAILABLE en public | UNAVAILABLE en public | UNAVAILABLE en public | SUPPORTED | Les données de marché ne sont jamais une preuve de fills wallet. |
| Bybit | UNAVAILABLE en public | UNAVAILABLE en public | UNAVAILABLE en public | SUPPORTED | La catégorie produit et la continuité snapshot/delta sont obligatoires. |
| OKX | UNAVAILABLE en public | UNAVAILABLE en public | UNAVAILABLE en public | SUPPORTED | L’instrument et `instType` restent dans l’identité native. |
| Gate | UNAVAILABLE en public | UNAVAILABLE en public | UNAVAILABLE en public | SUPPORTED | La famille de règlement et la séquence native restent obligatoires. |
| Bitget | UNAVAILABLE en public | UNAVAILABLE en public | UNAVAILABLE en public | SUPPORTED | `instType`, snapshot et `seq/pseq` sont requis pour un flux exploitable. |

Sources officielles conservées dans le code : [Hyperliquid Info](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [limites Hyperliquid](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits), [Binance local book](https://developers.binance.com/en/docs/derivatives/usds-margined-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly), [Bybit orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook), [OKX API v5](https://www.okx.com/docs-v5/en), [Gate futures WS](https://www.gate.com/docs/developers/futures/ws/en), [Bitget depth](https://www.bitget.com/docs/uta/websocket/public/Order-Book-Channel).

Statuts : `SUPPORTED` signifie que le contrat public est documenté et admissible pour ce type de donnée ; `PARTIAL` impose des limites explicites et une admission plus restrictive ; `UNAVAILABLE` signifie que le collecteur Copy‑Vault ne doit pas prétendre fournir cette preuve ; `UNKNOWN` reste bloquant. Toute interruption, pagination tronquée, 429, gap ou identité ambiguë dégrade la collecte en `PARTIAL`/quarantaine jusqu’à réconciliation.
