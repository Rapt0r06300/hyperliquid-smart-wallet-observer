"""Les quatre façons de mentir en agrégeant des tranches, et le refus de chacune.

Le labo lit désormais une tranche de temps à la fois (le corpus entier demandait ~52 Go). Le danger
n'est pas la découpe : c'est la recombinaison. Ces tests verrouillent les refus.
"""
from __future__ import annotations

from hl_observer.backtesting import agregation_tranches as AG

JOUR = 86_400_000


def _r(**kw):
    return dict(kw)


# ───────────────────────── 1. le verdict optimiste ─────────────────────────

def test_une_seule_tranche_non_mesurable_emporte_tout_l_agregat():
    """Cinq MORE_DATA et une UNMEASURABLE ne font pas un MORE_DATA."""
    rapports = [_r(status="MORE_DATA") for _ in range(5)] + [_r(status="UNMEASURABLE", reason="X")]
    v = AG.verdict_global(rapports)
    assert v["status"] == "UNMEASURABLE"
    assert v["tranche_la_plus_faible"] == 5 and v["reason"] == "X"
    assert v["unanime"] is False


def test_l_etat_le_plus_faible_est_pris_meme_entre_deux_etats_positifs():
    v = AG.verdict_global([_r(status="PROVEN"), _r(status="PROMISING"), _r(status="PROVEN")])
    assert v["status"] == "PROMISING" and v["tranche_la_plus_faible"] == 1


def test_un_etat_INCONNU_est_traite_comme_le_plus_faible_jamais_ignore():
    v = AG.verdict_global([_r(status="PROVEN"), _r(status="SUPER_BIEN")])
    assert v["status"] == "UNMEASURABLE", "un état hors nomenclature ne vaut pas une preuve"
    assert v["etats_par_tranche"]["UNMEASURABLE"] == 1


def test_un_status_ABSENT_est_traite_comme_le_plus_faible():
    v = AG.verdict_global([_r(status="PROVEN"), _r()])
    assert v["status"] == "UNMEASURABLE"


def test_AUCUNE_tranche_ne_vaut_pas_rien_a_signaler():
    v = AG.verdict_global([])
    assert v["status"] == "UNMEASURABLE" and v["reason"] == "AUCUNE_TRANCHE"


def test_l_unanimite_est_declaree_quand_elle_existe():
    v = AG.verdict_global([_r(status="MORE_DATA"), _r(status="MORE_DATA")])
    assert v["unanime"] is True and v["status"] == "MORE_DATA"


# ───────────────────────── 2. la moyenne de moyennes ─────────────────────────

def test_un_taux_se_recompose_en_sommant_les_DEUX_termes():
    """Le piège : une journée de 40 signaux ne doit pas peser autant qu'une de 40 000."""
    rapports = [
        _r(executables=40, signaux=40),        # taux journalier 100 %
        _r(executables=0, signaux=40_000),     # taux journalier 0 %
    ]
    t = AG.ratio_global(rapports, numerateur="executables", denominateur="signaux")
    assert t["denominateur"] == 40_040 and t["numerateur"] == 40
    assert abs(t["taux"] - 40 / 40_040) < 1e-12, "la moyenne des taux aurait donné 50 %"
    assert t["mesurable"] is True


def test_le_denominateur_est_TOUJOURS_publie_avec_le_taux():
    t = AG.ratio_global([_r(a=1, b=4)], numerateur="a", denominateur="b")
    assert t["taux"] == 0.25 and t["denominateur"] == 4 and t["numerateur"] == 1


def test_un_denominateur_NUL_ne_donne_pas_un_taux_de_zero():
    t = AG.ratio_global([_r(a=0, b=0)], numerateur="a", denominateur="b")
    assert t["taux"] is None and t["mesurable"] is False
    assert t["raison"] == "DENOMINATEUR_ABSENT_OU_NUL"


def test_un_denominateur_MANQUANT_dans_une_tranche_rend_le_taux_non_mesurable():
    t = AG.ratio_global([_r(a=1, b=4), _r(a=1)], numerateur="a", denominateur="b")
    assert t["taux"] is None and t["raison"] == "DENOMINATEUR_INCOMPLET"


