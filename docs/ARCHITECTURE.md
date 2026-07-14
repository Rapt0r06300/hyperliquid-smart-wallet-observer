# Architecture & installation — HyperSmart Observer

> **Read-only / paper-only.** Aucun ordre réel n'est possible : 0 clé privée, 0 signature,
> 0 endpoint d'exécution. (IMPROVE-50)

## Schéma des flux

```
                    ┌──────────────────────────┐
   Hyperliquid ────►│  COLLECTE (lecture seule) │
   (REST /info      │  • REST Indexer (snapshots)│
    + WebSocket)    │  • Firehose WS userFills   │──┐
                    │  • WS-first (allMids)      │  │
                    └──────────────────────────┘  │
                                                    ▼
                    ┌────────────────────────────────────────┐
                    │  STOCKAGE                              │
                    │  • SQLite (positions, snapshots)       │
                    │  • replay jsonl par-process (candidats,│
                    │    marks) + cap atomique               │
                    └────────────────────────────────────────┘
                                                    │
                    ┌───────────────────────────────▼────────┐
                    │  DÉCISION (local, explicable)          │
                    │  • edge net après coûts                │
                    │  • gates: fraîcheur, liquidité,        │
                    │    consensus, dégradation              │
                    │  • FAIL-SAFE : doute ⇒ NO_TRADE        │
                    └───────────────────────────────┬────────┘
                                                    ▼
                    ┌────────────────────────────────────────┐
                    │  SIMULATION PAPER (jamais réelle)      │
                    │  • ledger d'événements (PnL vérifiable)│
                    │  • SL/TP, exits, frais/spread/slippage │
                    └───────────────────────────────┬────────┘
                                                    ▼
        ┌───────────────────────────────────────────────────────────┐
        │  RECHERCHE (hors-ligne)                                   │
        │  replay 150M scénarios · OOS · Monte-Carlo · contrôle     │
        │  aléatoire · PBO · gate "edge réel" · garde anti-lookahead│
        └───────────────────────────────────────────────────────────┘
```

## Modules clés (`src/hl_observer/`)
- **collection/** : collecte read-only, WS-first, `research_recorder` (stockage par-process capé).
- **backtesting/** : le **toolkit quant** — `quant_methods`, `validation_methods`, `cross_validation`,
  `risk_sizing`, `portfolio_risk`, `stress_testing`, `regime_detection`, `regime_models`,
  `microstructure`(+`_extras`), `execution_models`(+`_extras`, `_sim`), `signal_processing`,
  `features`, `cost_model`, `labeling`, `lookahead_guard`, `experiment_harness`, `ml_extras`,
  `ml_diagnostics`, `mlops_tools`, `reporting`, `safety_tools`, `perf_tools`, `runtime_guards`,
  `infra_primitives`, `quality_tools`, `strategies_extra`, `market_metrics`.
- **paper_trading/**, **signals/**, **risk/** : la simulation locale (jamais d'ordre réel).

## Installation (from scratch)

```bat
:: 1) Python 3.10+ requis
python -m venv .venv
.venv\Scripts\activate

:: 2) Dépendances
pip install -r requirements.txt

:: 3) Tests (tout doit être vert)
set PYTHONPATH=src
python -m pytest -q

:: 4) Lancer la simulation (paper, read-only)
LANCER_HYPERSMART.cmd
```

## Qualité
```bat
tools\ci_local.cmd        :: tests + audit sécurité + doctor (avant chaque commit)
tools\run_pipeline.cmd    :: rejoue toute la recherche (tests -> analyses -> rapports)
pip install ruff mypy && ruff check src tests && mypy src\hl_observer\backtesting
```

## Sécurité (non négociable)
✅ 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.
Le fail-safe renvoie **NO_TRADE** à la moindre donnée manquante ou douteuse.
