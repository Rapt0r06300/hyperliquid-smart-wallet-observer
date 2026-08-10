from __future__ import annotations

import json
from pathlib import Path

from hl_observer.experimental import moteur_paper as MP


def _signal(moteur: str, *, notional: float, coin: str = "ETH") -> MP.Signal:
    return MP.Signal(
        moteur=moteur,
        coin=coin,
        sens=1,
        type_pnl="dislocation" if moteur == "cross_venue" else "directional",
        notional_usd=notional,
        prix_entree=100.0,
        cout_entree_bps=5.0,
        edge_estime_bps=20.0,
        ts_signal_ms=1_000_000.0,
        pnl_attendu_usd=1.0,
    )


def test_cross_venue_open_records_per_leg_and_gross_exposure(tmp_path: Path) -> None:
    store = {"mode": MP.MODE, "ouvertes": {}}
    sig = _signal("cross_venue", notional=50.0)
    ok, reason = MP.admettre(sig, store, now_ms=1_000_100.0)
    assert ok is True and reason is None
    pos = MP.ouvrir(sig, store, tmp_path, now_ms=1_000_100.0)
    assert pos["per_leg_notional_usd"] == 50.0
    assert pos["gross_exposure_usd"] == 100.0
    assert MP.resume(tmp_path)["gross_exposure_open_usd"] == 100.0


def test_cross_venue_incoming_budget_counts_both_legs() -> None:
    store = {
        "mode": MP.MODE,
        "ouvertes": {
            "copy_vault:BTC": {"moteur": "copy_vault", "notional_usd": 920.0, "gross_exposure_usd": 920.0}
        },
    }
    sig = _signal("cross_venue", notional=50.0)
    ok, reason = MP.admettre(sig, store, now_ms=1_000_100.0)
    assert ok is False
    assert reason == "BUDGET_GLOBAL_DEPASSE"


def test_resume_separates_current_session_from_lifetime(tmp_path: Path, monkeypatch) -> None:
    sessions = tmp_path / "runtime" / "data" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "COURANTE.json").write_text(json.dumps({"run_id": "run-new"}), encoding="utf-8")
    ledger = tmp_path / MP.LEDGER_RELPATH
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        "\n".join([
            json.dumps({"kind": "CLOSE", "strategie": "lead_lag", "session_id": "run-old", "realized_net_pnl_usdc": 8.0}),
            json.dumps({"kind": "CLOSE", "strategie": "lead_lag", "session_id": "run-new", "realized_net_pnl_usdc": 2.0}),
            json.dumps({"kind": "REDUCE", "strategie": "copy_vault", "session_id": "run-new", "realized_net_pnl_usdc": -0.5}),
        ]) + "\n",
        encoding="utf-8",
    )
    summary = MP.resume(tmp_path)
    assert summary["session_id"] == "run-new"
    assert summary["realise_total_usd"] == 1.5
    assert summary["realise_session_usd"] == 1.5
    assert summary["realise_lifetime_usd"] == 9.5
    assert summary["par_moteur"]["lead_lag"]["realise_usd"] == 2.0
    assert summary["par_moteur"]["lead_lag"]["realise_lifetime_usd"] == 10.0


def test_new_ledger_rows_always_carry_scope(tmp_path: Path) -> None:
    sessions = tmp_path / "runtime" / "data" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "COURANTE.json").write_text(json.dumps({"run_id": "run-42"}), encoding="utf-8")
    store = {"mode": MP.MODE, "ouvertes": {}}
    MP.ouvrir(_signal("lead_lag", notional=50.0), store, tmp_path, now_ms=1_000_100.0)
    row = json.loads((tmp_path / MP.LEDGER_RELPATH).read_text(encoding="utf-8").splitlines()[0])
    assert row["session_id"] == "run-42"
    assert row["lane"] == "EXP"
    assert row["cohort"] == "EXPERIMENTAL"
    assert row["real_execution"] is False
