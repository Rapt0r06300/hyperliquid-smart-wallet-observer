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


# ---------------- 20/07 soir : UNIFICATION des positions + session jusqu'au navigateur ----------------

def test_l_endpoint_carry_TRANSMET_le_pnl_de_session():
    """Le bug vu par Flo dans Chrome : etat_carry CALCULAIT le PnL de session, mais le dict de
    reponse /v2/carry filtrait les cles -> le grand chiffre affichait l'HISTORIQUE (-6.03).
    Un filtre de cles est une porte : il doit laisser passer tout ce que l'ecran promet."""
    src = open("src/hl_observer/ui/dashboard_v2.py", encoding="utf-8").read()
    assert '"realized_net_pnl_usdc_session": etat.get("realized_net_pnl_usdc_session")' in src
    assert '"taux_accrual_usd_h"' in src, "le taux usd/h alimente le ticker de fraicheur"


def test_le_panneau_POSITIONS_est_UNIFIE_copy_plus_carry():
    """« 3 positions ouvertes mais je ne les vois pas dans l'ecran des positions » : le panneau
    ne montrait que le copy. Desormais les lignes carry y sont, etiquetees CARRY, et le
    compteur additionne les deux. Une page, une verite."""
    src = open("src/hl_observer/ui/dashboard_v2.py", encoding="utf-8").read()
    assert "window._carryRows" in src
    assert "(ps.length+cRows.length)+' ouvertes'" in src
    assert "tag2 tg-g\">CARRY" in src.replace("'", '"')
    assert "!ps.length&&!cRows.length" in src, "le message 'aucune position' exige les DEUX vides"


def test_le_ticker_de_fraicheur_interpole_le_taux_MESURE_et_resnappe():
    """« Je veux une fraicheur maximum » : le funding coule continument dans la realite. Le
    ticker 1 s = dernier releve REEL + taux MESURE x temps ecoule, resnappe a chaque poll (2 s).
    Interpolation d'une mesure, jamais une invention."""
    src = open("src/hl_observer/ui/dashboard_v2.py", encoding="utf-8").read()
    assert "setInterval(loadCarry,2000)" in src, "poll carry acceleree 4s -> 2s"
    assert "_carryRateUsdH" in src and "_carryPollTs" in src
    assert "resnappee" in src, "le contrat d'honnetete de l'interpolation est documente"


# ---------------- 20/07 revue Chrome n°2 : les panneaux COPY deguises en panneaux GLOBAUX ----------------
# La page fraiche montrait « funding +0.0000 » (panneau couts, copy-only) PENDANT que le carry
# accroissait $0.027 trois lignes plus haut ; « ✓ 0 » (coche verte sur zero donnee) ; « ledger 0pos »
# a cote de « 3 OUVERTES » ; « TRADES CLOS 6 » qui melangeait copy-session et carry-24h.
# Meme famille que le bug des tuiles du 19/07 : un chiffre juste sous une mauvaise etiquette est faux.

def _src():
    return open("src/hl_observer/ui/dashboard_v2.py", encoding="utf-8").read()


def test_le_panneau_couts_est_ETIQUETE_copy_et_montre_le_funding_carry():
    src = _src()
    assert "COÛTS NETS <span class=\"hint\">copy · session</span>" in src, \
        "le panneau couts doit dire son perimetre (copy), pas se faire passer pour global"
    assert src.count("c-fund-carry") >= 3, \
        "la ligne funding carry doit exister (HTML) et etre alimentee (poll + ticker 1 s)"


def test_marks_zero_affiche_un_tiret_JAMAIS_une_coche_verte():
    """« ✓ 0 » = chiffre rassurant sorti de rien (meme regle que le PF « ≥1 » du 19/07)."""
    src = _src()
    assert "if(av===0&&mi===0){fr.textContent='— 0';fr.style.color='var(--mut2)';}" in src


def test_le_wiring_etiquette_le_ledger_comme_COPY():
    """« ledger 0pos » a cote de « 3 OUVERTES » : c'est le ledger du moteur copy, il le dit."""
    assert "'ledger copy'" in _src()


def test_trades_clos_prefere_le_compteur_de_SESSION_avec_repli_honnete():
    """La rangee de tuiles est SESSION (comme le grand PnL) : le carry y entre par
    closes_session (ledger etiquete), pas par la fenetre 24 h du churn ; repli si vieux moteur."""
    src = _src()
    assert "(d.closes_session!=null)?Number(d.closes_session):Number((d.churn&&d.churn.closes)||0)" in src


def test_funding_arb_legacy_ne_se_confond_plus_avec_le_funding_du_carry():
    """« funding · paires 0 · off » se lisait « le funding est OFF » alors que le carry
    encaisse du funding : c'est le funding-ARB perp<->perp (loi X-04, ferme) — etiquete."""
    assert "funding-arb · paires" in _src()
