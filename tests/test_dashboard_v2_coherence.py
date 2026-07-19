"""REVUE UI DU 2026-07-19 — les deux défauts qui faisaient dire « l'UI est énormément buguée ».

DÉFAUT 1 — DEUX VÉRITÉS POUR UN SEUL PnL
    Le bandeau affichait -5,00 $ ; la COURBE d'equity restait plate à 1 000,00. L'historique
    d'equity ne connaissait que la pile copy — le PnL du carry n'y entrait jamais. Ce n'est pas
    un défaut cosmétique : CLAUDE.md exige que « dashboard, audit, logs convergent sur le même
    ledger ». Deux nombres pour une seule vérité, c'est la porte ouverte au chiffre qui ment.

DÉFAUT 2 — LES PANNES ÉTAIENT MUETTES
    Chaque `fetch` finissait par `.catch(function(){})`. Une erreur serveur était AVALÉE : le
    panneau restait figé sur « … » indéfiniment, sans un mot. Vu de l'extérieur, ça ressemble
    exactement à « l'UI bugue » — alors que l'UI, elle, savait très bien qu'elle était cassée.
    Un dashboard incapable de dire qu'il est en panne est pire qu'un dashboard en panne.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from hl_observer.ui import dashboard_v2
from hl_observer.ui.dashboard_v2 import create_dashboard_v2_router


def _endpoint(chemin: str):
    return next(r.endpoint for r in create_dashboard_v2_router().routes if r.path == chemin)


def _requete(points):
    etat = SimpleNamespace(simulation_equity_history=points)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ui_state=etat)))


def _appel(req, **kw):
    return json.loads(_endpoint("/v2/equity_history")(req, **kw).body.decode("utf-8"))


# ------------------------------------------------------------- défaut 1 : une seule vérité

def test_la_courbe_INCLUT_le_net_carry(monkeypatch):
    """LE BUG : bandeau -5,00 / courbe 1 000,00 plate. Le dernier point doit porter le carry."""
    monkeypatch.setattr("hl_observer.runtime.equity_history_store.read_equity_points",
                        lambda max=600: [])
    monkeypatch.setattr(dashboard_v2, "net_carry_courant", lambda root=None: -5.0)
    d = _appel(_requete([{"timestamp_ms": 1000, "current_equity_usdt": 1000.0,
                          "current_pnl_usdc": 0.0}]))
    assert d["inclut_carry"] is True
    assert d["points"][-1]["equity"] == 995.0
    assert d["points"][-1]["pnl"] == -5.0
    assert d["points"][-1]["carry_net_usdc"] == -5.0


def test_le_PASSE_n_est_PAS_reecrit(monkeypatch):
    """Le carry n'a pas d'historique horodaté. Rétro-projeter son net sur les points anciens
    fabriquerait une courbe — on n'écrit pas l'histoire qu'on n'a pas mesurée."""
    monkeypatch.setattr("hl_observer.runtime.equity_history_store.read_equity_points",
                        lambda max=600: [])
    monkeypatch.setattr(dashboard_v2, "net_carry_courant", lambda root=None: -5.0)
    d = _appel(_requete([
        {"timestamp_ms": 1000, "current_equity_usdt": 1000.0, "current_pnl_usdc": 0.0},
        {"timestamp_ms": 2000, "current_equity_usdt": 1000.0, "current_pnl_usdc": 0.0},
    ]))
    assert d["points"][0]["equity"] == 1000.0, "un point PASSÉ ne doit pas bouger"
    assert d["points"][-1]["equity"] == 995.0


def test_un_carry_illisible_ne_CASSE_PAS_la_courbe(monkeypatch):
    """Deny-by-default appliqué correctement : donnée absente -> 0, pas d'exception, pas
    d'invention. La courbe copy reste affichable même si le carry est HS."""
    monkeypatch.setattr("hl_observer.runtime.equity_history_store.read_equity_points",
                        lambda max=600: [])

    def explose(root=None):
        raise RuntimeError("ledger carry corrompu")

    monkeypatch.setattr(dashboard_v2, "net_carry_courant", explose)
    try:
        d = _appel(_requete([{"timestamp_ms": 1, "current_equity_usdt": 1000.0,
                              "current_pnl_usdc": 0.0}]))
    except RuntimeError:
        raise AssertionError("un carry illisible ne doit JAMAIS casser la courbe d'equity")
    assert d["points"][-1]["equity"] == 1000.0


def test_net_carry_courant_est_INJECTABLE():
    """Un endpoint qui lit une racine codée en dur est INTESTABLE : l'état live fuite dans les
    tests. C'est un test qui l'a attrapé — la fonction accepte donc une racine."""
    import inspect
    assert "root" in inspect.signature(dashboard_v2.net_carry_courant).parameters
    assert dashboard_v2.net_carry_courant(root="/chemin/qui/n/existe/pas") == 0.0


# ------------------------------------------------------------- défaut 2 : les pannes parlent

def test_aucun_catch_muet_ne_subsiste():
    """LE CLIQUET : `.catch(function(){})` avale une panne serveur en silence. Si quelqu'un en
    réintroduit un, ce test rougit — c'est la seule façon d'éviter que l'UI redevienne aveugle."""
    src = open(dashboard_v2.__file__, encoding="utf-8").read()
    assert ".catch(function(){})" not in src, (
        "un catch MUET est revenu : une erreur serveur y disparaîtra sans laisser de trace, "
        "et le panneau restera figé sur « … » sans jamais dire pourquoi.")


def test_la_page_sait_afficher_une_panne():
    page = _endpoint("/v2")().body.decode("utf-8")
    for morceau in ("signalerPanne", "signalerOK", "rendrePannes", 'id="pannes"'):
        assert morceau in page, "le mécanisme d'affichage des pannes est incomplet : %s" % morceau


def test_aucun_getElementById_sans_element():
    """Un seul ID manquant fait planter le script ENTIER (null.textContent) et fige tous les
    panneaux d'un coup. Vérification mécanique, pas à l'œil."""
    import re
    page = _endpoint("/v2")().body.decode("utf-8")
    ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', page))
    refs = set(re.findall(r"getElementById\(['\"]([A-Za-z0-9_-]+)['\"]\)", page))
    manquants = sorted(refs - ids)
    assert not manquants, "getElementById sans élément (crash JS garanti) : %r" % manquants
