"""Autopsie read-only de la couverture causale Lead-Lag sur un workspace réel.

Ce diagnostic n'est pas une stratégie et ne peut pas promouvoir un PnL. Il
rejoue uniquement les chocs Binance ETH >=8 bps afin de mesurer si un carnet
Hyperliquid causal était observable <=750 ms, et distingue les absences
réellement accompagnées d'une preuve de gap/reconnexion des simples absences de
données. Le seuil économique V3 reste 20 bps.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.lead_lag_causal_coverage import (  # noqa: E402
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    ECONOMIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage,
)
from hl_observer.backtesting.lead_lag_queue_replay import detect_rolling_shocks  # noqa: E402
from hl_observer.backtesting.lead_lag_source_alignment import (  # noqa: E402
    load_aligned_binance_trade_tape,
    select_aligned_bbo_sources,
)
from hl_observer.datasets.source_discovery import (  # noqa: E402
    is_dataset_workspace,
    load_family_source_paths,
)
from hl_observer.simulation.lead_lag_l2_history import (  # noqa: E402
    load_market_microstructure_event_windows,
)

REPORT_RELATIVE = Path("runtime/reports/economic_campaigns/LEAD_LAG_CAUSAL_COVERAGE_DIAGNOSTIC.json")
REPORT_MD_RELATIVE = Path("runtime/reports/economic_campaigns/LEAD_LAG_CAUSAL_COVERAGE_DIAGNOSTIC.md")


def _enabled(name: str) -> bool:
    return os.environ.get(name, "0").strip().casefold() in {"1", "true", "yes", "on", "oui"}


def _assert_read_only() -> None:
    active = [
        name
        for name in (
            "HL_ENABLE_MAINNET_EXECUTION",
            "HL_ENABLE_TESTNET_EXECUTION",
            "HYPERSMART_ENABLE_REAL_ORDERS",
            "ENABLE_REAL_ORDERS",
        )
        if _enabled(name)
    ]
    if active:
        raise RuntimeError("diagnostic Lead-Lag refuse toute exécution réelle: " + ", ".join(active))


def _render_markdown(payload: dict[str, Any]) -> str:
    counts = payload.get("classification_counts") or {}
    lines = [
        "# Lead-Lag — autopsie couverture causale",
        "",
        f"- Diagnostic uniquement : `{payload.get('diagnostic_only')}`",
        f"- Seuil diagnostic : `{payload.get('diagnostic_shock_threshold_bps')} bps`",
        f"- Seuil économique inchangé : `{payload.get('economic_shock_threshold_bps_unchanged')} bps`",
        f"- Délai carnet exécutable maximum : `{payload.get('max_executable_book_delay_ms')} ms`",
        f"- Événements diagnostiqués : `{payload.get('event_count')}`",
        f"- Événements conclusifs : `{payload.get('conclusive_event_count')}`",
        f"- Carnets exécutables <= limite : `{payload.get('executable_event_count')}`",
        f"- Délai premier carnet p50 : `{payload.get('first_book_delay_p50_ms')}` ms",
        f"- Délai premier carnet p95 : `{payload.get('first_book_delay_p95_ms')}` ms",
        "",
        "## Classifications",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- `{key}` : **{counts[key]}**")
    lines.extend(
        [
            "",
            "## Événements",
            "",
            "| trigger_ms | choc_bps | classification | premier carnet ms | délai ms | gap explicite |",
            "|---:|---:|---|---:|---:|---|",
        ]
    )
    for event in payload.get("events") or []:
        lines.append(
            "| {trigger} | {bps} | {classification} | {book} | {delay} | {gap} |".format(
                trigger=event.get("trigger_ts_ms"),
                bps=event.get("lead_shock_bps"),
                classification=event.get("classification"),
                book=event.get("first_causal_book_ts_ms"),
                delay=event.get("first_causal_book_delay_ms"),
                gap=event.get("explicit_gap_evidence"),
            )
        )
    lines.extend(
        [
            "",
            "> Règle : une absence de carnet ne prouve jamais à elle seule un gap collecteur.",
            "> Seuls les indicateurs enregistrés gap/reconnect/sequence peuvent classer un gap explicite.",
            "",
        ]
    )
    return "\n".join(lines)


def run_diagnostic(root: Path) -> dict[str, Any]:
    _assert_read_only()
    root = root.resolve()
    candidates = load_family_source_paths(root, "lead_lag") if is_dataset_workspace(root) else None
    aligned_sources, alignment = select_aligned_bbo_sources(root, candidates=candidates)
    lead_tape, tape_meta = load_aligned_binance_trade_tape(root, aligned_sources)
    trades = (lead_tape.get("ETH") or {}).get("TRADE") or ()
    diagnostic_shocks = detect_rolling_shocks(
        trades,
        threshold_bps=DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    )
    economic_shocks = detect_rolling_shocks(
        trades,
        threshold_bps=ECONOMIC_SHOCK_THRESHOLD_BPS,
    )
    l2_history, _public_trades, microstructure = load_market_microstructure_event_windows(
        root,
        [int(row["trigger_ts_ms"]) for row in diagnostic_shocks],
    )
    payload = diagnose_causal_book_coverage(
        diagnostic_shocks,
        l2_history,
        microstructure_meta=microstructure,
        diagnostic_threshold_bps=DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
        economic_threshold_bps=ECONOMIC_SHOCK_THRESHOLD_BPS,
    )
    payload["aligned_source_meta"] = alignment
    payload["aligned_lead_tape_meta"] = tape_meta
    payload["microstructure_meta"] = microstructure
    payload["economic_20bps_shock_count"] = len(economic_shocks)
    payload["diagnostic_8bps_shock_count"] = len(diagnostic_shocks)
    payload["purpose"] = "SOURCE_COVERAGE_AUTOPSY_NOT_ECONOMIC_SELECTION"

    report = root / REPORT_RELATIVE
    report.parent.mkdir(parents=True, exist_ok=True)
    temporary = report.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, report)
    markdown = root / REPORT_MD_RELATIVE
    markdown.write_text(_render_markdown(payload), encoding="utf-8", newline="\n")
    payload["report_path"] = str(report)
    payload["markdown_path"] = str(markdown)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    try:
        payload = run_diagnostic(Path(args.root))
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"LEAD_LAG_CAUSAL_DIAGNOSTIC_NO_GO: {type(exc).__name__}: {exc}", flush=True)
        return 2
    print(
        "LEAD_LAG_CAUSAL_DIAGNOSTIC_OK "
        f"events={payload['event_count']} executable={payload['executable_event_count']} "
        f"p50_ms={payload['first_book_delay_p50_ms']} p95_ms={payload['first_book_delay_p95_ms']} "
        f"classes={json.dumps(payload['classification_counts'], sort_keys=True)}",
        flush=True,
    )
    print(f"report={payload['report_path']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
