"""Metagraphe parfait: endpoint equity_history réel + page qui le consomme."""

from __future__ import annotations

from types import SimpleNamespace

from hl_observer.ui.dashboard_v2 import create_dashboard_v2_router


def _endpoint(name):
    router = create_dashboard_v2_router()
    return next(r.endpoint for r in router.routes if r.path == name)


def test_page_uses_real_history_endpoint_and_smoothing():
    html = _endpoint("/v2")().body.decode("utf-8")
    assert "/v2/equity_history" in html          # metagraphe branché sur la vraie courbe
    assert "smoothPath" in html                   # courbe lissée (Catmull-Rom -> Bézier)
    assert "base = equity départ" in html         # ligne de base profit/perte
    assert "EQUITY //" in html   # panneau courbe (ex-"METAGRAPHE", renomme a la refonte /v2)


def test_metagraph_ne_projette_jamais_un_pnl_cote_navigateur():
    """Le navigateur trace les mesures serveur/ledger, sans extrapoler entre deux polls."""
    html = _endpoint("/v2")().body.decode("utf-8")

    assert "var nr=pts.length;" in html
    assert "var solide=smoothPath(xy);" in html
    assert "nr<pts.length" not in html
    assert "Aucune extrapolation client" in html


def _isolate_persisted_store(monkeypatch):
    """L'endpoint privilegie l'historique PERSISTE (survit a la fermeture du navigateur).
    En test, ce store lisait les VRAIES donnees runtime -> le test n'etait pas isole (600 points
    au lieu de 0). On neutralise le store pour tester la lecture de l'etat en memoire."""
    monkeypatch.setattr(
        "hl_observer.runtime.equity_history_store.read_equity_points",
        lambda max=600: [],
    )
    # 19/07 — MÊME PIÈGE, DEUXIÈME FOIS. La courbe d'equity inclut désormais le net CARRY (elle
    # affichait 1 000,00 plat pendant que le bandeau disait -5,00 : deux vérités pour un seul
    # PnL). Sans cette isolation, le vrai PnL carry du runtime entrait dans le test et le
    # décalait. Un test qui lit l'état live ne teste pas, il constate.
    monkeypatch.setattr("hl_observer.ui.dashboard_v2.net_carry_courant", lambda root=None: 0.0)


def _req(root=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        ui_state=None, project_root=root)))


def _appel(root, monkeypatch):
    import json
    _isolate_persisted_store(monkeypatch)
    ep = _endpoint("/v2/equity_history")
    return json.loads(ep(_req(root), max=600).body.decode("utf-8"))


# 🔴 21/07 — CES DEUX TESTS ONT ÉTÉ RÉÉCRITS, PAS « RÉPARÉS ».
# Ils vérifiaient que l'endpoint sert `app.state.ui_state.simulation_equity_history`, c'est-à-dire
# l'historique de la pile COPY. C'est précisément ce contrat qui produisait le métagraphe éclaté :
# cette pile est éteinte depuis le 11/07 et ses 600 points valent tous 1 000,00 $ / pnl 0,0, si
# bien que la courbe était une ligne morte prolongée d'une falaise. La source est désormais le
# LEDGER. L'intention d'origine — « l'endpoint sert une vraie courbe » et « un état vide répond
# honnêtement » — est conservée telle quelle ; seule la source de vérité change.

def test_equity_history_sert_la_courbe_du_ledger(tmp_path, monkeypatch):
    import json as _json
    from hl_observer.funding.carry_positions_store import LEDGER_RELPATH
    p = tmp_path / LEDGER_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(_json.dumps(l) for l in [
        {"kind": "CLOSE", "mode": "LIVE", "ts_ms": 1000, "realized_net_pnl_usdc": -2.0,
         "coin": "HYPE", "strategie": "arbitrage"},
        {"kind": "CLOSE", "mode": "LIVE", "ts_ms": 2000, "realized_net_pnl_usdc": +0.5,
         "coin": "ZEC", "strategie": "arbitrage"},
    ]) + "\n", encoding="utf-8")
    payload = _appel(tmp_path, monkeypatch)
    assert payload["count"] == 4                  # départ + 2 événements + maintenant
    assert payload["evenements"] == 2
    assert payload["read_only"] is True and payload["real_execution"] is False
    eq = [pt["equity"] for pt in payload["points"]]
    assert eq[:3] == [1000.0, 998.0, 998.5]
    assert payload["amplitude_usd"] > 0, "la courbe doit BOUGER quand des trades se ferment"
    assert payload["sources"], "la courbe doit pouvoir énumérer ce qu'elle contient"


