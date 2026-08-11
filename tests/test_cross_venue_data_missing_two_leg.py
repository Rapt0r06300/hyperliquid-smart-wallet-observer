from __future__ import annotations

from hl_observer.experimental import execution_paper as EP
from hl_observer.experimental import runner


def _position(*, with_legs: bool = True) -> dict:
    meta = {"gap_entree_bps": 12.0}
    if with_legs:
        meta["jambes"] = {
            "hl": {"prix_exec": 100.0, "frais_bps": 4.5, "slippage_bps": 1.0},
            "bin": {"prix_exec": 101.0, "frais_bps": 4.5, "slippage_bps": 1.0},
        }
    return {
        "position_id": "cv-1",
        "moteur": "cross_venue",
        "coin": "BTC",
        "sens": 1,
        "type_pnl": "dislocation",
        "notional_usd": 100.0,
        "prix_entree": 100.0,
        "ts_ouverture_ms": 1_000.0,
        "ts_derniere_donnee_ms": 1_000.0,
        "frais_bps": 9.0,
        "spread_bps": 2.0,
        "meta": meta,
    }


def test_data_missing_stress_is_exactly_two_leg_and_never_fabricates_convergence() -> None:
    pos = _position()
    legs = runner._jambes_sortie_dislocation(pos, None, stress_slippage_bps=25.0)

    assert legs is not None and len(legs) == 2
    assert {leg["venue"] for leg in legs} == {"HL", "BIN"}
    assert all(leg["entry_px"] == leg["exit_px"] for leg in legs)
    assert all(leg["exit_slippage_bps"] == 26.0 for leg in legs)

    result = EP.pnl_deux_jambes(legs)
    # Par jambe: 4.5 bps entree + 4.5 sortie + 1 entree + 26 sortie = 36 bps.
    # Deux jambes de 100 USD => -0.72 USD, sans aucun gain de convergence invente.
    assert result["n_jambes"] == 2
    assert result["realized_usd"] == -0.72
    assert result["round_trip_cost_usd"] == 0.72


def test_missing_entry_legs_returns_none_instead_of_aggregate_close() -> None:
    assert runner._jambes_sortie_dislocation(
        _position(with_legs=False), None, stress_slippage_bps=25.0
    ) is None


def test_data_missing_timeout_never_calls_generic_sortir(monkeypatch, tmp_path) -> None:
    pos = _position()
    store = {"ouvertes": {pos["position_id"]: pos}}
    now_ms = 300_000.0

    import hl_observer.experimental.carry_deux_jambes as cdj

    monkeypatch.setattr(cdj, "carnet_par_coin", lambda _root: {})
    monkeypatch.setattr(runner, "_marks_cross_venue", lambda _root: {})

    def forbidden(*_args, **_kwargs):
        raise AssertionError("MP.sortir aggregate must never close a dislocation")

    captured: dict = {}

    def two_leg(_pos, _store, _root, *, jambes, raison, now_ms):
        captured["jambes"] = jambes
        captured["raison"] = raison
        return {"raison": raison, "n_jambes": len(jambes)}

    monkeypatch.setattr(runner.MP, "sortir", forbidden)
    monkeypatch.setattr(runner.MP, "sortir_deux_jambes", two_leg)

    closed = runner._gerer_sorties(store, tmp_path, now_ms=now_ms)
    assert closed == [{"raison": "DATA_MISSING_TIMEOUT_TWO_LEG_STRESS", "n_jambes": 2}]
    assert len(captured["jambes"]) == 2


def test_unreconciled_entry_legs_are_marked_unliquidatable(monkeypatch, tmp_path) -> None:
    pos = _position(with_legs=False)
    store = {"ouvertes": {pos["position_id"]: pos}}

    import hl_observer.experimental.carry_deux_jambes as cdj

    monkeypatch.setattr(cdj, "carnet_par_coin", lambda _root: {})
    monkeypatch.setattr(runner, "_marks_cross_venue", lambda _root: {})
    monkeypatch.setattr(
        runner.MP,
        "sortir",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("aggregate close forbidden")),
    )

    closed = runner._gerer_sorties(store, tmp_path, now_ms=300_000.0)
    assert closed == []
    assert pos["liquidation_status"] == "UNLIQUIDATABLE_DATA_MISSING"
    assert "ENTRY_LEGS_UNAVAILABLE" in pos["liquidation_reason"]
    assert pos["position_id"] in store["ouvertes"]
