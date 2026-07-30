"""ALPHA-7 — toxicité et crowding des métaordres.

Objectif prouvé ici : la porte ne peut que REFUSER ou S'ABSTENIR, jamais autoriser une entrée ; une donnée
absente vaut `None` (jamais un `False` rassurant) ; et une ablation sans échantillon suffisant ne proclame
aucune amélioration.

SHADOW uniquement : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.experimental import metaorder_toxicite as TOX  # noqa: E402
from hl_observer.experimental.metaorder_shadow import classer_stade  # noqa: E402
from hl_observer.experimental.metaorder_l2_tape import resume_book  # noqa: E402


def _book(bid, ask, taille_bid=10.0, taille_ask=10.0):
    return {"time": 1_700_000_000_000,
            "levels": [[{"px": str(bid - i * 0.01), "sz": str(taille_bid), "n": 1} for i in range(5)],
                       [{"px": str(ask + i * 0.01), "sz": str(taille_ask), "n": 1} for i in range(5)]]}


def _meta(t0, t1, sens):
    return {"t0": t0, "t1": t1, "sens": sens}


# ═══════════════ cohérence avec les stades existants ═══════════════
def test_les_stades_restent_synchronises_avec_metaorder_shadow():
    """Si `classer_stade` évolue, ce test tombe : pas de vocabulaire divergent en silence."""
    produits = {
        classer_stade(0, 3, {"reversal": True}),
        classer_stade(0, 3, {"reversal": False}),
        classer_stade(1, 3, {"reversal": False}),
        classer_stade(1, 3, {"reversal": False, "fraction_executed": 0.9}),
    }
    assert produits <= set(TOX.STADES)
    assert "LATE_STAGE" in TOX.STADES_TARDIFS and "REVERSAL" in TOX.STADES_TARDIFS


# ═══════════════ 1. crowding ═══════════════
def test_metaordres_concurrents_comptes_par_sens():
    metas = [_meta(0, 1_000, 1), _meta(500, 2_000, 1), _meta(0, 1_000, -1)]
    r = TOX.metaordres_concurrents(metas, t_ms=800, sens=1)
    assert r["meme_sens"] == 2 and r["sens_oppose"] == 1 and r["encombre"] is True


def test_metaordre_termine_hors_fenetre_nest_plus_concurrent():
    r = TOX.metaordres_concurrents([_meta(0, 1_000, 1)], t_ms=500_000, sens=1, fenetre_ms=60_000)
    assert r["meme_sens"] == 0 and r["encombre"] is False


def test_sens_inconnu_nest_pas_devine():
    r = TOX.metaordres_concurrents([_meta(0, 1_000, 1)], t_ms=500, sens=0)
    assert r["encombre"] is None and r["raison"] == "SENS_INCONNU"


# ═══════════════ 2. imbalance ═══════════════
def test_imbalance_extreme_et_non_mesurable():
    desequilibre = TOX.imbalance_extreme(resume_book(_book(100.0, 100.1, taille_bid=90.0, taille_ask=10.0)))
    equilibre = TOX.imbalance_extreme(resume_book(_book(100.0, 100.1, taille_bid=10.0, taille_ask=10.0)))
    assert desequilibre["extreme"] is True and desequilibre["ratio"] > 0.6
    assert equilibre["extreme"] is False
    absent = TOX.imbalance_extreme(None)
    assert absent["extreme"] is None and absent["raison"] == "CARNET_NON_MESURABLE"


# ═══════════════ 3. profondeur reconstruite / prix déjà parti ═══════════════
def test_profondeur_qui_remonte_alors_que_le_prix_est_parti_signale_le_retard():
    r = TOX.profondeur_reconstruite_prix_parti(
        resume_avant=resume_book(_book(100.0, 100.1, taille_bid=5.0, taille_ask=5.0)),
        resume_apres=resume_book(_book(100.3, 100.4, taille_bid=50.0, taille_ask=50.0)),
        mid_avant=100.05, mid_apres=100.35, sens=1)
    assert r["profondeur_en_hausse"] is True and r["prix_deja_parti"] is True and r["en_retard"] is True
    assert r["deplacement_bps"] > 15.0


def test_prix_immobile_nest_pas_un_retard_meme_si_la_profondeur_monte():
    r = TOX.profondeur_reconstruite_prix_parti(
        resume_avant=resume_book(_book(100.0, 100.1, taille_bid=5.0, taille_ask=5.0)),
        resume_apres=resume_book(_book(100.0, 100.1, taille_bid=50.0, taille_ask=50.0)),
        mid_avant=100.05, mid_apres=100.05, sens=1)
    assert r["profondeur_en_hausse"] is True and r["prix_deja_parti"] is False and r["en_retard"] is False


def test_mid_absent_reste_non_mesurable_et_ne_conclut_pas():
    r = TOX.profondeur_reconstruite_prix_parti(
        resume_avant=resume_book(_book(100.0, 100.1)), resume_apres=resume_book(_book(100.0, 100.1)),
        mid_avant=None, mid_apres=None, sens=1)
    assert r["en_retard"] is None and r["raison"] == "MID_NON_MESURABLE"


# ═══════════════ 4. markout ═══════════════
def test_markout_signe_selon_le_sens():
    assert TOX.markout_adverse_bps(100.0, 99.5, 1) < 0        # long, prix baisse = adverse
    assert TOX.markout_adverse_bps(100.0, 99.5, -1) > 0       # short, prix baisse = favorable
    assert TOX.markout_adverse_bps(None, 99.5, 1) is None
    assert TOX.markout_adverse_bps(100.0, 99.5, 0) is None


# ═══════════════ la porte ═══════════════
def test_gate_refuse_un_stade_tardif():
    g = TOX.gate_toxicite(stade="LATE_STAGE", crowding={"encombre": False, "meme_sens": 0},
                          imbalance={"extreme": False}, retard={"en_retard": False}, markout_bps=1.0)
    assert g["verdict"] == "LATE_OR_CROWDED_NO_TRADE" and "STADE_LATE_STAGE" in g["motifs"]


def test_gate_refuse_un_marche_encombre():
    g = TOX.gate_toxicite(stade="CONTINUATION", crowding={"encombre": True, "meme_sens": 3},
                          imbalance={"extreme": False}, retard={"en_retard": False}, markout_bps=1.0)
    assert g["verdict"] == "LATE_OR_CROWDED_NO_TRADE"
    assert "CROWDING_3_METAORDRES_MEME_SENS" in g["motifs"]


def test_gate_sabstient_quand_une_mesure_manque():
    g = TOX.gate_toxicite(stade="CONTINUATION", crowding=None, imbalance={"extreme": False},
                          retard={"en_retard": False}, markout_bps=0.0)
    assert g["verdict"] == "ABSTAIN_UNMEASURABLE" and "CROWDING" in g["non_mesurables"]


def test_gate_autorise_seulement_en_shadow_et_ne_promeut_jamais():
    g = TOX.gate_toxicite(stade="FIRST_SLICE", crowding={"encombre": False, "meme_sens": 0},
                          imbalance={"extreme": False}, retard={"en_retard": False}, markout_bps=2.0)
    assert g["verdict"] == "ALLOW_SHADOW"
    assert g["shadow"] is True and g["promotion_possible"] is False and g["real_execution"] is False


def test_un_refus_prime_sur_une_mesure_manquante():
    g = TOX.gate_toxicite(stade="REVERSAL", crowding=None, imbalance=None, retard=None, markout_bps=None)
    assert g["verdict"] == "LATE_OR_CROWDED_NO_TRADE"


# ═══════════════ ablation ═══════════════
def test_ablation_refuse_de_conclure_sans_echantillon():
    episodes = [{"net_bps": 1.0, "verdict": "ALLOW_SHADOW"} for _ in range(5)]
    a = TOX.ablation_gate(episodes)
    assert a["statut"] == "AMELIORATION_NON_MESURABLE" and a["delta_bps"] is None


def test_ablation_mesure_le_gain_du_gate_sans_le_promouvoir():
    episodes = ([{"net_bps": 2.0, "verdict": "ALLOW_SHADOW"} for _ in range(30)]
                + [{"net_bps": -10.0, "verdict": "LATE_OR_CROWDED_NO_TRADE"} for _ in range(10)])
    a = TOX.ablation_gate(episodes)
    assert a["statut"] == "MESURE" and a["n_refuses"] == 10
    assert a["net_moyen_avec_gate"] > a["net_moyen_sans_gate"] and a["gate_utile"] is True
    assert a["promotion_possible"] is False


# ═══════════════ sécurité ═══════════════
def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "experimental" / "metaorder_toxicite.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans metaorder_toxicite: %s" % interdit
