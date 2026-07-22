"""LA STRATÉGIE EFFECTIVE D'UN CANDIDAT — une seule vérité, mesure + crible (22/07).

Le rapport qualité criait « 9 % des candidats portent une strategie » = DÉFAUTS À CORRIGER.
Mesure : 77,6 % de l'historique n'a pas de label MAIS porte `leader_wallet`/`leader_score` —
ce sont des candidats copy, classables sans ambiguïté. La vraie santé : 100 % classables, 0
ambigu. L'alarme brute prenait un historique parfait pour un défaut.
"""
from __future__ import annotations

from hl_observer.ops.strategie_candidat import (INCONNU, resume_etiquetage,
                                                strategie_effective)


# ─────────────── le label explicite fait foi ───────────────

def test_un_label_explicite_est_pris_tel_quel():
    assert strategie_effective({"strategie": "carry"}) == "carry"
    assert strategie_effective({"strategie": "copy"}) == "copy"
    assert strategie_effective({"strategie": "arbitrage"}) == "arbitrage"


def test_les_alias_sont_normalises():
    assert strategie_effective({"strategie": "funding_arb"}) == "arbitrage"
    assert strategie_effective({"strategie": "triangular"}) == "arbitrage"


# ─────────────── l'inférence quand le label manque ───────────────

def test_un_candidat_copy_SANS_label_est_reconnu_a_ses_champs():
    """LE cas du rapport : 77,6 % de l'historique, sans `strategie`, avec les champs copy."""
    c = {"coin": "AAVE", "leader_wallet": "0xabc", "leader_score": 72.5,
         "consensus_wallets": 2, "leader_expected_edge_bps": 45.6}
    assert strategie_effective(c) == "copy"
    # même sans strategie, même sans leader_wallet, un seul champ distinctif suffit :
    assert strategie_effective({"leader_score": 10.0}) == "copy"


def test_un_candidat_arbitrage_sans_label_est_reconnu():
    assert strategie_effective({"coin": "MKR", "ecart_prix_bps": 71.4}) == "arbitrage"
    assert strategie_effective({"venue_haute": "HL", "hl_px": 1.0, "bin_px": 1.01}) == "arbitrage"


def test_un_candidat_carry_sans_label_est_reconnu():
    assert strategie_effective({"coin": "BTC", "funding_bps_h": 0.45, "base_bps": -0.6}) == "carry"


def test_un_carry_sans_label_n_est_JAMAIS_range_en_copy_par_accident():
    """🔴 LE défaut de l'alias aveugle : il mappait TOUT '?' en copy. Un candidat carry qui
    perd son label doit être reconnu carry, pas compté copy."""
    c = {"coin": "ETH", "funding_bps_h": 0.30, "base_bps": 2.0}   # pas de label, pas de leader
    assert strategie_effective(c) == "carry", "ses champs disent carry, pas copy"


def test_un_candidat_vraiment_ambigu_reste_INCONNU():
    """Sans label ET sans marqueur : `?`. On ne range pas de confort — c'est LE vrai défaut."""
    assert strategie_effective({"coin": "BTC", "current_mid": 100.0}) == INCONNU
    assert strategie_effective({}) == INCONNU
    assert strategie_effective("pas un dict") == INCONNU


def test_un_label_INCONNU_retombe_sur_l_inference():
    """`strategie: '?'` avec des champs copy -> copy (le label vide ne bloque pas l'inférence)."""
    assert strategie_effective({"strategie": "?", "leader_wallet": "0x1"}) == "copy"
    assert strategie_effective({"strategie": "", "ecart_prix_bps": 30.0}) == "arbitrage"


# ─────────────── le résumé qui doit alimenter l'alarme ───────────────

def test_le_resume_distingue_label_inference_et_ambigu():
    cands = [
        {"strategie": "carry"},                       # label
        {"leader_wallet": "0x1"},                     # inféré copy
        {"ecart_prix_bps": 30.0},                     # inféré arbitrage
        {"coin": "X", "current_mid": 1.0},            # VRAIMENT ambigu
    ]
    r = resume_etiquetage(cands)
    assert r["total"] == 4
    assert r["label_brut_pct"] == 25.0               # 1/4 portent le label
    assert r["classes_pct"] == 75.0                  # 3/4 classables (label + inférence)
    assert r["ambigus"] == 1 and r["ambigus_pct"] == 25.0
    assert r["par_strategie"]["carry"] == 1 and r["par_strategie"]["copy"] == 1


def test_le_resume_sur_un_historique_copy_dit_100_pourcent_classable():
    """La correction en une assertion : un historique tout-copy sans label -> 100 % classable,
    0 ambigu. L'alarme ne doit PAS se déclencher là-dessus."""
    cands = [{"leader_wallet": "0x%d" % i, "leader_score": 50.0} for i in range(1000)]
    r = resume_etiquetage(cands)
    assert r["classes_pct"] == 100.0 and r["ambigus"] == 0
    assert r["label_brut_pct"] == 0.0                # aucun ne porte le label, et pourtant...
    assert r["par_strategie"] == {"copy": 1000}


def test_le_resume_vide_ne_LEVE_pas():
    r = resume_etiquetage([])
    assert r["total"] == 0 and r["classes_pct"] == 100.0


# ─────────────── mesure et crible s'accordent ───────────────

def test_la_metrique_qualite_et_le_crible_utilisent_LA_MEME_fonction():
    """« Une seule vérité » : les deux consomment `strategie_candidat`, pas deux logiques."""
    import inspect

    from hl_observer.backtesting import recherche_scenario as rs
    qual = open("tools/qualite_donnees_replay.py", encoding="utf-8").read()
    assert "strategie_candidat" in qual, "la metrique qualite doit utiliser la fonction partagee"
    assert "strategie_effective" in inspect.getsource(rs.DonneesReplay.charger), (
        "le crible doit bucketer par strategie EFFECTIVE, pas par l'alias aveugle")
