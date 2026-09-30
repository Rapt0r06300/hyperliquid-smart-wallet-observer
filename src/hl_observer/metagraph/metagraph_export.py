from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from hl_observer.simulation.decision_replay_analyzer import load_decision_events


@dataclass(frozen=True, slots=True)
class MetagraphExport:
    json_path: Path
    csv_path: Path
    points: int
    final_pnl_usdc: float
    read_only: bool = True


def export_metagraph_from_logs(log_dir: Path, *, output_dir: Path = Path("data/reports")) -> MetagraphExport:
    events = sorted(
        load_decision_events(log_dir),
        key=lambda event: event.timestamp_ms or 0,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "metagraph_latest.json"
    csv_path = output_dir / "metagraph_latest.csv"
    equity = 0.0
    points: list[dict] = []
    for index, event in enumerate(events):
        pnl = float(event.estimated_net_pnl_usdc or 0.0)
        fee = float(event.fee_cost_usdc or 0.0)
        equity += pnl
        points.append(
            {
                "index": index,
                "timestamp_ms": event.timestamp_ms,
                "wallet_address": event.wallet_address,
                "coin": event.coin,
                "bot_decision": event.bot_decision,
                "status": event.status,
                "reason": event.reason,
                "event_pnl_usdc": round(pnl, 8),
                "fee_usdc": round(fee, 8),
                "cumulative_pnl_usdc": round(equity, 8),
                "edge_remaining_bps": event.edge_remaining_bps,
                "copy_degradation_bps": event.copy_degradation_bps,
                "signal_age_ms": event.signal_age_ms,
            }
        )
    json_path.write_text(
        json.dumps(
            {
                "source_dir": str(log_dir),
                "points": points,
                "final_pnl_usdc": round(equity, 8),
                "read_only": True,
                "execution": "forbidden",
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(points[0].keys()) if points else ["index", "cumulative_pnl_usdc"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(points)
    return MetagraphExport(
        json_path=json_path,
        csv_path=csv_path,
        points=len(points),
        final_pnl_usdc=round(equity, 8),
    )


def format_metagraph_export(result: MetagraphExport) -> str:
    return "\n".join(
        [
            "metagraph_export=local_simulation_only",
            f"json={result.json_path}",
            f"csv={result.csv_path}",
            f"points={result.points}",
            f"final_pnl_usdc={result.final_pnl_usdc:.6f}",
            f"read_only={str(result.read_only).lower()}",
        ]
    )