def test_equity_history_sur_un_projet_vide_est_honnete(tmp_path, monkeypatch):
    """Aucune donnée -> une ligne plate DÉCLARÉE. Pas de courbe inventée pour meubler."""
    payload = _appel(tmp_path, monkeypatch)
    assert payload["plate"] is True and payload["evenements"] == 0
    assert payload["amplitude_usd"] == 0.0
    assert payload["read_only"] is True


def test_le_grand_chiffre_lit_le_realise_TOTAL_pas_celui_de_la_session():
    """🔴 21/07 — LE BANDEAU AFFICHAIT UN GAIN VERT PENDANT UNE PERTE.

    Le grand chiffre valait `réalisé SESSION + funding TOUTE LA VIE`. Mesuré ce jour-là :
    0,00 (0 close depuis le redémarrage) + 0,362469 = **+0,36 en vert**, pendant que le ledger
    disait **−5,64** et que la courbe descendait en rouge juste en dessous. Ce n'était même pas
    « le PnL de la session » : numérateur et dénominateur venaient de deux fenêtres différentes,
    donc le nombre ne mesurait rien.

    Ce test verrouille la formule côté page : le net qui alimente le grand chiffre doit partir
    du réalisé TOTAL, celui-là même que la courbe cumule.
    """
    html = _endpoint("/v2")().body.decode("utf-8")
    # 06/08 — decision Flo 23/07 : la courbe cumule le LIVRE LIVE (carry retire exclu) ; le
    # grand chiffre part du meme livre, sinon il contredit la courbe.
    assert "window._carryNet=realLive+fundingRegle;" in html, (
        "le grand chiffre doit partir du realise du LIVRE LIVE — sinon il contredit la courbe")
    assert "window._carryNet=realSess+" not in html, (
        "la chimere session+all-time ne doit jamais revenir")
    # la fenêtre session reste visible, mais ETIQUETEE et a cote
    assert "_carryNetSess" in html and "session " in html
    # et le libelle sous le grand chiffre doit dire de quelle fenetre il parle
    assert "depuis le début" in html


def test_l_axe_du_temps_ne_peut_pas_cacher_les_jours():
    """Une série de 73 h s'affichait « 17:12 → 18:36 » : on lisait une chute de 84 minutes là
    où il y avait 3 jours. Une échelle de temps qui perd son unité est un mensonge."""
    html = _endpoint("/v2")().body.decode("utf-8")
    assert "function horoAxe(" in html and "spanMs>=86400000" in html
    assert "horoAxe(t0,ts)" in html and "horoAxe(t1,ts)" in html


def test_le_dernier_point_de_l_endpoint_vaut_le_pnl_stable(tmp_path, monkeypatch):
    """L'INVARIANT qui interdit au dashboard d'afficher deux vérités : la courbe et le grand
    chiffre lisent la même couche (`réalisé + funding RÉGLÉ`)."""
    import json as _json
    from hl_observer.funding.carry_positions_store import LEDGER_RELPATH
    p = tmp_path / LEDGER_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps({"kind": "CLOSE", "mode": "LIVE", "ts_ms": 1000,
                              "realized_net_pnl_usdc": -6.0, "coin": "BTC",
                              "strategie": "arbitrage"}) + "\n", encoding="utf-8")
    monkeypatch.setattr("hl_observer.funding.carry_positions_store.etat_carry",
                        lambda root=None: {"net_funding_settled": 0.35})
    payload = _appel(tmp_path, monkeypatch)
    assert payload["points"][-1]["pnl"] == -5.65
    assert payload["points"][-1]["equity"] == 994.35
