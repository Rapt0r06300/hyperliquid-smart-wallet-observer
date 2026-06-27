# HyperSmart Test Matrix

Areas:

- runtime check;
- clean archive hygiene;
- `/info` payloads;
- explorer normalization;
- WebSocket limits and dedupe;
- wallet discovery;
- position lifecycle;
- ranking V2;
- pattern detector;
- backtesting;
- paper from observed action;
- dashboard read-only;
- safety audit.

All tests are designed to run without Internet.
## Docs-to-code checklist

- [x] Full pytest suite runs.
- [x] HyperSmart targeted tests run.
- [x] Scanner/local-index tests added.
- [ ] Dashboard screenshot smoke test for new scanner sections.
- [ ] Local benchmark regression threshold in CI.
- [ ] Provider registry contract tests for all future providers.
