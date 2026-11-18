"""La conduite du labo par tranches : découper d'après la densité réelle, ne rien fabriquer.

Les six journées du corpus sont inégales — 2 172 496 fills le 13/11 contre 476 078 le 18/11 — donc
un découpage calendaire donnerait une tranche de ~7 Go et une de ~1,5 Go. Ces tests verrouillent le
découpage par densité, la contiguïté des tranches, et le refus de transformer une tranche en échec
silencieux.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.backtesting import agregation_tranches as AG
from tools import conduire_labo_par_tranches as CD

HEURE = 3_600_000


def _ruban(tmp_path, fills_par_heure):
    """Un ruban où l'heure `i` porte `n` fills."""
    chemin = tmp_path / "runtime" / "data" / "vault_fills_live.jsonl"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="") as flux:
        for heure, nombre in enumerate(fills_par_heure):
            for index in range(nombre):
                flux.write(json.dumps({"ts_ms": (heure + 1) * HEURE + index, "coin": "BTC"}) + "\n")
    return chemin


# ───────────────────────── la mesure de densité ─────────────────────────

def test_la_densite_est_mesuree_PAR_PAS_de_temps(tmp_path):
    ruban = _ruban(tmp_path, [3, 0, 5])
    densite = CD.densite_par_pas(ruban)
    assert sorted(densite.values()) == [3, 5], "l'heure vide n'apparaît pas"
    assert len(densite) == 2


def test_un_ruban_ABSENT_rend_une_densite_vide_sans_lever(tmp_path):
    """Et c'est l'appelant qui décide : `main` rend 2 et dit que ce n'est pas un zéro."""
    assert CD.densite_par_pas(tmp_path / "jamais.jsonl") == {}


def test_une_ligne_SANS_horodatage_est_ignoree_pas_comptee_a_zero(tmp_path):
    chemin = tmp_path / "r.jsonl"
    with open(chemin, "w", encoding="utf-8", newline="") as flux:
        flux.write('{"coin":"BTC"}\n')
        flux.write(json.dumps({"ts_ms": HEURE, "coin": "BTC"}) + "\n")
    assert sum(CD.densite_par_pas(chemin).values()) == 1


# ───────────────────────── le découpage ─────────────────────────

def test_le_decoupage_respecte_le_budget_de_lignes():
    densite = {HEURE: 400, 2 * HEURE: 400, 3 * HEURE: 400}
    tranches = CD.decouper(densite, budget=500)
    assert len(tranches) == 3, "400 + 400 dépasse 500 : chaque heure va dans sa tranche"


def test_des_pas_legers_sont_REGROUPES():
    densite = {HEURE: 100, 2 * HEURE: 100, 3 * HEURE: 100}
    tranches = CD.decouper(densite, budget=500)
    assert len(tranches) == 1 and tranches[0] == (HEURE, 4 * HEURE - 1)


def test_les_tranches_sont_CONTIGUES_sans_trou_ni_recouvrement():
    """Le contrôle qui compte : c'est `couverture` qui le dira à l'agrégat."""
    densite = {h * HEURE: 300 for h in range(1, 8)}
    tranches = CD.decouper(densite, budget=500)
    assert len(tranches) > 1
    couv = AG.couverture(tranches)
    assert couv["continue"] is True, couv
    assert couv["trous"] == [] and couv["recouvrements"] == []


def test_un_pas_SEUL_au_dessus_du_budget_est_rendu_tel_quel():
    """Le casser séparerait des fills que la reconstruction doit voir ensemble."""
    tranches = CD.decouper({HEURE: 10_000}, budget=500)
    assert tranches == [(HEURE, 2 * HEURE - 1)], "une tranche lourde vaut mieux qu'un mensonge"


def test_une_densite_vide_ne_donne_AUCUNE_tranche():
    assert CD.decouper({}) == []


def test_les_pas_non_contigus_restent_couverts_sans_trou():
    """Un trou d'activité ne doit pas devenir un trou de COUVERTURE."""
    tranches = CD.decouper({HEURE: 100, 5 * HEURE: 100}, budget=500)
    assert AG.couverture(tranches)["continue"] is True


# ───────────────────────── la conduite ─────────────────────────

def test_chaque_tranche_est_lancee_UNE_fois_avec_ses_bornes(tmp_path):
    vues = []

    def lancer(_ws, tranche):
        vues.append(tranche)
        return {"status": "MORE_DATA", "net_pnl_usd": 1.0}

    tranches = [(1, HEURE), (HEURE + 1, 2 * HEURE)]
    resultat = CD.conduire(tmp_path, tranches, lancer=lancer, additifs=("net_pnl_usd",))
    assert vues == tranches
    assert resultat["agregat"]["totaux"]["net_pnl_usd"]["total"] == 2.0
    assert resultat["agregat"]["exploitable"] is True


