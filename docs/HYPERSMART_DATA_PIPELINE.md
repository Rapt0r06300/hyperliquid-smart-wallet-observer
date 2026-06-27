# HyperSmart Data Pipeline

Pipeline local:

1. Observation read-only: `/info`, imports, explorer observer experimental, WebSocket read-only planifie.
2. Discovery: candidats wallets dedupliques.
3. Position lifecycle: ouvertures, fermetures, reductions, augmentations, UNKNOWN si ambigu.
4. Scoring: metriques prudentes avec refus si echantillon insuffisant.
5. Ranking V2: recherche uniquement, jamais signal.
6. Pattern detection: evidence count et confidence, research-only.
7. Backtesting local: fees, spread, slippage, latency.
8. Paper simulation locale: risk gate obligatoire.
9. Dashboard read-only: visualisation sans action dangereuse.

Aucune etape n'envoie d'ordre.
## Docs-to-code checklist

- [x] Local cache provider documented.
- [x] Official `/info` and WS are read-only and explicit.
- [x] Provider registry command exists.
- [ ] Persist provider health into dashboard.
- [ ] Add optional DuckDB/Parquet backend.
- [ ] Add incremental refresh cursors for local index.