def test_un_numerateur_manquant_laisse_le_taux_mais_le_declare_incomplet():
    t = AG.ratio_global([_r(a=1, b=4), _r(b=6)], numerateur="a", denominateur="b")
    assert t["taux"] == 0.1 and t["mesurable"] is False and t["raison"] == "NUMERATEUR_INCOMPLET"


# ───────────────────────── 3. le trou qui devient un zéro ─────────────────────────

def test_une_cle_ABSENTE_n_est_pas_comptee_comme_un_zero():
    s = AG.sommer([_r(pnl=5.0), _r(), _r(pnl=-2.0)], "pnl")
    assert s["total"] == 3.0
    assert s["tranches_sans_la_cle"] == 1 and s["complet"] is False


def test_une_somme_complete_est_declaree_complete():
    s = AG.sommer([_r(n=2), _r(n=3)], "n")
    assert s["total"] == 5 and s["complet"] is True and isinstance(s["total"], int)


def test_un_booleen_n_est_pas_un_nombre():
    """`True` vaudrait 1 et gonflerait le total en silence."""
    s = AG.sommer([_r(n=True), _r(n=2)], "n")
    assert s["total"] == 2 and s["tranches_sans_la_cle"] == 1


def test_un_NaN_ou_un_infini_ne_contamine_pas_le_total():
    s = AG.sommer([_r(n=float("nan")), _r(n=float("inf")), _r(n=4)], "n")
    assert s["total"] == 4 and s["tranches_sans_la_cle"] == 2


def test_un_TROU_entre_deux_tranches_est_nomme():
    c = AG.couverture([(1, JOUR), (2 * JOUR, 3 * JOUR)])
    assert c["continue"] is False and c["raison"] == "TROU"
    assert c["trous"] == [[JOUR + 1, 2 * JOUR - 1]]


def test_un_RECOUVREMENT_est_nomme_car_il_compterait_deux_fois():
    c = AG.couverture([(1, 2 * JOUR), (JOUR, 3 * JOUR)])
    assert c["continue"] is False and c["raison"] == "RECOUVREMENT"
    assert c["recouvrements"] == [[JOUR, 2 * JOUR]]


def test_des_tranches_contigues_sont_continues():
    c = AG.couverture([(1, JOUR), (JOUR + 1, 2 * JOUR)])
    assert c["continue"] is True and c["etendue_ms"] == 2 * JOUR
    assert c["premier_ms"] == 1 and c["dernier_ms"] == 2 * JOUR


def test_l_ordre_des_tranches_n_a_pas_d_importance():
    a = AG.couverture([(JOUR + 1, 2 * JOUR), (1, JOUR)])
    assert a["continue"] is True and a["etendue_ms"] == 2 * JOUR


def test_une_tranche_ILLISIBLE_est_signalee_et_non_devinee():
    for mauvaise in ((0, 10), (10, 5), (1.0, 10), "hier", None, (5,)):
        c = AG.couverture([(1, JOUR), mauvaise])
        assert c["continue"] is False and c["raison"] == "TRANCHE_ILLISIBLE"
        assert c["tranches_illisibles"] == [1]


# ───────────────────────── 4. les jours comptés deux fois ─────────────────────────

def test_les_jours_sont_UNIS_jamais_additionnes():
    """Sinon le seuil de six journées distinctes se franchirait par simple découpage."""
    rapports = [
        _r(signal_coverage={"utc_days": ["2026-11-13", "2026-11-14"]}),
        _r(signal_coverage={"utc_days": ["2026-11-14", "2026-11-15"]}),
    ]
    j = AG.unir_les_jours(rapports)
    assert j["jours"] == ["2026-11-13", "2026-11-14", "2026-11-15"]
    assert j["distincts"] == 3, "l'addition aurait donné 4"


def test_une_tranche_sans_jours_declares_est_comptee_a_part():
    j = AG.unir_les_jours([_r(signal_coverage={"utc_days": ["2026-11-13"]}), _r(), _r(signal_coverage={})])
    assert j["distincts"] == 1 and j["tranches_sans_jours_declares"] == 2


# ───────────────────────── l'agrégat complet ─────────────────────────

