# HyperSmart Dashboard

Le dashboard exporte un HTML read-only dans `data/dashboard/hypersmart_dashboard.html`.

Sections:

- safety banner;
- runtime/archive readiness;
- data collection status;
- wallet discovery;
- smart wallet rankings;
- position lifecycle;
- pattern detector;
- backtests/replays;
- paper trading;
- risk events;
- limitations.

Il ne contient aucun bouton trade, buy, sell, execute, connect wallet ou private key.
## Docs-to-code checklist

- [x] Read-only UI exists.
- [x] Simulation panel uses real local API data.
- [x] Dangerous trading buttons are forbidden by tests.
- [ ] Add scanner priority and missed-opportunity cards.
- [ ] Add provider health table.
- [ ] Add local index benchmark card.
- [ ] Add empty states for every new data section.
