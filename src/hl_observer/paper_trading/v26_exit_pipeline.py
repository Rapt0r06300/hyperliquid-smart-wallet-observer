"""V26 — Pipeline post-exits : nourrit les books (L5/L6), halt gradué (L4), auto-unstuck (L3).

Appelé par ``apply_sltp_exits_vol_adjusted`` après chaque passe d'exits, avec le
ledger comme SEULE source de vérité :

1. ingestion des nouveaux closes → ProtectionsBook (L5) + KellyLeaderBook (L6) —
   observation pure, toujours active (les flags ne gèrent que les ACTIONS) ;
2. mise à jour du halt gradué (L4) ; à RED : sorties forcées paper (une fois) ;
3. passe d'auto-unstuck (L3) sur les positions restantes.

Fail-safe total : toute exception ⇒ no-op (le moteur d'exits n'est jamais cassé).
Paper-only : tout événement produit est un close simulé du ledger, jamais un ordre.
"""

from __future__ import annotations

from typing import Any


def run_v26_exit_pipeline(
    positions: dict[Any, dict[str, Any]],
    ledger_events: list[dict[str, Any]],
    mid_prices: dict[str, float] | None,
    *,
    now_ms: int,
    cost_bps: float = 12.0,
    ledger_len_before: int = 0,
    env: dict | None = None,
    paper_mode: str = "PAPER_LOCAL_USDT_ONLY",
) -> dict[str, Any]:
    """Une passe complète. Retourne un résumé read-only (dashboard/audit)."""
    summary: dict[str, Any] = {"pipeline": "V26", "actions": []}

    # 0) Enregistreur de marks pour le harnais A/B (L9) — observation pure, opt-in.
    try:
        import os as _os

        if str(_os.environ.get("HYPERSMART_V26_RECORD_CANDIDATES", "0")).lower() in ("1", "true", "yes", "on"):
            import json as _json
            import pathlib as _pl

            base = _pl.Path(str(_os.environ.get("HYPERSMART_V26_RECORD_PATH", "") or "runtime/replay"))
            base.mkdir(parents=True, exist_ok=True)
            ts = (float(now_ms) / 1000.0) if now_ms else None
            _rows = []
            for _coin, _mid in (mid_prices or {}).items():
                try:
                    _rows.append({"ts": ts, "coin": str(_coin).upper(), "mid": float(_mid)})
                except (TypeError, ValueError):
                    continue
            # ANTI-BLOAT: append CAPÉ (le run 48h a crashé sur du stockage non borné).
            from hl_observer.runtime.replay_recorder import (
                MARKS_MAX_BYTES, MARKS_MAX_LINES, append_replay_lines)
            append_replay_lines(base, "marks.jsonl", _rows,
                                max_bytes=MARKS_MAX_BYTES, max_lines=MARKS_MAX_LINES)
    except Exception:
        pass

    # 1) Observation : ingérer les closes AJOUTÉS pendant cette passe (jamais deux fois).
    try:
        new_events = [e for e in ledger_events[max(0, int(ledger_len_before)):] if isinstance(e, dict)]
        if new_events:
            from hl_observer.risk.kelly_leader_book import DEFAULT_KELLY_LEADER_BOOK
            from hl_observer.risk.protections_v26 import DEFAULT_PROTECTIONS_BOOK

            summary["protections_ingested"] = DEFAULT_PROTECTIONS_BOOK.update_from_ledger_events(new_events)
            summary["kelly_ingested"] = DEFAULT_KELLY_LEADER_BOOK.update_from_ledger_events(new_events)
            # note de performance marché (L8) depuis les closes réels
            try:
                from hl_observer.risk.protections_v26 import close_record_from_ledger_event
                from hl_observer.signals.market_quality_score import DEFAULT_MARKET_QUALITY_BOOK

                pnl_by_coin: dict[str, float] = {}
                for ev in new_events:
                    rec = close_record_from_ledger_event(ev)
                    if rec:
                        pnl_by_coin[rec.coin] = pnl_by_coin.get(rec.coin, 0.0) + rec.net_pnl_usd
                for coin, pnl in pnl_by_coin.items():
                    DEFAULT_MARKET_QUALITY_BOOK.observe(coin, market_pnl_usd=pnl, env=env)
            except Exception:
                pass
    except Exception:
        pass

    # 2) Halt gradué (L4) : update + RED => sorties forcées paper (une seule fois par épisode).
    try:
        from hl_observer.risk.graded_halt import DEFAULT_GRADED_HALT, force_exit_all_positions
        from hl_observer.risk.graded_halt import flag_on as halt_flag_on

        if halt_flag_on(env):
            state = DEFAULT_GRADED_HALT.update(ledger_events, now_ms, env)
            summary["graded_halt_state"] = state
            fx = DEFAULT_GRADED_HALT.effects(env)
            if fx.force_exit_all and positions:
                forced = force_exit_all_positions(
                    positions, ledger_events, mid_prices,
                    now_ms=now_ms, cost_bps=cost_bps, paper_mode=paper_mode,
                )
                DEFAULT_GRADED_HALT.mark_forced_exit_done()
                summary["actions"].extend(forced)
    except Exception:
        pass

    # 3) Auto-unstuck (L3) sur les positions restantes.
    try:
        from hl_observer.paper_trading.auto_unstuck import apply_auto_unstuck

        acts = apply_auto_unstuck(
            positions, ledger_events, mid_prices,
            now_ms=now_ms, cost_bps=cost_bps, env=env, paper_mode=paper_mode,
        )
        summary["actions"].extend(acts)
    except Exception:
        pass

    return summary


__all__ = ["run_v26_exit_pipeline"]
