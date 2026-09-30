# Ajouts forensic de Codex a REAPPLIQUER — src/hl_observer/ui/simulation_log_export.py

## Ce qui s'est passe (2026-07-12)

Le mount a **tronque** ce fichier : il s'arretait en plein milieu d'une instruction
(`lines.app`), et la definition de `_as_float` avait disparu.
Consequence : **NameError a l'execution** — l'export de logs aurait plante.
Un fichier coupe sur `lines.app` **compile quand meme** (c'est une expression valide) :
`py_compile` ne l'a pas vu.

J'ai restaure la version git (complete, 771 lignes, valide). **Les ajouts forensic de Codex
a CE fichier sont donc a reappliquer.** Le reste de son travail (negative_pnl_auditor,
decision_replay_analyzer, fusion_heartbeat_input) est intact.

## Fichier de reference

`docs/audit/simulation_log_export_AJOUTS_CODEX_A_REAPPLIQUER.py.txt`
(⚠️ contient 5 fonctions DUPLIQUEES — ne pas copier tel quel, en extraire les champs)

## Champs a re-ajouter (27 lignes distinctes)

```python
        "position_key": row.get("position_key"),
        "source_delta_key": row.get("source_delta_key"),
        "notional_closed_usdt": row.get("notional_closed_usdt"),
        "remaining_notional_usdt": row.get("remaining_notional_usdt"),
        "size_before": row.get("size_before"),
        "size_closed": row.get("size_closed"),
        "size_after": row.get("size_after"),
        "reduce_fraction": row.get("reduce_fraction"),
        "sltp_position_age_ms": row.get("sltp_position_age_ms"),
        "sltp_stop_min_hold_ms": row.get("sltp_stop_min_hold_ms"),
        "sltp_catastrophic_stop_bps": row.get("sltp_catastrophic_stop_bps"),
        "funding_cost_usdc": row.get("funding_cost_usdc"),
        "funding_hours": row.get("funding_hours"),
        "leader_wallets_count": row.get("leader_wallets_count") or row.get("consensus_wallets"),
        "leader_wallets_csv": row.get("leader_wallets_csv"),
        "liquidity_score": row.get("liquidity_score"),
        "spread_bps": row.get("spread_bps"),
        "slippage_bps": row.get("slippage_bps"),
        "orderbook_depth_usdc": row.get("orderbook_depth_usdc"),
        "wallet_score": row.get("wallet_score"),
        "signal_score": row.get("signal_score"),
        "leader_event_time_ms": row.get("leader_event_time_ms"),
        "edge_source": row.get("edge_source"),
        "edge_is_empirical": row.get("edge_is_empirical"),
        "strategy_id": row.get("strategy_id"),
        "strategy_family": row.get("strategy_family"),
        "source_profiles": row.get("source_profiles"),
```
