"""Le panneau CARRY du dashboard v2 : endpoint /v2/carry (lecture seule) + presence dans la page."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hl_observer.ui.dashboard_v2 import create_dashboard_v2_router


def _client():
    app = FastAPI()
    app.include_router(create_dashboard_v2_router())
    return TestClient(app)


def test_endpoint_v2_carry_forme_et_read_only():
    d = _client().get("/v2/carry").json()
    for k in ("positions_ouvertes", "realized_net_pnl_usdc", "funding_accru_usdt",
              "opens", "closes", "positions", "viables"):
        assert k in d, k
    assert d["read_only"] is True and d["paper_only"] is True and d["real_execution"] is False
    assert isinstance(d["positions"], list) and isinstance(d["viables"], list)


def test_la_page_v2_contient_le_panneau_carry():
    txt = _client().get("/v2").text
    assert "CARRY DELTA-NEUTRE" in txt          # le titre du panneau
    assert "/v2/carry" in txt                    # le JS poll bien l'endpoint dedie
    assert "carrytb" in txt and "carry-real" in txt


# ------------------------------------------------------------------ allocation & renfort (21/07)

def test_endpoint_carry_expose_la_marge_cible_et_l_allocation(tmp_path, monkeypatch):
    """L'écran doit DIRE où va le capital : sans ça, l'inversion −0,596 pouvait durer des
    jours sans que personne la voie (c'est exactement ce qui s'est passé)."""
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from hl_observer.ui import dashboard_v2 as dv2

    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "carry_paper_positions.json").write_text(json.dumps({
        "mode": "LIVE", "ouvertes": {"BTC": {
            "coin": "BTC", "mode": "LIVE", "marge_usdt": 25.0, "notional_usdt": 125.0,
            "levier": 5.0, "entry_ts_ms": 1, "last_accrual_ts_ms": 1, "renforts": 2,
            "cout_entree_bps": 10.0, "funding_accrued_usdt": 0.03}}}), encoding="utf-8")
    (d / "carry_allocation.json").write_text(json.dumps({
        "meilleur": "BTC", "coins_finances": 1, "capital_alloue_usd": 240.36,
        "rendement_pondere_bps_j": 1.83, "rendement_part_egale_bps_j": 1.61,
        "gain_vs_part_egale_pct": 13.65, "marges_usd": {"BTC": 240.36}}), encoding="utf-8")

    monkeypatch.setattr(dv2, "__file__", str(tmp_path / "src" / "hl_observer" / "ui" / "x.py"))
    app = FastAPI()
    app.include_router(dv2.create_dashboard_v2_router())
    r = TestClient(app).get("/v2/carry").json()

    pos = {p["coin"]: p for p in r.get("positions", [])}
    assert pos["BTC"]["marge_cible_usdt"] == 240.36     # la cible est DITE
    assert pos["BTC"]["renforts"] == 2                  # les renforts sont VISIBLES
    assert r["allocation"]["gain_vs_part_egale_pct"] == 13.65
    assert r["real_execution"] is False


def test_le_panneau_carry_contient_la_ligne_allocation():
    """`mention ≠ porte` version écran : l'ancre HTML doit exister, sinon le JS écrit
    dans le vide et personne ne voit jamais l'allocation."""
    from pathlib import Path as _P

    from hl_observer.ui import dashboard_v2 as dv2
    src = _P(dv2.__file__).read_text(encoding="utf-8")
    assert 'id="carry-alloc"' in src
    assert "getElementById('carry-alloc')" in src
    assert "marge_cible_usdt" in src
