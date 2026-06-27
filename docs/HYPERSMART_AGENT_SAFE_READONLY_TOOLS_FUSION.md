# HyperSmart Agent Safe Readonly Tools Fusion

## Objectif

Publier un manifeste agent-safe read-only pour permettre a un agent de lire
status, source health, leaderboard, decision ledger and dashboard exports sans
outil write/trade.

## Source GitHub inspiratrice

PolyTerm pour manifest/JSON schemas/doctor/exports/zero custody, Polymarket
agents pour research layer offline only.

## Adaptation Hyperliquid

Allowed tools:

```text
status.read
wallet.leaderboard
decision_ledger.search
dashboard.export
source_health.read
```

Forbidden: any write action, trade action, private-key flow, signature, CLOB,
wallet connect, live toggle, executor-service or `/exchange`.

## Modules cibles

- `hyper_smart_observer/agent_tools/readonly_manifest.py`
- `hyper_smart_observer/agent_tools/schemas.py`
- `docs/HYPERSMART_AGENT_SAFE_READONLY_TOOLS_FUSION.md`

## Donnees Hyperliquid utilisees

Only local read-only derivatives: SQLite source health, leaderboard rows,
DecisionLedger entries and dashboard export metadata.

## Tests requis

- `test_agent_safe_manifest_readonly_only.py`
- `test_no_exchange_sdk_imports_or_actions.py`
- `test_no_private_key_signature_live_toggle.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

DONE. The manifest module exposes only status/read, leaderboard read,
ledger search, dashboard export and source-health read contracts.
