# Copy‑Vault — matrice d’accès L4 vérifiée

Date de vérification : **2026-10-29**. Cette matrice décrit des capacités documentées ; elle
n’active aucun collecteur, ne crée aucune clé et n’engage aucun fournisseur payant.

## Décision

**NO-GO opérationnel pour L4 dans Copy‑Vault aujourd’hui.** Le runtime reste sur les sources
locales SAFE déjà autorisées. Une source L4 tierce ne pourra être activée qu’après décision
explicite, secret injecté hors dépôt, contrat de coût/quota accepté et fixtures de protocole
rejouables. L’absence d’une source n’est jamais remplacée par un faux événement, un L2 ou un
fill public.

## Matrice des capacités

| Source | Transport / accès | Snapshot + diffs L4 | Séquences / epoch | Historique / replay | Coût ou limite publiquement vérifiée | État Copy‑Vault |
|---|---|---|---|---|---|---|
| Hyperliquid public | `wss://api.hyperliquid.xyz/ws` | L4 `l4BookUpdates` non exposé sur cet endpoint | N/A pour L4 | L4 non disponible | API publique documentée pour les flux officiels, mais pas pour ce flux L4 | **UNAVAILABLE** |
| GoldRush | WebSocket propriétaire `wss://hypercore.goldrushdata.com/ws?key=...` | Diff-only order-level ; bootstrap REST `l4BookSnapshot` ; perps uniquement | `seq`, `prev_seq`, `epoch`, `block_height`, `cursor` | Flux temps réel ; la page consultée ne fournit pas de replay historique du flux | **1 crédit / coin / minute** ; clé API obligatoire | **PARTIAL / NO-GO** |
| QuickNode | gRPC `OrderBookStreaming/StreamL4BookUpdates` | Snapshot reset initial et resets ultérieurs ; diffs typés NEW/UPDATE/REMOVE | La documentation consultée expose `height` et snapshot/reset ; ne pas supposer `seq/prev_seq/epoch` sans contrat du flux sélectionné | Temps réel ; pas de replay historique L4 démontré dans les pages consultées | **0,0165 MB = 10 crédits API** ; endpoint + token ; accès live/query history à partir du plan Build selon le quickstart | **PARTIAL / NO-GO** |
| Alchemy | WebSocket HyperCore beta `wss://hypercore-mainnet.g.alchemy.com/v2/<API_KEY>` | `l4BookUpdates` annoncé comme snapshot puis order diffs | `seq` par abonnement ; bloc/temps ; gap/book_reset à gérer ; le contrat L4 détaillé doit être revalidé avant admission | Pas de replay L4 ; la documentation indique resubscription + snapshot pour les books | Accès HyperCore activé par équipe pendant la beta ; clé API ; volumes non filtrés élevés | **PARTIAL / NO-GO** |
| 0xArchive | Documentation fournisseur référencée, accès non récupérable pendant cet audit | **UNKNOWN** tant que contrat, schéma et disponibilité ne sont pas vérifiés | **UNKNOWN** | **UNKNOWN** | Aucun coût/quota ne doit être inventé | **UNKNOWN / NO-GO** |

## Ce qui est prouvé et ce qui ne l’est pas

- GoldRush documente explicitement le bootstrap `l4BookSnapshot`, le flux `l4BookUpdates`
  diff-only, les champs `seq`/`prev_seq` par coin et l’`epoch`; son endpoint est distinct du
  WebSocket Hyperliquid public.
- QuickNode documente une variante gRPC avec snapshots de reset et diffs typés, mais ce n’est
  pas le même contrat que le flux GoldRush : les champs ne doivent pas être transposés entre
  fournisseurs.
- Alchemy documente un flux HyperCore L4 en beta, avec clé et accès activé par équipe ; la
  beta, le volume et les limites imposent une revalidation avant toute collecte SAFE.
- Le flux officiel public Hyperliquid reste la source autorisée actuelle ; aucune capacité L4
  tierce n’est ajoutée au runtime par cette matrice.

## Compatibilité avec le runtime local

`src/hl_observer/collection/l4_capture.py` reste `BLOCKED_EXTERNAL` sans source explicite.
`src/hl_observer/collection/feed_integrity.py::L4BookIntegrity` vérifie le protocole générique
fourni par une source validée : état indépendant par marché, ancre `height + seq + epoch`,
`prev_seq`, gap, doublon contradictoire, changement d’epoch et resnapshot. Le validateur ne
fait aucun appel réseau et n’autorise pas la preuve SAFE tant qu’un snapshot valide n’a pas
réancré le marché.

## Sources officielles consultées

- Hyperliquid WebSocket : <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket>
- GoldRush `l4BookUpdates` : <https://goldrush.dev/docs/api-reference/hyperliquid-websocket/l4-book-updates>
- QuickNode L4 dataset : <https://www.quicknode.com/docs/hyperliquid/datasets/l4-book-updates>
- QuickNode gRPC L4 : <https://www.quicknode.com/docs/hyperliquid/grpc-api/StreamL4BookUpdates>
- QuickNode quickstart / plans : <https://www.quicknode.com/docs/hyperliquid/quickstart>
- Alchemy HyperCore WebSocket : <https://www.alchemy.com/docs/chains/websockets/hypercore>
- Alchemy erreurs et limites : <https://www.alchemy.com/docs/chains/websockets/hypercore/errors-and-limits>
- 0xArchive (référence à revalider) : <https://docs.0xarchive.io/hyperliquid-websocket-streaming-api>
