"""Bloc 18 — revalidation économique : scénarios ANALYTIQUES exigés par la roadmap.

Un moteur de PnL ne se teste pas avec « ça a l'air cohérent » : on lui donne des cas dont la réponse est
connue à la main (frais nuls + prix plat = 0 ; frais seuls = perte exacte ; long/short symétriques), et on
vérifie que les épisodes non mesurables ne sont **jamais** valorisés à 0.

Paper only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import economic_revalidation as ER  # noqa: E402


def _ep(prix_entree=100.0, prix_sortie=100.0, sens=1, notional=1_000.0, frais=0.0, coin="BTC"):
    return ER.Episode(strategie="test", coin=coin, sens=sens, notional_usd=notional,
                      prix_entree=prix_entree, prix_sortie=prix_sortie, frais_usd=frais)


# ═══════════════ scénarios analytiques ═══════════════
def test_zero_frais_prix_plat_donne_exactement_zero():
    e = _ep()
    assert e.pnl_brut_usd() == 0.0 and e.pnl_net_usd() == 0.0 and e.net_bps() == 0.0


def test_frais_seuls_donnent_la_perte_exacte():
    e = _ep(frais=0.45)                      # 4,5 bps sur 1 000 $
    assert e.pnl_net_usd() == -0.45
    assert round(e.net_bps(), 6) == -4.5


def test_long_et_short_sont_symetriques():
    hausse = _ep(prix_entree=100.0, prix_sortie=101.0, sens=1)
    baisse = _ep(prix_entree=100.0, prix_sortie=101.0, sens=-1)
    assert round(hausse.pnl_net_usd(), 6) == 10.0
    assert round(baisse.pnl_net_usd(), 6) == -10.0
    assert round(hausse.net_bps(), 4) == 100.0 and round(baisse.net_bps(), 4) == -100.0


def test_le_pnl_est_proportionnel_au_notionnel():
    petit = _ep(prix_sortie=101.0, notional=100.0)
    grand = _ep(prix_sortie=101.0, notional=1_000.0)
    assert round(grand.pnl_net_usd(), 6) == round(10 * petit.pnl_net_usd(), 6)


# ═══════════════ métriques ═══════════════
def test_profit_factor_et_drawdown():
    eps = [_ep(prix_sortie=101.0), _ep(prix_sortie=99.5), _ep(prix_sortie=101.0)]   # +10, -5, +10
    m = ER.metriques(eps, starting_equity_usd=1_000.0)
    assert round(m["net_pnl_usd"], 4) == 15.0
    assert round(m["profit_factor"], 4) == 4.0          # 20 / 5
    assert round(m["max_drawdown_usd"], 4) == -5.0
    assert m["hit_rate"] == round(2 / 3, 4)


def test_profit_factor_sans_perte_nest_pas_infini():
    m = ER.metriques([_ep(prix_sortie=101.0)], starting_equity_usd=1_000.0)
    assert m["profit_factor"] is None and "pas infini" in m["profit_factor_note"]


def test_les_quatre_roi_ont_des_denominateurs_distincts():
    eps = [_ep(prix_sortie=101.0)]                       # +10 $ sur 1 000 $ de notionnel
    m = ER.metriques(eps, starting_equity_usd=1_000.0, marge_moyenne_usd=100.0, marge_pic_usd=200.0)
    roi = m["roi"]
    assert roi["ROI_starting_equity"] == 0.01
    assert roi["ROI_avg_margin_locked"] == 0.1
    assert roi["ROI_peak_margin_locked"] == 0.05
    assert roi["return_on_gross_exposure"] == 0.01


def test_un_denominateur_absent_rend_none_pas_une_valeur_de_repli():
    m = ER.metriques([_ep(prix_sortie=101.0)], starting_equity_usd=1_000.0)
    assert m["roi"]["ROI_avg_margin_locked"] is None and m["roi"]["ROI_peak_margin_locked"] is None


def test_turnover_et_frais_sont_comptes():
    m = ER.metriques([_ep(frais=0.45), _ep(frais=0.45)], starting_equity_usd=1_000.0)
    assert m["turnover_usd"] == 4_000.0 and round(m["fees_usd"], 4) == 0.9


def test_capacite_absente_reste_none():
    m = ER.metriques([_ep()], starting_equity_usd=1_000.0)
    assert m["capacite_usd"] is None and m["fill_ratio"] is None


def test_aucun_episode_donne_un_statut_explicite_pas_des_zeros():
    m = ER.metriques([], starting_equity_usd=1_000.0)
    assert m["statut"] == "AUCUNE_DONNEE_MESURABLE"
    assert m["net_pnl_usd"] is None and m["profit_factor"] is None


# ═══════════════ normalisation : non mesurable ≠ zéro ═══════════════
def test_une_fermeture_sans_prix_executable_nest_pas_valorisee_a_zero():
    lignes = [{"evt": "OPEN", "coin": "BTC", "sens": 1, "notional_usd": 100.0, "prix_entree": 50.0},
              {"evt": "CLOSE", "coin": "BTC", "sens": 1, "prix_sortie": None}]
    r = ER.normaliser_episodes(lignes, strategie="t")
    assert r["n_episodes"] == 0
    assert r["rejets"]["FERMETURE_SANS_PRIX_EXECUTABLE"] == 1


def test_une_fermeture_orpheline_est_refusee():
    r = ER.normaliser_episodes([{"evt": "CLOSE", "coin": "BTC", "sens": 1, "prix_sortie": 50.0}], strategie="t")
    assert r["n_episodes"] == 0 and r["rejets"]["FERMETURE_ORPHELINE"] == 1


def test_une_position_encore_ouverte_est_comptee_comme_non_mesurable():
    lignes = [{"evt": "OPEN", "coin": "BTC", "sens": 1, "notional_usd": 100.0, "prix_entree": 50.0}]
    r = ER.normaliser_episodes(lignes, strategie="t")
    assert r["n_episodes"] == 0 and r["rejets"]["POSITION_ENCORE_OUVERTE"] == 1


def test_un_aller_retour_complet_est_apparie():
    lignes = [{"evt": "OPEN", "coin": "BTC", "sens": 1, "notional_usd": 1_000.0, "prix_entree": 100.0,
               "ts_ms": 1},
              {"evt": "CLOSE", "coin": "BTC", "sens": 1, "prix_sortie": 101.0, "ts_ms": 2}]
    r = ER.normaliser_episodes(lignes, strategie="t")
    assert r["n_episodes"] == 1 and round(r["episodes"][0].pnl_net_usd(), 6) == 10.0


# ═══════════════ enveloppes ═══════════════
def test_les_enveloppes_adverses_degradent_reellement_le_resultat():
    eps = [_ep(prix_sortie=101.0) for _ in range(3)]
    env = ER.enveloppes(eps, starting_equity_usd=1_000.0)
    base = env["BASE_CALIBRATED"]["net_pnl_usd"]
    assert env["ADVERSE_P95"]["net_pnl_usd"] < base
    assert env["ADVERSE_P99"]["net_pnl_usd"] < env["ADVERSE_P95"]["net_pnl_usd"]
    assert env["ADVERSE_P95"]["origine"] == "ASSUMED"


def test_lenveloppe_optimiste_est_marquee_non_promouvable():
    env = ER.enveloppes([_ep(prix_sortie=101.0)], starting_equity_usd=1_000.0)
    opt = env["OPTIMISTIC_DIAGNOSTIC_ONLY"]
    assert opt["promouvable"] is False and opt["net_pnl_usd"] > env["BASE_CALIBRATED"]["net_pnl_usd"]


# ═══════════════ exécution sur disque ═══════════════
def test_ledger_absent_donne_un_statut_explicite(tmp_path):
    r = ER.revalider(tmp_path, ledgers={"fantome": "runtime/data/inexistant.jsonl"})
    assert r["strategies"]["fantome"]["statut"] == "LEDGER_ABSENT"
    assert r["paper_only"] is True and r["real_execution"] is False


def test_revalidation_sur_un_ledger_reel_ecrit_un_rapport(tmp_path):
    ledger = tmp_path / "runtime" / "data" / "l.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        '{"evt":"OPEN","coin":"BTC","sens":1,"notional_usd":1000,"prix_entree":100,"ts_ms":1}\n'
        '{"evt":"CLOSE","coin":"BTC","sens":1,"prix_sortie":101,"ts_ms":2}\n'
        'PAS DU JSON\n', encoding="utf-8")
    r = ER.revalider(tmp_path, ledgers={"demo": "runtime/data/l.jsonl"})
    bloc = r["strategies"]["demo"]
    assert bloc["statut"] == "MESURE" and bloc["n_episodes"] == 1
    assert round(bloc["enveloppes"]["BASE_CALIBRATED"]["net_pnl_usd"], 6) == 10.0
    chemin = ER.ecrire_rapport(r, tmp_path)
    assert chemin.exists()


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "ops" / "economic_revalidation.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans economic_revalidation: %s" % interdit
