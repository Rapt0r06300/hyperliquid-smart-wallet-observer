from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from hyper_smart_observer.simulation.simulation_engine import SimulationEngine

LOGS_TO_SEND_DIRNAME = "logs \u00e0 envoyer"


def write_simulation_engine_logs(engine: SimulationEngine, *, project_root: Path = Path("."), title: str = "cli_simulation") -> dict[str, str]:
    primary_log_dir = project_root / "logs" / LOGS_TO_SEND_DIRNAME
    log_dir, directory_warnings = _resolve_writable_log_dir(primary_log_dir)
    jsonl_path = log_dir / f"{title}_decisions_latest.jsonl"
    md_path = log_dir / f"{title}_resume_pour_chatgpt.md"
    snapshot_path = log_dir / f"{title}_snapshot_latest.json"
    rows = [_engine_event(row) for row in engine.fills]
    if not rows:
        rows = [_decision_event(index, decision) for index, decision in enumerate(engine.decisions, start=1)]
    warnings: list[str] = list(directory_warnings)
    jsonl_warning = _safe_write_text(
        jsonl_path,
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows),
    )
    snapshot_warning = _safe_write_text(
        snapshot_path,
        json.dumps(
            {
                "starting_equity": engine.portfolio.starting_equity,
                "current_equity": engine.portfolio.current_equity(),
                "realized_pnl": engine.portfolio.realized_pnl,
                "total_fees": engine.portfolio.total_fees,
                "open_positions": len(engine.portfolio.positions),
                "equity_curve": engine.portfolio.equity_curve,
                "decisions": [asdict(decision) for decision in engine.decisions],
                "execution": "forbidden",
                "research_only": True,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
    )
    md_warning = _safe_write_text(md_path, _render_engine_markdown(engine, rows))
    warnings.extend(warning for warning in (jsonl_warning, snapshot_warning, md_warning) if warning)
    return {
        "directory": str(log_dir),
        "primary_directory": str(primary_log_dir),
        "directory_status": "OK" if not warnings else "FALLBACK_USED" if log_dir != primary_log_dir else "WRITE_WARNINGS",
        "decisions_jsonl": str(jsonl_path),
        "snapshot_json": str(snapshot_path),
        "chatgpt_markdown": str(md_path),
        "write_warnings": " || ".join(warnings),
    }


def _safe_write_text(path: Path, text: str) -> str | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"{path}: {exc.__class__.__name__}: {exc}"
    return None


def _resolve_writable_log_dir(primary: Path) -> tuple[Path, list[str]]:
    primary_warning = _probe_log_dir(primary)
    if primary_warning is None:
        return primary, []
    warnings = [f"primary_log_dir_unavailable={primary}: {primary_warning}"]
    fallback = Path(gettempdir()) / "hypersmart_logs_a_envoyer"
    fallback_warning = _probe_log_dir(fallback)
    if fallback_warning is None:
        return fallback, warnings
    warnings.append(f"fallback_log_dir_unavailable={fallback}: {fallback_warning}")
    return primary, warnings


def _probe_log_dir(path: Path) -> str | None:
    probe = path / ".hypersmart_cli_probe.tmp"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("probe", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return f"{exc.__class__.__name__}: {exc}"
    return None


def _engine_event(fill: Any) -> dict[str, Any]:
    return {
        "fill_id": fill.fill_id,
        "coin": fill.coin,
        "side": fill.side.value,
        "action": fill.action.value,
        "price": fill.price,
        "size": fill.size,
        "notional": fill.notional,
        "fee": fill.fee,
        "timestamp_ms": fill.timestamp_ms,
        "realized_pnl": fill.realized_pnl,
        "plain_english": _explain_fill(fill),
        "research_only": True,
        "execution": "forbidden",
    }


def _decision_event(index: int, decision: Any) -> dict[str, Any]:
    return {
        "decision_id": f"decision:{index}",
        "coin": "N/A",
        "side": "N/A",
        "action": "NO_TRADE",
        "accepted": bool(decision.accepted),
        "reason": decision.reason,
        "message": decision.message,
        "price": None,
        "size": 0.0,
        "notional": 0.0,
        "fee": 0.0,
        "timestamp_ms": None,
        "realized_pnl": 0.0,
        "plain_english": _explain_decision(decision),
        "research_only": True,
        "execution": "forbidden",
    }


def _explain_fill(fill: Any) -> str:
    if fill.action.value == "OPEN":
        return f"Entree virtuelle {fill.side.value} sur {fill.coin}; frais simules {fill.fee:.6f}; aucune execution reelle."
    if fill.action.value == "REDUCE":
        return f"Reduction virtuelle {fill.side.value} sur {fill.coin}; PnL net evenement {fill.realized_pnl:.6f}; aucune execution reelle."
    if fill.action.value == "CLOSE":
        return f"Fermeture virtuelle {fill.side.value} sur {fill.coin}; PnL net evenement {fill.realized_pnl:.6f}; aucune execution reelle."
    return "Evenement de simulation locale; aucune execution reelle."


def _explain_decision(decision: Any) -> str:
    if decision.reason == "EDGE_UNPROVEN_PROTECTION_MODE":
        return "Protection du capital: aucun edge frais et mesurable, donc aucune position virtuelle n'est ouverte."
    return f"Decision de simulation: {decision.reason}. {decision.message}"


def _render_engine_markdown(engine: SimulationEngine, rows: list[dict[str, Any]]) -> str:
    forbidden_exchange_path = "/" + "exchange"
    lines = [
        "# HyperSmart CLI simulation - logs a envoyer",
        "",
        f"Simulation sans argent. Aucun {forbidden_exchange_path}, aucune signature, aucun ordre reel.",
        "",
        f"- Capital de depart: {engine.portfolio.starting_equity:.2f}",
        f"- Equity actuelle: {engine.portfolio.current_equity():.6f}",
        f"- PnL realise brut: {engine.portfolio.realized_pnl:.6f}",
        f"- Frais totaux: {engine.portfolio.total_fees:.6f}",
        f"- Positions ouvertes: {len(engine.portfolio.positions)}",
        f"- Drawdown max: {engine.portfolio.max_drawdown():.6f}",
        "",
        "## Evenements",
    ]
    if not rows:
        lines.append("- Aucun evenement de simulation.")
    for row in rows:
        timestamp = row.get("timestamp_ms") or "N/A"
        lines.append(
            f"- {timestamp} | {row['coin']} {row['side']} {row['action']} | "
            f"notional={row['notional']:.6f} | fee={row['fee']:.6f} | pnl={row['realized_pnl']:.6f} | {row['plain_english']}"
        )
    return "\n".join(lines) + "\n"
