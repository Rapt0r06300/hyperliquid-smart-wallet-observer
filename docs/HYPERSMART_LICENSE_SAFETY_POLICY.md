# HyperSmart License Safety Policy

## Objectif

Utiliser les depots externes comme sources d'idees only. No external code copy
without a separate license review, provenance note and explicit approval.

## Source GitHub inspiratrice

All fusion repositories. Several are MIT, PolyWeather is AGPL-3.0, and
prediction-market-backtesting includes Nautilus-derived LGPL/GPL style notices.
Because license mix varies, HyperSmart must not copy code from any external
repo during this fusion pass.

## Adaptation Hyperliquid

Allowed:

- summarize architecture ideas;
- map concepts to Hyperliquid read-only data;
- write original local code;
- link to source repository in docs;
- record KEEP/ADAPT/BAN/DEFER decisions.

Forbidden:

- paste external implementation;
- copy tests, schemas or configs verbatim;
- import external trading SDKs for execution;
- add incompatible license files without review;
- remove attribution from referenced ideas.

## Modules cibles

- `docs/research/HYPERSMART_REPO_IDEA_MATRIX_FUSION.md`
- `docs/research/HYPERSMART_GITHUB_FUSION_MASTER.md`
- all future fusion implementation modules.

## Donnees Hyperliquid utilisees

License policy does not read Hyperliquid data. It gates all implementation
touching read-only scanner, dashboard, backtest and agent tools.

## Tests requis

- `test_no_external_code_copy_license_markers.py`
- `test_repo_idea_matrix_has_keep_adapt_ban_defer.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

DONE for this fusion pass: no external code was copied. PARTIAL for future:
each implementation PR must repeat license review before importing any source.

