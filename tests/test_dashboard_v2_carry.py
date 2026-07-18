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
