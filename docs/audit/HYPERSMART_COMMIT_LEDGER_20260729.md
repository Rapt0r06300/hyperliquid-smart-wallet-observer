# HyperSmart Commit Ledger - 2026-07-29

Ce registre associe chaque bloc logique de la roadmap V2 à son commit de code,
ses tests et sa preuve runtime. Les SHA sont ajoutés immédiatement après le
commit correspondant; aucun état `DONE` n'est déduit d'un simple flag.

| Bloc | Objet | SHA code | Tests | Preuve runtime | Statut |
|---:|---|---|---|---|---|
| 3 | Contrat d'horodatage causal et fraîcheur après redémarrage | `4589481` | 59 tests ciblés verts | Appel runtime : frais à 120 ms, même snapshot refusé à 2120 ms ; données legacy sans wall clock refusées `TS_ABSENT` | DONE |
| 1 | Périmètre stratégique autoritaire | `0ffa5e5` | 30 tests ciblés verts | CLI `refactor-fusion-run`: 1 ordre cross-venue, 0 funding, 0 bus externe | DONE |
| 2 | Contrat de sens cross-venue explicite | `37b1635` | 53 tests ciblés verts | Appel runtime `signaux_cross_venue`: BUY HL/SELL Binance et SELL HL/BUY Binance aux prix exécutables | DONE |