def test_la_tranche_est_REPORTEE_dans_chaque_rapport(tmp_path):
    resultat = CD.conduire(
        tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"},
    )
    assert resultat["rapports"][0]["tranche"] == [1, HEURE]


def test_une_tranche_qui_LEVE_est_consignee_et_ne_devient_pas_un_zero(tmp_path):
    def lancer(_ws, tranche):
        if tranche[0] == 1:
            raise MemoryError("plus de place")
        return {"status": "MORE_DATA", "net_pnl_usd": 5.0}

    resultat = CD.conduire(
        tmp_path, [(1, HEURE), (HEURE + 1, 2 * HEURE)],
        lancer=lancer, additifs=("net_pnl_usd",),
    )
    assert resultat["incidents"][0]["erreur"] == "MemoryError"
    assert resultat["incidents"][0]["message"] == "plus de place"
    agregat = resultat["agregat"]
    assert agregat["exploitable"] is False
    assert agregat["raison_non_exploitable"] == "TRANCHE_SANS_RAPPORT"
    assert agregat["totaux"]["net_pnl_usd"]["total"] == 5.0, "le total reste lisible…"
    assert agregat["totaux"]["net_pnl_usd"]["complet"] is False, "…mais il est déclaré incomplet"


def test_un_rapport_NON_LISIBLE_est_refuse_comme_un_echec(tmp_path):
    resultat = CD.conduire(tmp_path, [(1, HEURE)], lancer=lambda _w, _t: "tout va bien")
    assert resultat["incidents"][0]["erreur"] == "RAPPORT_NON_LISIBLE"
    assert resultat["agregat"]["exploitable"] is False


def test_TOUTES_les_tranches_sont_tentees_meme_apres_un_echec(tmp_path):
    """Un échec au milieu ne doit pas priver les suivantes de leur mesure."""
    vues = []

    def lancer(_ws, tranche):
        vues.append(tranche[0])
        if tranche[0] == HEURE + 1:
            raise RuntimeError("au milieu")
        return {"status": "MORE_DATA"}

    CD.conduire(
        tmp_path,
        [(1, HEURE), (HEURE + 1, 2 * HEURE), (2 * HEURE + 1, 3 * HEURE)],
        lancer=lancer,
    )
    assert vues == [1, HEURE + 1, 2 * HEURE + 1]


def test_le_verdict_le_plus_faible_remonte_a_la_conduite(tmp_path):
    etats = iter(("PROVEN", "UNMEASURABLE"))
    resultat = CD.conduire(
        tmp_path, [(1, HEURE), (HEURE + 1, 2 * HEURE)],
        lancer=lambda _w, _t: {"status": next(etats)},
    )
    assert resultat["agregat"]["verdict"]["status"] == "UNMEASURABLE"


def test_la_conduite_est_PAPER_et_le_declare(tmp_path):
    resultat = CD.conduire(tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"})
    assert resultat["paper_read_only"] is True and resultat["real_execution"] is False
    assert resultat["schema"] == CD.SCHEMA


# ───────────────────────── la ligne de commande ─────────────────────────

def test_le_mode_plan_seulement_ne_lance_PAS_le_labo(tmp_path, capsys, monkeypatch):
    _ruban(tmp_path, [50, 50])

    def interdit(*_a, **_k):
        raise AssertionError("le labo ne doit pas tourner en mode plan")

    monkeypatch.setattr(CD, "_lanceur_reel", interdit)
    assert CD.main([str(tmp_path), "--plan-seulement", "--budget", "1000"]) == 0
    sortie = capsys.readouterr().out
    assert "100 fills" in sortie and "1 tranches" in sortie
    assert "continue=True" in sortie


def test_un_ruban_vide_rend_un_code_D_ERREUR_pas_un_succes(tmp_path, capsys):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_fills_live.jsonl").write_text("", encoding="utf-8")
    assert CD.main([str(tmp_path), "--plan-seulement"]) == 2
    assert "ce n'est pas un zéro" in capsys.readouterr().out


def test_le_plan_SIGNALE_une_tranche_au_dessus_du_budget(tmp_path, capsys):
    _ruban(tmp_path, [900])
    CD.main([str(tmp_path), "--plan-seulement", "--budget", "100"])
    assert "au-dessus du budget" in capsys.readouterr().out


@pytest.mark.parametrize("heures", (1, 3))
def test_le_pas_de_decoupage_est_reglable(tmp_path, heures):
    _ruban(tmp_path, [10, 10, 10])
    densite = CD.densite_par_pas(
        tmp_path / "runtime" / "data" / "vault_fills_live.jsonl", pas_ms=heures * HEURE)
    assert sum(densite.values()) == 30
    assert len(densite) == (3 if heures == 1 else 2)
