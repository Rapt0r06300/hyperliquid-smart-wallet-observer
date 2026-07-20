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


# ---------------- 20/07 « les chiffres stagnent » : l'ancre sur CHANGEMENT ----------------
# Mesure en direct (17:43) : cellules IDENTIQUES a 7 s d'ecart pendant que l'API donnait un
# taux de 0.0009375 $/h par coin. Cause : le poll 2 s resnappait base+horloge sans nouvelle
# mesure -> l'interpolation ne depassait jamais ~5e-7 $ (invisible). En prime le poll ecrivait
# 4 decimales contre 6 au ticker (clignotement), et le curseur du flux restait fige 5 min.

def test_le_ticker_ancre_sur_CHANGEMENT_pas_sur_chaque_poll():
    src = _src()
    assert "window._carryAccruBase!==apiAccru||!window._carryPollTs" in src, \
        "le total ne resnappe que quand la mesure change (sinon l'interpolation coule)"
    assert "q.accru===a&&q.t0)?q.t0:Date.now()" in src.replace(" ", ""), \
        "chaque ligne garde son ancre t0 tant que le moteur n'a pas rafraichi SA mesure"
    assert "(Date.now()-(p.t0||t0))/3.6e6" in src, "le ticker utilise l'ancre par ligne"


def test_l_accru_a_UN_SEUL_format_6_decimales_poll_et_ticker():
    src = _src()
    assert "n(d.funding_accru_usdt,6)" in src and "n(d.funding_accru_usdt,4)" not in src, \
        "poll a 4 decimales + ticker a 6 = clignotement $0.0287 <-> $0.028677"


def test_le_curseur_du_flux_se_redessine_chaque_seconde():
    assert "setInterval(renderFeed,1000)" in _src(), \
        "un curseur fige 5 min sous l'etiquette LIVE est un mensonge d'horloge"


def test_le_flux_scan_etiquette_les_positions_comme_COPY():
    assert "pos copy actives" in _src(), \
        "« 0 pos actives » a cote de 3 positions carry : le perimetre copy doit se dire"


# ---------------- 20/07 soir : fraicheur MAXIMALE physique + metagraphe VIVANT ----------------

def test_le_grand_pnl_et_l_equity_sont_en_6_decimales():
    src = _src()
    assert "P.textContent=(totNet>=0?'+':'')+n(totNet,6)" in src
    assert "E.textContent=n(eqCopy+carryNet,6)" in src


def test_la_boucle_de_fraicheur_est_calee_sur_l_ecran_requestAnimationFrame():
    """« chaque milliseconde » : l'ecran affiche 60-144 img/s — plus vite est invisible.
    rAF = le maximum physique, et il se met en pause onglet cache (0 gaspillage)."""
    src = _src()
    assert "requestAnimationFrame(boucleFraicheur)" in src
    assert "setInterval(majAccruLive" not in src, "l'ancien tick 1 s doit avoir disparu"


def test_le_metagraphe_recoit_le_point_vivant_et_a_une_fenetre_zoomable():
    src = _src()
    assert "window._eqLiveVal" in src and "pts.concat([{t:Date.now(),equity:lv}])" in src, \
        "le point vivant prolonge la courbe (meme interpolation que le grand chiffre)"
    assert "window._metaWin=3600000" in src, "fenetre par defaut 1 h (pente visible)"
    assert "(w===3600000)?300000:(w===300000?0:3600000)" in src, "cycle 1h -> 5min -> tout au clic"
    assert "mg-baselbl" in src, "l'etiquette de base dit si c'est l'equity depart ou la fenetre"


def test_la_base_du_pourcentage_vient_de_la_serie_COMPLETE_jamais_de_la_fenetre():
    """Zoomer ne doit JAMAIS changer le % affiche : base = premier point de la serie complete."""
    src = _src()
    assert "window._base=pts[0].equity" in src
    assert "window._base=base" not in src, "l'ancienne base (fenetre courante) mentirait en zoom"


# ---------------- 20/07 soir : « le PnL monte comme un minuteur » -> la BASE entre au PnL ----------------
# Le funding est un compteur d'interets (lineaire PAR NATURE — c'est le metier du carry).
# La respiration realiste d'un vrai livre, c'est la BASE (perp−spot), mesuree a chaque passe,
# qui bouge dans les DEUX sens. « Je ne veux pas que le pnl mente » : l'afficher SANS la base,
# c'etait cacher la composante qui peut BAISSER.

from hl_observer.ui.dashboard_v2 import base_mtm_usd


def test_base_mtm_le_signe_est_celui_d_A5_convergence_paye_le_short_perp():
    # entre a +30 bps de premium, la base est retombee a +10 -> le short perp a capture 20 bps
    assert base_mtm_usd(30.0, 10.0, 150.0) == 0.30   # 20 bps x 150$ / 1e4
    # la base s'ECARTE (10 -> 40) : on PERD — le PnL a le droit de baisser, c'est la verite
    assert base_mtm_usd(10.0, 40.0, 150.0) == -0.45
    assert base_mtm_usd(None, 10.0, 150.0) is None, "entree inconnue -> None, jamais invente"


