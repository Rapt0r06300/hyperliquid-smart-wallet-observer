# MEGA V1 Research To Decision Matrix

| Finding internet | Fiabilite | Decision HyperSmart | Module | Test | Commande | Statut |
|---|---|---|---|---|---|---|
| WS user fills ont un snapshot `isSnapshot` puis updates | OFFICIAL_HYPERLIQUID | Dedupe snapshot, ne pas traiter comme entree fraiche sans contexte | `src/hl_observer/wallets/user_fills_live.py` | `tests/test_user_fills_live_scan.py` | `live-user-fills-scan` | DONE |
| Deconnexions WS doivent etre gerees et reconciliees | OFFICIAL_HYPERLIQUID | Ajouter health/replay local et ne pas pretendre live si stale | `src/hl_observer/realtime/realtime_health.py` | `tests/test_realtime_health.py` | `realtime-health` | DONE |
| REST limite 1200/min et `userFills` coute par 20 elements | OFFICIAL_HYPERLIQUID | Scan massif uniquement local; reseau shortlist | `src/hl_observer/local_index`, `src/hl_observer/cli.py` | `tests/test_hypersmart_local_scan_performance_contract.py` | `benchmark-local-scan` | DONE |
| Explorer weight 40 | OFFICIAL_HYPERLIQUID | Explorer experimental/budget strict, pas de scraping agressif | `docs/HYPERSMART_API_LIMITS.md` | `tests/test_hypersmart_api_limits_constants.py` | `archive-audit` | DONE |
| WS limites 10 connexions, 1000 subscriptions, 10 users | OFFICIAL_HYPERLIQUID | Hot-watch rotation max 10 users | `src/hl_observer/realtime_monitor` | `tests/test_hypersmart_hot_watch_rotation.py` | `hot-watch` | DONE |
| Historique fills complet possible via dataset/S3/data provider | DATA_PROVIDER | Construire import/index local pour scale | `src/hl_observer/data_sources`, `src/hl_observer/local_index` | `tests/test_hypersmart_data_providers.py` | `scan-local` | DONE |
| Claims "Claude bot" scan/top wallets/profit | OSINT_CLAIM | Inspiration UX seulement; pas de promesse de gain | `docs/research/MEGA_V1_INTERNET_INTELLIGENCE_REPORT.md` | `tests/test_mega_v1_prompt_coverage.py` | `prompt-coverage-audit` | DONE |
| Copy trading peut echouer par retard/hedges invisibles | USER_REPORT / QUANT_BEST_PRACTICE | Ajouter loss attribution et root cause | `src/hl_observer/simulation/loss_attribution.py` | `tests/test_simulation_loss_report.py` | `simulation-loss-report` | DONE |
| Dashboard doit montrer provenance et non placeholders | UI_UX_BEST_PRACTICE | Dashboard truth audit | `src/hl_observer/dashboard_truth` | `tests/test_dashboard_truth_audit.py` | `dashboard-truth-audit` | DONE |

