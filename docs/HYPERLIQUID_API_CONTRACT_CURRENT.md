# Contrat API Hyperliquid courant

Verification : 2026-07-29  
Perimetre : lecture seule `/info` et WebSocket public/utilisateur.

Sources officielles :

- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats

## Reponses et pagination

| Contrat | Valeur | Usage HyperSmart |
|---|---:|---|
| Reponse temporelle generique | 500 elements/blocs distincts | garde conservative des collecteurs generiques |
| `userFills` | 2 000 fills recents | limite de validation de la reponse |
| `userFillsByTime` | 2 000 fills par reponse | pagination `startTime` inclusive |
| Historique visible `userFillsByTime` | 10 000 fills recents | garde de disponibilite, jamais borne de boucle implicite |
| `userTwapSliceFills` | 2 000 slices recentes | preuve TWAP avec `twapId` |

La pagination temporelle utilise le dernier timestamp retourne puis
`next_start = last_timestamp + 1`. Elle s'arrete explicitement sur reponse vide,
curseur immobile, page dupliquee, nombre maximal de pages ou nombre maximal de
fills. Chaque arret produit un `stopped_reason`.

## Poids REST par IP

- budget agrege : 1 200 poids par minute ;
- `l2Book`, `allMids`, `clearinghouseState`, `orderStatus`,
  `spotClearinghouseState`, `exchangeStatus` : poids 2 ;
- `userRole` : poids 60 ;
- autre requete `/info` documentee : poids 20 ;
- endpoint itemise tel que `userFillsByTime` ou `userTwapSliceFills` :
  poids additionnel 1 par tranche de 20 elements retournes ;
- `candleSnapshot` : poids additionnel 1 par tranche de 60 elements ;
- Explorer : poids 40.

Le budgeter applique ces poids sans multiplier par erreur chaque tranche de
20 par le poids de base 20. Il reste volontairement sous une cible de securite
et ne contourne jamais un refus serveur.

## WebSocket

- 10 connexions simultanees ;
- 30 nouvelles connexions par minute ;
- 1 000 subscriptions ;
- 10 utilisateurs uniques pour les subscriptions user-specific ;
- 2 000 messages emis par minute ;
- 100 requetes post simultanees ;
- fermeture serveur possible apres 60 secondes sans message.

Les snapshots initiaux `userFills` sont distingues des increments par
`isSnapshot`. La deduplication est faite au niveau des items et les trous
declenchent une recuperation REST bornee.

## TWAP read-only

HyperSmart autorise `userTwapSliceFills` dans son client `/info`. La forme
attendue contient `fill` et `twapId`. Cette lecture sert uniquement a
l'evidence shadow des metaordres ; elle ne place, ne modifie et n'annule aucun
TWAP.

## Frontiere de securite

`/exchange` est hors contrat et interdit. Aucun code de ce bloc ne signe, ne
detient de cle privee et ne cree d'ordre reel.
