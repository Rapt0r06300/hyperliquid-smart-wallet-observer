"""Portable reproducer for the physically frozen Copy-Vault V21 TRAIN policy.

Historical research helper only.  It replays the immutable frozen parameters and
never tunes, submits orders, or depends on a user PC path.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting import copy_vault_executable as cv  # noqa: E402
from hl_observer.backtesting.copy_vault_v21_frozen import (  # noqa: E402
    evaluate_frozen_v21_segment,
)

FREEZE_PATH = ROOT / "runtime" / "codex_research" / "COPY_V21_PHYSICAL_FREEZE.json"
OUTPUT = (
    ROOT
    / "runtime"
    / "reports"
    / "economic_campaigns"
    / "research_vnext"
    / "copy_vault_v21_frozen_train_reproduction.json"
)


def _load_pipeline():
    path = ROOT / "tools" / "pipeline_copie_reel.py"
    spec = importlib.util.spec_from_file_location("copy_v21_frozen_pipeline", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load copy pipeline: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if not FREEZE_PATH.is_file():
        raise RuntimeError(f"physical freeze missing: {FREEZE_PATH}")
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    pipeline = _load_pipeline()
    entries, entries_audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(ROOT)
    metaorders, metaorder_audit = cv.cluster_metaorders(entries)
    books, books_audit = cv.load_observed_books(
        ROOT,
        coins={str(row["coin"]) for row in metaorders},
    )
    causal_metaorders, causal_books, protocol_audit = cv.select_causal_protocol_inputs(
        metaorders, books
    )
    continuous_books = {
        coin: sorted(
            [
                dict(row)
                for row in rows
                if row.get("causal_observation") is True
                and not row.get("checkpoint_id")
                and str(row.get("source") or "") == "HYPERLIQUID_L2_WS"
            ],
            key=lambda row: int(row["ts_ms"]),
        )
        for coin, rows in causal_books.items()
    }
    continuous_books = {coin: rows for coin, rows in continuous_books.items() if rows}
    report = evaluate_frozen_v21_segment(
        causal_metaorders,
        continuous_books,
        freeze,
        segment="train",
    )
    report["input_audit"] = {
        "entries": entries_audit,
        "metaorders": metaorder_audit,
        "books": books_audit,
        "protocol": protocol_audit,
        "continuous_causal_rows": sum(len(rows) for rows in continuous_books.values()),
    }
    report["reproduction_only"] = True
    report["paper_read_only"] = True
    report["real_execution"] = False
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "status": report.get("status"),
                "sample_count": (report.get("statistics") or {}).get("sample_count"),
                "daily_mean_net_pnl_usd": report.get("daily_mean_net_pnl_usd"),
                "paper_read_only": True,
                "real_execution": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
