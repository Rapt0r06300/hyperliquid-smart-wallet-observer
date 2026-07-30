# HyperSmart - audit TWAP/metaorders causal - 2026-07-29

## Verdict

Statut: `SHADOW_VERIFIED`, non materialisable.

Le chemin existant `experimental/metaorder_shadow.py` a ete renforce au lieu
d'etre duplique. Il lit les fills et les preuves TWAP Hyperliquid en lecture
seule, produit des observations reproductibles et n'ouvre aucune position.

## Causes racines corrigees

| Defaut | Risque | Correction | Preuve |
|---|---|---|---|
| Le nombre total futur de slices entrait dans le classement du stade | Lookahead: un prefixe changeait apres l'arrivee du futur | `classer_stade` et le replay n'utilisent que le prefixe observable | test de stabilite avec snapshot futur |
| Le hash TWAP nul pouvait devenir une cle de deduplication | Plusieurs slices officielles pouvaient collisionner | identite `tid`, puis `(oid,time)`; hash nul ignore | test de deux slices au meme hash nul |
| Une fenetre temporelle regroupait seule les slices | Un TWAP officiel coupe par un long intervalle devenait plusieurs metaordres | `twapId` est l'identite prioritaire; inference uniquement sans preuve directe | test de regroupement direct au-dela de 60 s |
| Le residuel et le stade tardif pouvaient etre inferes sans taille totale observable | Confiance et edge artificiels | dernier `twapStates` horodate et causal; sinon `RESIDUAL_UNMEASURABLE` | test sans etat puis avec etat futur |
| Aucune grille standard de delai n'etait exportee | Comparaison de timing non reproductible | grille 50/100/250/500/1000/2000/5000 ms | test de couverture complete |

## Chaine reelle

`userFillsByTime + userTwapSliceFills + twapStates + tape prix/L2`
-> deduplication forte
-> replay causal par `(vault, coin, twapId)`
-> stade/residuel/cadence/catch-up
-> cout executable de la taille follower
-> markout/placebo/walk-forward SHADOW
-> ledger et statistiques separes.

Chaque observation porte `shadow=true` et `real_execution=false`. Les donnees
absentes restent `None`/`UNMEASURABLE`; elles ne deviennent jamais zero.

## Contrats officiels revalides

- Info API: `userTwapSliceFills`, jusqu'a 2000 resultats recents, avec
  `twapId`.
- WebSocket: `twapStates` expose `states: Array<[twapId, TwapState]>`.
- Order types: tranche normale toutes les 30 secondes; rattrapage borne a
  trois fois la tranche normale.

Sources:

- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types

## Limites honnetes

- Un metaordre cache sans `twapId` reste une inference, pas une identite
  officielle.
- Sans snapshot `twapStates` recu avant le fill, taille totale, residuel,
  fraction et ETA restent non mesurables.
- Les performances par stade exigent encore un echantillon OOS et des
  placebos suffisants avant toute promotion.
- Ce module ne prouve aucun edge positif et reste hors PnL canonique.

## Tests

`tests/test_metaorder_shadow.py` et `tests/test_metaorder_l2_tape.py` couvrent
identite, hash nul, causalite, stade, residuel, catch-up, cout, capacite,
walk-forward, placebos et grille de delais.

**Securite : 0 ordre reel, 0 argent reel, 0 cle privee, 0 signature, 0 depot/retrait.**