def test_l_endpoint_transmet_le_mtm_et_la_base_courante_ou_None_honnete():
    src = _src()
    assert '"base_mtm_usd": _mtm' in src and '"base_bps_courant": _bc' in src
    assert "if _bc is not None else None" in src, "hors shortlist ce tick -> None, pas un zero deguise"


def test_le_pnl_affiche_inclut_le_mtm_et_chaque_cellule_dit_son_decompte():
    src = _src()
    assert "window._carryNet=Number(window._carryReal||0)+live+mtmTot" in src
    assert "base non mesuree ce tick" in src, "l'absence de mesure se DIT"
    assert "realisable a la fermeture" in src and "hors couts" in src, \
        "l'infobulle separe le mesure, l'estime, et ce qui reste a payer"


def test_UNE_SEULE_definition_du_net_carry_la_courbe_inclut_le_MtM(tmp_path):
    """« ça ne va pas du tout » (20/07 soir) : la courbe (net sans MtM) et le grand chiffre
    (net avec MtM) divergeaient de 0,19 $ -> falaise FABRIQUEE au raccord. Une definition."""
    import json as _j
    from hl_observer.ui.dashboard_v2 import net_carry_courant
    d = tmp_path / "runtime" / "data"; d.mkdir(parents=True)
    (d / "carry_paper_positions.json").write_text(_j.dumps({"mode": "LIVE", "ouvertes": {
        "HYPE": {"coin": "HYPE", "mode": "LIVE", "notional_usdt": 150.0,
                 "funding_accrued_usdt": 0.01, "base_bps_entree": 30.0,
                 "cout_entree_bps": 2.0, "entry_ts_ms": 1,
                 "marge_usdt": 100.0, "levier": 1.5}}}), encoding="utf-8")
    import time as _t
    (d / "carry_bases_courantes.json").write_text(_j.dumps(
        {"ts_ms": _t.time() * 1000, "bases": {"HYPE": {"base_mid_bps": 10.0, "liq": 50000}}}),
        encoding="utf-8")
    net = net_carry_courant(tmp_path)
    assert abs(net - (0.01 + 0.30)) < 1e-9, \
        "net = accru 0.01 + MtM (30-10)bps x 150$ = 0.31 — la MEME somme que l'affichage"


def test_le_marquage_MID_perime_ou_absent_donne_ZERO_MtM_jamais_un_bruit(tmp_path):
    """20/07 soir (yoyo -0,22 -> +0,31) : marquer au VWAP-500$ d'une shortlist partielle
    fabriquait des sauts. Regle : marquage MID de TOUS les coins scannes ; fichier absent ou
    perime -> {} -> MtM absent (un marquage perime n'est pas un marquage)."""
    import json as _j, time as _t
    from hl_observer.ui.dashboard_v2 import bases_courantes_mid
    assert bases_courantes_mid(tmp_path) == {}
    d = tmp_path / "runtime" / "data"; d.mkdir(parents=True)
    (d / "carry_bases_courantes.json").write_text(_j.dumps(
        {"ts_ms": (_t.time() - 3600) * 1000, "bases": {"HYPE": {"base_mid_bps": 5.0}}}),
        encoding="utf-8")
    assert bases_courantes_mid(tmp_path) == {}, "perime (1 h) -> vide, jamais un vieux marquage"
    (d / "carry_bases_courantes.json").write_text(_j.dumps(
        {"ts_ms": _t.time() * 1000, "bases": {"HYPE": {"base_mid_bps": 5.0}}}), encoding="utf-8")
    assert bases_courantes_mid(tmp_path) == {"HYPE": 5.0}


def test_la_chaine_MID_est_cablee_feeder_entree_endpoint_et_poll():
    """Le feeder publie base_mid pour TOUS les coins ; l'entree stocke base_mid_bps_entree ;
    l'endpoint marque MID contre MID ; le poll JS n'a plus de definition transitoire."""
    src = _src()
    feed = open("tools/ecrire_carry_spot_inputs.py", encoding="utf-8").read()
    lifec = open("src/hl_observer/funding/carry_position_lifecycle.py", encoding="utf-8").read()
    assert "carry_bases_courantes.json" in feed and "bases_mid_dump" in feed
    assert '"base_mid_bps"' in feed, "les inputs portent la base MID"
    assert '"base_mid_bps_entree": _f(inputs, "base_mid_bps")' in lifec
    assert "bases_courantes_mid(root)" in src
    assert "window._carryNet=realSess+Number(d.funding_accru_usdt||0)+_mtmPoll" in src
