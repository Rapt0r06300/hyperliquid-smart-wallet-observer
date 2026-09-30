from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.experimental import moteur_paper as paper
from hl_observer.ui.status_routes import _mark_to_market_positions


ROOT = Path(__file__).resolve().parents[1]


def _marked(direction: str, mark: float) -> dict:
    coin = "HYPE"
    return _mark_to_market_positions(
        [
            {
                "position_id": f"paper:{coin}:{direction}",
                "coin": coin,
                "direction": direction,
                "size": 1.0,
                "entry_price": 100.0,
                "entry_costs": 0.0,
                "exit_fee_bps": 0.0,
                "exit_slippage_bps": 0.0,
            }
        ],
        starting_equity_usdt=1_000.0,
        realized_pnl_usdc=0.0,
        market_marks={
            "prices": {f"{coin}|{direction}": mark},
            "sources": {
                f"{coin}|{direction}": "LOCAL_BBO_BID" if direction == "LONG" else "LOCAL_BBO_ASK"
            },
            "timestamps": {f"{coin}|{direction}": 2_000},
            "latest_exchange_ts": 2_000,
            "read_status": "OK",
        },
        current_ms=2_000,
    )


def test_directional_executable_marks_move_pnl_monotonically() -> None:
    long_1, long_2 = _marked("LONG", 101.0), _marked("LONG", 102.0)
    short_1, short_2 = _marked("SHORT", 99.0), _marked("SHORT", 98.0)

    assert long_2["unrealized_pnl_usdc"] > long_1["unrealized_pnl_usdc"] > 0
    assert short_2["unrealized_pnl_usdc"] > short_1["unrealized_pnl_usdc"] > 0
    assert long_1["positions"][0]["mark_source"] == "LOCAL_BBO_BID"
    assert short_1["positions"][0]["mark_source"] == "LOCAL_BBO_ASK"
    assert long_2["current_equity_usdt"] == pytest.approx(1_000.0 + long_2["unrealized_pnl_usdc"])


def test_close_is_idempotent_and_realized_once(tmp_path: Path) -> None:
    store = {"mode": paper.MODE, "ouvertes": {}}
    signal = paper.Signal(
        moteur="copy_vault",
        coin="HYPE",
        sens=1,
        type_pnl="directional",
        notional_usd=50.0,
        prix_entree=100.0,
        cout_entree_bps=1.0,
        edge_estime_bps=20.0,
        ts_signal_ms=1_000.0,
        pnl_attendu_usd=1.0,
    )
    position = paper.ouvrir(signal, store, tmp_path, now_ms=1_000.0)

    first = paper.sortir(
        position,
        store,
        tmp_path,
        prix_sortie=101.0,
        cout_sortie_bps=1.0,
        raison="TEST_CLOSE",
        now_ms=2_000.0,
    )
    second = paper.sortir(
        position,
        store,
        tmp_path,
        prix_sortie=101.0,
        cout_sortie_bps=1.0,
        raison="TEST_CLOSE_DUPLICATE",
        now_ms=2_001.0,
    )
    rows = [json.loads(line) for line in (tmp_path / paper.LEDGER_RELPATH).read_text(encoding="utf-8").splitlines()]

    assert first["realized_usd"] > 0
    assert second["ignored"] is True
    assert [row["kind"] for row in rows].count("CLOSE") == 1
    assert rows[0]["kind"] == "OPEN"
    assert rows[0]["intent_id"] and rows[0]["order_id"] and rows[0]["fill_id"]
    assert rows[0]["position_id"] == position["position_id"]
    assert all(row["real_execution"] is False for row in rows)


def test_strict_roi_gate_stays_strict_while_experimental_collects() -> None:
    store = {"mode": paper.MODE, "ouvertes": {}}
    signal = paper.Signal(
        moteur="copy_vault",
        coin="HYPE",
        sens=1,
        type_pnl="directional",
        notional_usd=50.0,
        prix_entree=100.0,
        cout_entree_bps=1.0,
        edge_estime_bps=20.0,
        ts_signal_ms=10_000.0,
        roi_annuel_pct=None,
        pnl_attendu_usd=1.0,
    )

    assert paper.admettre(signal, store, now_ms=10_000.0, mode="strict") == (False, "ROI_NON_MESURABLE")
    assert paper.admettre(signal, store, now_ms=10_000.0, mode="experimental_paper") == (True, None)


def test_status_dashboard_and_runner_share_the_p0_truth_contract() -> None:
    dashboard = (ROOT / "src/hl_observer/ui/dashboard_v2.py").read_text(encoding="utf-8")
    status = (ROOT / "src/hl_observer/ui/status_routes.py").read_text(encoding="utf-8")
    runner = (ROOT / "src/hl_observer/experimental/runner.py").read_text(encoding="utf-8")
    signals = (ROOT / "src/hl_observer/experimental/signaux.py").read_text(encoding="utf-8")

    assert "fetch('/api/simulation/status')" in dashboard
    assert "upsertStatusGraphPoint" in dashboard and "latest_graph_point" in dashboard
    assert "JOURNAL PAPER CANONIQUE" in dashboard
    assert "_mgLiveDelta" not in dashboard
    assert "d+=' L'" in dashboard
    assert "setInterval(majAccruLive,250)" in dashboard
    assert '"real_execution": False' in status
    assert '"ledger_recent_events"' in status and '"lanes"' in status
    assert 'directional_mark_key = f"{coin}|{direction}"' in status
    for key in ("events", "fresh", "candidates", "l2", "liquidity", "edge", "consensus", "PaperIntent", "PaperFill", "POSITION"):
        assert f'"{key}"' in runner
    assert "decision_latency_ms" in runner and "top_no_trade" in runner
    assert "experimental_entry_from_add=True" in runner
    assert "experimental_calibration=True" in runner
    assert "raw_gap_bps" in signals and "net_edge_bps" in signals
