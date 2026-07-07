# HyperSmart Fast Scan Design

Date: 2026-06-18

Ce document remplace les anciennes notes de scan agressif. Le design actuel
reste Hyperliquid read-only, simulation locale uniquement, sans ordre reel.
La collecte large (scraping + pool de proxies/rotation) est AUTORISEE (cf. V9 §8).

## Objectif

Trouver rapidement des opportunites observables sans inventer de donnees:

- shortlist locale de leaders complets `0x` + 40 hex;
- rotation de leaders bornee;
- `/info` read-only pour `allMids`, `l2Book`, `clearinghouseState`,
  `userFillsByTime`, `userFills`, `openOrders`, `frontendOpenOrders`;
- WebSocket read-only uniquement avec duree bornee et max 10 users uniques;
- fallback REST polling quand le WS est indisponible ou non borne;
- source-health obligatoire pour expliquer les trous de donnees.

## Pipeline rapide mais propre

```text
leaderboard/imports/local DB
-> shortlist bornee
-> copy-run --network-read
-> snapshots positions/fills/orders
-> deltas leader
-> market features allMids/l2Book/candles
-> SignalCandidate ou NoTradeDecision
-> PaperIntent/PaperTrade local si gates OK
-> DecisionLedger + copy-report + dashboard
```

## Garde-fous

- Pas de `/exchange`.
- Pas de signature.
- Pas de private key.
- Pas de wallet connect.
- Pas de mainnet/testnet executor.
- Scraping et pool de proxies/rotation AUTORISES (budget de poids par IP, cf. V9 §8).
- Pas de fake PnL ni fake chart.

## Mesure de performance

La vitesse se juge par:

- latence collecte par wallet;
- nombre de wallets valides scannes;
- nombre de deltas exploitables;
- taux de signaux refuses et raisons;
- fraicheur `source_ts -> local_received_ts`;
- PnL paper realise/non realise;
- drawdown paper;
- preuves `DecisionLedger`.

Ce design sert a maximiser les donnees fraiches dans les limites officielles et
observables, pas a promettre un profit.
