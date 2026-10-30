# Copy-Vault — contrats des feeds Hyperliquid au 2026-10-29

Ce document certifie les hypothèses de collecte utilisées par le runtime
`src/hl_observer/`. Il ne crée pas un second collecteur et ne fixe pas une
cadence locale : la cadence de publication reste une propriété du serveur et
chaque décision doit être autorisée par les timestamps source/réception et par
la qualité du carnet.

Sources de référence :

- [Hyperliquid — WebSocket subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)
- [QuickNode — Hyperliquid Foundation WebSocket Changes](https://www.quicknode.com/blog/hyperliquid-foundation-websocket-changes)

## Matrice canal → contrat → code → tests → écart

| Canal | Contrat actuel vérifié | Hypothèse du code | Test/fixture | Écart ou décision |
| :--- | :--- | :--- | :--- | :--- |
| `l2Book` | `coin`, `levels=[bids, asks]`, `time`; abonnement optionnel `fast`, `nSigFigs`, `mantissa`; fast = profondeur publique courte, slow = profondeur publique plus profonde | `rest_info_client.py` construit la requête REST ; `l2_snapshot_cache.py` conserve le carnet complet ; `ExecutionTruth` sépare source/réception ; le nouveau contrat ne fabrique pas de cadence | `test_hyperliquid_feed_contracts.py` : abonnement, fraîcheur, profondeur, identité ; `test_l2_gap_detection.py`, `test_native_market_tape.py`, tests d’exécution | Les intervalles annoncés sont descriptifs, pas une horloge de substitution. Un carnet stale, non causal ou trop peu profond reste non exploitable. |
| `bbo` | `coin`, `time`, `bbo=[bid, ask]`; mise à jour lorsque le BBO change sur un bloc | Contrat explicite disponible, mais un BBO n’est jamais promu au rang de profondeur L2 | `test_hyperliquid_feed_contracts.py` vérifie la souscription ; les gates L2/exécution restent obligatoires pour un fill | Le BBO seul ne certifie ni slippage, ni capacité, ni exécution profonde ; aucune promotion automatique. |
| `allMids` | objet `mids`; feed de contexte périodique | `rest_info_client.py` ne l’utilise que comme donnée de contexte ; pas de substitution silencieuse au BBO/L2 | Contrats de souscription et tests REST existants | Un mid absent ou ancien ne devient jamais un prix d’exécution. |
| `webData3` | abonnement avec adresse ; `userState.serverTime` dans le format courant | `hyperliquid_clock_sync.py` l’utilise seulement comme preuve d’horloge/provenance, avec timeout, RTT et âge bornés | `test_hyperliquid_clock_sync.py` + contrat de souscription | Les champs frontend non documentés sont ignorés ; ce canal ne fournit pas de profondeur de marché. |
| `fastAssetCtxs` | chaîne base64 contenant du JSON compressé en DEFLATE brut ; premier message snapshot, suivants mises à jour partielles | `hyperliquid_feed_contracts.py` décode strictement base64 → raw DEFLATE → UTF-8 → JSON ; le canal est marqué contexte de mark price | Fixture officielle dans `test_hyperliquid_feed_contracts.py`, plus rejet des wrappers gzip/zlib et des canaux erronés | Il n’est pas branché sur une décision Copy-Vault : le contexte ne remplace ni L2 ni BBO. Toute future admission devra apporter identité, réception, cutoff et politique de snapshot/diff. |

## Garde-fous d’exécution

- `assess_l2_book_frame` exige l’instrument attendu, `time`, deux côtés
  valides, une réception antérieure à la décision, une source antérieure à la
  réception, un âge maximal explicite et le nombre minimal de niveaux demandé.
- `simulate_execution` conserve le comportement économique existant : les
  partial fills sont mesurés quand ils sont autorisés ; avec une exigence de
  fill complet, une profondeur insuffisante produit un no-fill (`MISSED_FILL`)
  et jamais un PnL inventé.
- Aucun code ne transforme `fast` en timer local, ne complémente les niveaux
  manquants, ne reconstruit un snapshot à partir d’un mid, ni ne convertit
  `fastAssetCtxs` en profondeur.
- Le module est réseau-free et PAPER/read-only. Aucun endpoint d’exécution,
  secret ou credential n’est ajouté.

## Validation exécutée

Commande locale :

```text
.venv\Scripts\python.exe -m pytest -q tests/test_hyperliquid_feed_contracts.py tests/test_hyperliquid_clock_sync.py tests/test_l2_gap_detection.py tests/test_native_market_tape.py tests/test_execution_models.py
```

Résultat au HEAD local du 2026-10-29 : **37 passed**.
