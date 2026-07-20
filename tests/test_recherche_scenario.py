"""RECHERCHE DE SCÉNARIO — le « parfait » qu'on accepte est celui qui SURVIT.

Trois exécutions du même piège, tuées par trois barres :
  * le GAGNANT CHANCEUX (brille sur la moitié 1, meurt sur la 2) -> rejeté ;
  * le PIC ISOLÉ (passe les moitiés, ses voisins meurent)        -> rejeté (plateau W8) ;
  * le FRAGILE AUX COÛTS (net <= 0 à frais x1,5)                  -> rejeté (F29).
Et la fuite du 13/07 ne peut pas revenir : l'embargo jette les candidats à moins d'un
horizon de la coupe, DES DEUX côtés.
"""
from __future__ import annotations

from hl_observer.backtesting.recherche_scenario import (
    DonneesReplay, chercher, grille_configs, porte_robuste, voisins,
    MIN_TRADES_PAR_MOITIE,
)


def _cand(ts: float) -> dict:
    return {"recorded_at": ts, "coin": "HYPE", "strategie": "carry"}


DONNEES = DonneesReplay(
    candidats=[_cand(t) for t in (0, 1000, 2000, 3000, 30000, 40000, 50000, 60000)],
    marks=[])


# ------------------------------------------------------------------ 1. la coupe + embargo

def test_l_embargo_jette_les_candidats_trop_pres_de_la_coupe_DES_DEUX_COTES():
    """Fuite du 13/07 : sans embargo, les outcomes de fin de moitié 1 se réalisent dans la
    moitié 2. Ici : horizon 60 min -> 3600 s de marge. Le candidat pile sur la coupe meurt."""
    m1, m2 = DONNEES.moities_avec_embargo(60.0)
    assert [c["recorded_at"] for c in m1] == [0, 1000, 2000, 3000]
    assert [c["recorded_at"] for c in m2] == [40000, 50000, 60000]   # 30000 = la coupe, jetée


def test_sans_candidats_les_moities_sont_vides_pas_une_exception():
    assert DonneesReplay().moities_avec_embargo(60.0) == ([], [])


# ------------------------------------------------------------------ 2. l'espace de recherche

def test_la_grille_ne_genere_JAMAIS_un_ratio_perdant_par_construction():
    configs = list(grille_configs())
    assert configs and all(c["tp"] > c["sl"] for c in configs)


def test_les_voisins_restent_valides_et_au_nombre_attendu():
    vs = voisins({"sl": 40.0, "tp": 70.0, "horizon_min": 60.0})
    assert len(vs) == 4 and all(v["tp"] > v["sl"] > 0 for v in vs)
    # au bord de la grille (tp-20 <= sl), le voisin invalide disparait au lieu d'etre absurde
    assert len(voisins({"sl": 40.0, "tp": 55.0})) == 3


# ------------------------------------------------------------------ 3. la porte robuste

def _moitie(net: float, trades: int = 50, pf: float = 1.5) -> dict:
    return {"net_total_usd": net, "trades": trades, "profit_factor": pf}


def test_la_porte_exige_les_DEUX_moities_ET_le_stress():
    bon = {"moitie_1": _moitie(5.0), "moitie_2": _moitie(3.0), "stress": _moitie(1.0)}
    assert porte_robuste(bon) is True
    assert porte_robuste({**bon, "moitie_2": _moitie(-0.1)}) is False       # gagnant chanceux
    assert porte_robuste({**bon, "stress": _moitie(-0.5)}) is False         # fragile aux couts
    assert porte_robuste({**bon, "moitie_1": _moitie(5.0, trades=MIN_TRADES_PAR_MOITIE - 1)}) \
        is False                                                            # pas assez de preuves
    assert porte_robuste({**bon, "moitie_2": _moitie(3.0, pf=1.05)}) is False  # PF sous la barre
    assert porte_robuste({**bon, "moitie_1": _moitie(5.0, pf="inf")}) is True  # 0 perte = ok


# ------------------------------------------------------------------ 4. la recherche complète

def _fake_ab(nets: dict[float, tuple[float, float]]):
    """Fabrique un faux run_ab_replay : nets[sl] = (net_moitie_1, net_moitie_2).
    La moitié se reconnaît à son 1er candidat ; le stress aux coûts > défaut."""
    def evaluer_ab(candidats, marks, *, base_config, horizon_min, cost_bps):
        sl = base_config.stop_loss_bps
        n1, n2 = nets.get(sl, (-1.0, -1.0))
        if cost_bps > 15.0:                             # stress x1,5 (défaut 12 -> 18)
            net = (n1 + n2) - 1.0                       # les coûts mangent 1 $
        elif candidats and candidats[0]["recorded_at"] < 30000:
            net = n1
        else:
            net = n2
        return {"arm_a": {"net_total_usd": net, "trades": 60, "profit_factor": 1.5}}
    return evaluer_ab


def test_le_gagnant_chanceux_est_REJETE_et_le_survivant_PROMU(tmp_path):
    """CHANCEUX gagne 10 $ sur la moitié 1 et perd sur la 2 -> rejeté. SURVIVANT gagne
    modestement PARTOUT (et ses voisins aussi) -> promu. Le « parfait » est le second."""
    nets = {50.0: (10.0, -2.0),                          # le chanceux (sl=50)
            40.0: (3.0, 2.5),                            # le survivant (sl=40)
            30.0: (2.0, 2.0), 45.0: (2.0, 1.5), 35.0: (1.0, 1.0)}   # ses voisins vivants
    configs = [{"sl": 50.0, "tp": 90.0, "horizon_min": 60.0},
               {"sl": 40.0, "tp": 70.0, "horizon_min": 60.0}]
    r = chercher(tmp_path, configs=configs, donnees=DONNEES, evaluer_ab=_fake_ab(nets))
    assert r["statut"] == "PROMU"
    assert r["gagnant"]["sl"] == 40.0
    assert [e["verdict"] for e in r["essais"]] == ["REJETE", "PROMU"]
    assert (tmp_path / "runtime" / "replay" / "recherche_scenario_etat.json").exists()


def test_le_PIC_ISOLE_est_rejete_par_le_plateau(tmp_path):
    """sl=40 brille sur les deux moitiés... mais TOUS ses voisins perdent : pic isolé dans
    la grille = artefact (W8). La porte le refuse malgré ses belles moitiés."""
    nets = {40.0: (5.0, 4.0)}                            # voisins absents -> (-1,-1) perdants
    r = chercher(tmp_path, configs=[{"sl": 40.0, "tp": 70.0, "horizon_min": 60.0}],
                 donnees=DONNEES, evaluer_ab=_fake_ab(nets))
    assert r["statut"] == "ESPACE_EPUISE" and r["gagnant"] is None


def test_zero_candidat_est_un_INSUFFISANT_honnete(tmp_path):
    r = chercher(tmp_path, donnees=DonneesReplay(), evaluer_ab=_fake_ab({}))
    assert r["statut"] == "INSUFFISANT" and "W2" in r["motif"]
