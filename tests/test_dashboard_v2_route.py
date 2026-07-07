"""Dashboard v2 (thème hacker): route read-only montée sans toucher routes.py."""

from __future__ import annotations

from hl_observer.ui.dashboard_v2 import create_dashboard_v2_router


def test_router_exposes_v2_get_only():
    router = create_dashboard_v2_router()
    paths = {r.path: getattr(r, "methods", set()) for r in router.routes}
    assert "/v2" in paths
    assert paths["/v2"] == {"GET"}  # read-only: aucune méthode d'action


def test_v2_page_is_html_and_read_only_and_wired_to_canonical_status():
    router = create_dashboard_v2_router()
    endpoint = next(r.endpoint for r in router.routes if r.path == "/v2")
    resp = endpoint()
    html = resp.body.decode("utf-8")
    assert "HYPERSMART" in html
    assert "/api/simulation/status" in html          # source = ledger canonique (UI-4)
    assert "read_only" in html
    # pas de contenu de démo en dur: le PnL vient du fetch, pas d'une valeur figée
    assert "métagraphe".upper() in html.upper() or "METAGRAPHE" in html
