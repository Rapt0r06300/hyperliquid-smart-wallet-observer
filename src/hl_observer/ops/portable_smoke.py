"""Hermetic smoke path for the extracted portable release.

The input payload is explicitly a ``SYNTHETIQUE`` endpoint fixture.  It is
processed by the production Hyperliquid fill normalizer, the canonical
``PaperLedger`` and the canonical session catalogue.  Nothing here is market
data and nothing can leave the local paper boundary.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Sequence

from hl_observer.models import DataQuality, SourceMeta
from hl_observer.normalization.fills import normalize_hyperliquid_fill
from hl_observer.ops import session_catalog as SC
from hl_observer.simulation.paper_ledger import PaperLedger

SCHEMA = "hypersmart.portable_smoke.v1"
WALLET_FIXTURE = "0x1111111111111111111111111111111111111111"


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _fixture_fills(timestamp_ms: int) -> list[dict[str, Any]]:
    return [
        {
            "coin": "BTC",
            "dir": "Open Long",
            "side": "B",
            "sz": "0.001",
            "px": "50000",
            "time": timestamp_ms,
            "startPosition": "0",
            "closedPnl": "0",
            "fee": "0.0225",
            "oid": 1,
            "tid": 1,
            "hash": "0xportableopen",
        },
        {
            "coin": "BTC",
            "dir": "Close Long",
            "side": "A",
            "sz": "0.001",
            "px": "50020",
            "time": timestamp_ms + 1000,
            "startPosition": "0.001",
            "closedPnl": "0.02",
            "fee": "0.022509",
            "oid": 2,
            "tid": 2,
            "hash": "0xportableclose",
        },
    ]


def executer_smoke_portable(
    root: str | Path,
    *,
    horloge: Callable[[], float] = time.time,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run one bounded offline lifecycle and return its evidence payload."""
    root = Path(root).resolve()
    now_s = float(horloge())
    now_ms = int(now_s * 1000)
    run_id = run_id or SC.nouveau_run_id("portable-smoke", horloge=lambda: now_s)
    catalogue = SC.CatalogueSession(root, run_id)
    catalogue.demarrer(
        contexte={
            "purpose": "portable_extracted_validation",
            "network": False,
            "real_execution": False,
        },
        data_origin=SC.ORIGINE_SYNTHETIQUE,
        horloge=lambda: now_s,
    )
    session_dir = catalogue.dossier
    raw_rows = _fixture_fills(now_ms)
    raw_path = session_dir / "endpoint_fixture.jsonl"
    _write_jsonl(raw_path, raw_rows)

    meta = SourceMeta(
        source_endpoint="offline://hyperliquid/info/userFills",
        source_ts=now_ms,
        local_received_ts=now_ms,
        latency_ms=0,
        raw_ref="portable-smoke-fixture",
        data_quality=DataQuality.OK,
        is_stale=False,
    )
    normalized = [
        normalize_hyperliquid_fill(row, wallet=WALLET_FIXTURE, meta=meta)
        for row in raw_rows
    ]
    if any(not result.usable for result in normalized):
        warnings = [warning for result in normalized for warning in result.warnings]
        raise RuntimeError("portable fill normalization failed: %s" % warnings)
    normalized_path = session_dir / "normalized_fills.jsonl"
    _write_jsonl(
        normalized_path,
        [result.fill.model_dump(mode="json") for result in normalized if result.fill is not None],
    )

    opened = normalized[0].fill
    closed = normalized[1].fill
    assert opened is not None and closed is not None
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id=run_id)
    ledger.open_position(
        coin=opened.coin,
        side="LONG",
        notional_usdc=opened.size * opened.price,
        quantity=opened.size,
        fill_price=opened.price,
        timestamp_ms=opened.time_ms,
        fee_bps=4.5,
        refs={"data_origin": "TEST_FIXTURE", "raw_ref": normalized[0].raw_ref},
    )
    ledger.mark_to_market({opened.coin: 50_010.0}, timestamp_ms=now_ms + 500)
    ledger.reduce_or_close(
        coin=closed.coin,
        side="LONG",
        quantity=closed.size,
        fill_price=closed.price,
        timestamp_ms=closed.time_ms,
        fee_bps=4.5,
        reason="portable_smoke_fixture_close",
        refs={"data_origin": "TEST_FIXTURE", "raw_ref": normalized[1].raw_ref},
    )
    ledger_path = session_dir / "paper_ledger.jsonl"
    _write_jsonl(ledger_path, [event.to_dict() for event in ledger.events])

    snapshot = ledger.snapshot()
    reconciliation = ledger.reconciliation()
    if not reconciliation.ok or snapshot["positions"]:
        raise RuntimeError("canonical paper ledger did not reconcile and close")

    sources = (
        ("fixture_endpoint", "endpoint_fixture.jsonl", len(raw_rows)),
        ("normalized_fills", "normalized_fills.jsonl", len(normalized)),
        ("paper_ledger", "paper_ledger.jsonl", len(ledger.events)),
    )
    for source, relative, count in sources:
        catalogue.enregistrer_source(
            SC.EntreeSource(
                source=source,
                source_id=source,
                venue="LOCAL_TEST_FIXTURE",
                canal="portable_smoke",
                chemin=relative,
                schema_version=SCHEMA,
                parser_version="hl_observer.normalization.fills",
                premier_ts_exchange=now_ms,
                dernier_ts_exchange=now_ms + 1000,
                premier_ts_reception=now_ms,
                dernier_ts_reception=now_ms + 1000,
                evenements_recus=count,
                evenements_valides=count,
                sante="VERTE",
                metadata={"data_origin": "SYNTHETIQUE", "real_execution": False},
            )
        )
    closure = catalogue.cloturer(writers_arretes=True, horloge=lambda: now_s + 2)
    if closure.get("statut") != SC.STATUT_COMPLETE:
        raise RuntimeError("portable smoke session did not close: %s" % closure)

    report = {
        "schema": SCHEMA,
        "ok": True,
        "run_id": run_id,
        "created_at_ms": now_ms,
        "data_origin": "SYNTHETIQUE",
        "presented_as_real_market_data": False,
        "network_used": False,
        "real_execution": False,
        "pipeline": [
            "hyperliquid_fill_normalizer",
            "paper_ledger_open_mark_close",
            "pnl_reconciliation",
            "session_catalog_complete",
        ],
        "normalized_fills": len(normalized),
        "paper_events": len(ledger.events),
        "ledger": snapshot,
        "ledger_reconciliation": asdict(reconciliation),
        "session_closure": closure,
    }
    report_dir = root / "runtime" / "reports" / "backtest_replay"
    report_json = report_dir / "RAPPORT_PORTABLE_SMOKE.json"
    report_md = report_dir / "RAPPORT_PORTABLE_SMOKE.md"
    _write_json(report_json, report)
    report_md.write_text(
        "# Portable smoke report\n\n"
        "- Status: **OK**\n"
        "- Data origin: `SYNTHETIQUE` (offline endpoint fixture)\n"
        "- Real execution: **false**\n"
        "- Ledger reconciled: **true**\n"
        "- Session: `%s` (`COMPLETE`)\n" % run_id,
        encoding="utf-8",
        newline="\n",
    )
    report["report_json"] = str(report_json)
    report["report_md"] = str(report_md)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded offline portable smoke")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = executer_smoke_portable(args.root)
    except Exception as exc:  # noqa: BLE001 - CLI reports a bounded failure
        print("PORTABLE_SMOKE_FAILED: %s" % exc)
        return 1
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("PORTABLE_SMOKE_OK %s" % result["report_json"])
    return 0


__all__ = ["SCHEMA", "executer_smoke_portable", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
