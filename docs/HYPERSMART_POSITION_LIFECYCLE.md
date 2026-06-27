# HyperSmart Position Lifecycle

Le lifecycle transforme fills et evenements en actions:

- ouverture;
- augmentation;
- reduction;
- fermeture;
- liquidation;
- UNKNOWN.

Si les champs sont incomplets, HyperSmart garde `UNKNOWN` avec warning. Il ne reconstruit pas une entree ou une sortie inexistante.
## Docs-to-code checklist

- [x] Delta detector handles open/add/reduce/close.
- [x] Fill fields `dir`, `startPosition`, `closedPnl` are used in tests.
- [ ] Episode table with holding time for every reconstructed position.
- [ ] Confidence score per lifecycle episode.
- [ ] Contradiction report when fills and snapshots disagree.
