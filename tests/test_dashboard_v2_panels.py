"""UI-2..6: panneaux modes + wiring + fraîcheur, et vérité UI=ledger canonique."""

from __future__ import annotations

from hl_observer.ui.dashboard_v2 import CANONICAL_STATUS_FIELDS, create_dashboard_v2_router


def _page() -> str:
    router = create_dashboard_v2_router()
    endpoint = next(r.endpoint for r in router.routes if r.path == "/v2")
    return endpoint().body.decode("utf-8")


def test_page_has_all_panels():
    html = _page()
    assert "METAGRAPHE" in html          # metagraphe
    assert "SNIPER" in html and "GRINDER" in html and "FUNDING" in html  # UI-5 modes
    assert "WIRING" in html              # UI-6 wiring map
    assert "réconciliation" in html      # santé ledger
    assert "marks" in html               # UI-3 fraîcheur


def test_ui4_truth_every_field_comes_from_canonical_status():
    html = _page()
    # la page interroge le status canonique et lit ses champs (pas de valeur en dur)
    assert "/api/simulation/status" in html
    for field in ("net_pnl_usdt", "equity_usdt", "positions", "fusion_runtime", "paper_ledger", "funding_arb"):
        assert field in html, f"champ canonique absent de l'UI: {field}"
    # le contrat de champs est exporté pour vérification croisée
    assert "positions" in CANONICAL_STATUS_FIELDS and "fusion_runtime" in CANONICAL_STATUS_FIELDS


def test_read_only_no_action_endpoint():
    router = create_dashboard_v2_router()
    for r in router.routes:
        assert getattr(r, "methods", set()) == {"GET"}  # aucune écriture exposée
