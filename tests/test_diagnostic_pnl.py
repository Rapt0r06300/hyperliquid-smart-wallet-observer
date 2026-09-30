"""CERVELLE DIAGNOSTIC — transformer le RECAP en compréhension du PnL. On VERROUILLE : le parsing
tolérant du RECAP, la synthèse « où va l'argent », le verdict funding vs HLP, et la prochaine
action dérivée (jamais un vœu). Deny-by-default. Aucune donnée réseau."""
from __future__ import annotations

from hl_observer.ops import diagnostic_pnl as D

_RECAP = """## Où va l'argent (24 h)

- total : **+0.6616 $** sur 16 fermeture(s)
- par stratégie : `{'arbitrage': 0.5379, 'carry': 0.1237}`
- par motif : `{'ARB_CONVERGENCE_CAPTUREE': 0.6579, 'ARB_AGE_MAX_SANS_CONVERGENCE': -0.12}`
"""


def test_pnl_depuis_recap_lit_total_strategie_motif():
    p = D.pnl_depuis_recap(_RECAP)
    assert p["total"] == 0.6616 and p["fermetures"] == 16
    assert p["par_strategie"]["arbitrage"] == 0.5379
    assert p["par_motif"]["ARB_AGE_MAX_SANS_CONVERGENCE"] == -0.12


def test_ou_va_l_argent_nomme_meilleure_pire_et_motif_couteux():
    lignes = "\n".join(D.ou_va_l_argent(D.pnl_depuis_recap(_RECAP)))
    assert "meilleure stratégie : **arbitrage**" in lignes
    assert "COÛTEUX : **ARB_AGE_MAX_SANS_CONVERGENCE**" in lignes


def test_recap_sans_total_est_INSUFFISANT():
    lignes = D.ou_va_l_argent(D.pnl_depuis_recap("aucun chiffre ici"))
    assert any("INSUFFISANT" in l for l in lignes)


def test_funding_colle_au_plancher_dit_DOMINE_par_HLP():
    obs = [{"coin": "BTC", "hl_bps_h": 0.125} for _ in range(50)]
    r = D.funding_hors_plancher(obs)
    assert r["pct_bat_hlp"] == 0.0 and "DOMINÉ" in r["verdict"]


def test_funding_eleve_ouvre_une_fenetre():
    obs = [{"coin": "WIF", "hl_bps_h": 0.45} for _ in range(50)]
    r = D.funding_hors_plancher(obs)
    assert r["pct_bat_hlp"] == 100.0 and "fenêtre" in r["verdict"].lower()


def test_prochaine_action_pointe_l_univers_quand_le_carry_est_domine():
    action = D.prochaine_action({"total": 0.1}, ["- **carry** : ... DOMINÉ par HLP ..."])
    assert "univers" in action.lower()


def test_construire_produit_la_section_sans_planter(tmp_path):
    (tmp_path / "RECAP-COMPLET.md").write_text(_RECAP, encoding="utf-8")
    section = D.construire(tmp_path)
    assert "COMPRENDRE LE PnL" in section and "PROCHAINE ACTION" in section
    assert "Aucune promesse de PnL" in section


def test_construire_sans_recap_reste_honnete(tmp_path):
    section = D.construire(tmp_path)                 # pas de RECAP
    assert "COMPRENDRE LE PnL" in section            # la section existe, honnête et vide