def test_un_agregat_continu_et_complet_est_exploitable():
    tranches = [(1, JOUR), (JOUR + 1, 2 * JOUR)]
    rapports = [
        _r(status="MORE_DATA", net_pnl_usd=1.5, executables=10, signaux=100,
           signal_coverage={"utc_days": ["2026-11-13"]}),
        _r(status="MORE_DATA", net_pnl_usd=-0.5, executables=20, signaux=300,
           signal_coverage={"utc_days": ["2026-11-14"]}),
    ]
    a = AG.combiner(rapports, tranches=tranches,
                    additifs=("net_pnl_usd",), ratios=(("executables", "signaux"),))
    assert a["exploitable"] is True and "raison_non_exploitable" not in a
    assert a["verdict"]["status"] == "MORE_DATA"
    assert a["totaux"]["net_pnl_usd"]["total"] == 1.0
    assert a["taux"]["executables/signaux"]["denominateur"] == 400
    assert a["jours"]["distincts"] == 2
    assert a["paper_read_only"] is True and a["real_execution"] is False


def test_une_tranche_SANS_rapport_rend_l_agregat_non_exploitable():
    """Une tranche non évaluée n'a pas une contribution nulle : elle est inconnue."""
    a = AG.combiner([_r(status="MORE_DATA")], tranches=[(1, JOUR), (JOUR + 1, 2 * JOUR)])
    assert a["exploitable"] is False and a["raison_non_exploitable"] == "TRANCHE_SANS_RAPPORT"
    assert a["tranches_sans_rapport"] == 1


def test_un_TROU_rend_l_agregat_non_exploitable_meme_si_tout_est_vert():
    a = AG.combiner(
        [_r(status="PROVEN"), _r(status="PROVEN")],
        tranches=[(1, JOUR), (2 * JOUR, 3 * JOUR)],
    )
    assert a["exploitable"] is False and a["raison_non_exploitable"] == "TROU"
    assert a["verdict"]["status"] == "PROVEN", "le verdict reste lisible, c'est l'agrégat qui ne l'est pas"


def test_un_agregat_vide_le_dit_au_lieu_de_rendre_des_zeros():
    a = AG.combiner([], tranches=[], additifs=("net_pnl_usd",))
    assert a["exploitable"] is False and a["raison_non_exploitable"] == "AUCUNE_TRANCHE"
    assert a["totaux"]["net_pnl_usd"]["complet"] is False


def test_l_agregat_porte_toujours_son_PERIMETRE():
    """Un PnL sommé sans son étendue n'est comparable à rien."""
    a = AG.combiner([_r(status="MORE_DATA")], tranches=[(1, JOUR)], additifs=("net_pnl_usd",))
    assert a["tranches_demandees"] == 1 and a["couverture"]["etendue_ms"] == JOUR
    assert a["schema"] == AG.SCHEMA
def test_un_total_est_declare_INCOMPLET_des_qu_une_tranche_n_a_pas_rendu_de_rapport():
    """Le piège que `sommer` seul ne peut pas voir : il ignore ce qu'on ne lui donne pas.

    Défaut trouvé le 18/11 dans ce module même, par le test de la conduite : une tranche levant
    `MemoryError` laissait un total « complet » alors qu'un sixième du corpus manquait.
    """
    a = AG.combiner(
        [_r(status="MORE_DATA", net_pnl_usd=5.0, n=10, d=100)],
        tranches=[(1, JOUR), (JOUR + 1, 2 * JOUR)],
        additifs=("net_pnl_usd",), ratios=(("n", "d"),),
    )
    total = a["totaux"]["net_pnl_usd"]
    assert total["total"] == 5.0, "le total reste lisible"
    assert total["complet"] is False and total["raison"] == "TRANCHE_SANS_RAPPORT"
    assert total["tranches_sans_rapport"] == 1
    taux = a["taux"]["n/d"]
    assert taux["taux"] == 0.1 and taux["mesurable"] is False
    assert taux["raison"] == "TRANCHE_SANS_RAPPORT"


def test_sans_tranche_manquante_les_mesures_ne_sont_PAS_touchees():
    a = AG.combiner(
        [_r(status="MORE_DATA", net_pnl_usd=5.0, n=10, d=100)],
        tranches=[(1, JOUR)], additifs=("net_pnl_usd",), ratios=(("n", "d"),),
    )
    assert a["totaux"]["net_pnl_usd"]["complet"] is True
    assert a["taux"]["n/d"]["mesurable"] is True
    assert "tranches_sans_rapport" not in a["totaux"]["net_pnl_usd"]

