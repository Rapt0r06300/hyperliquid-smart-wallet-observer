"""Tests de l'ENREGISTREUR DE SCANS CARRY (21/07) — le trou de données n°1.

Ce qu'ils PROUVENT :
  * une ligne moche n'annule pas les 19 autres, et RIEN ne peut faire lever l'enregistreur ;
  * un champ absent reste ABSENT (jamais un 0 fabriqué), NaN/inf sont rejetés ;
  * les coins REFUSÉS sont enregistrés avec leur motif — un refus est une donnée ;
  * LIVE / BACKTEST / REPLAY / TEST_FIXTURE ne se mélangent JAMAIS à la relecture ;
  * append-only : une 2ᵉ passe n'écrase pas la 1ʳᵉ ; la rotation RENOMME, n'efface pas ;
  * le feeder appelle vraiment l'enregistreur (testé ≠ branché, la maladie du projet).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.backtesting import carry_scan_recorder as R

T0 = 1_760_000_000_000
H = 3_600_000


def _ligne(coin="BTC", **kw):
    d = {"coin": coin, "funding_bps_h": 0.125, "base_bps": 12.5, "liquidite_spot_usd": 400_000.0,
         "gain_net_24h_bps": 2.221, "levier_max": 10.0, "levier_utilise": 5.0, "viable": True}
    d.update(kw)
    return d


# ------------------------------------------------------------------ normalisation

def test_le_coin_est_normalise_en_majuscules():
    assert R.normaliser({"coin": " ethfi "}, ts_ms=T0)["coin"] == "ETHFI"


def test_sans_coin_il_n_y_a_pas_de_ligne():
    for brut in ({"coin": ""}, {"coin": None}, {}, "pas un dict", None, 42):
        assert R.normaliser(brut, ts_ms=T0) is None


@pytest.mark.parametrize("valeur", [None, float("nan"), float("inf"), float("-inf"),
                                    "0.125", True, [1]])
def test_un_champ_illisible_reste_ABSENT_jamais_zero(valeur):
    """Un zéro fabriqué ment plus qu'un trou avoué — et fausserait tout backtest."""
    l = R.normaliser({"coin": "BTC", "funding_bps_h": valeur}, ts_ms=T0)
    assert "funding_bps_h" not in l


def test_un_refus_est_une_donnee_avec_son_motif():
    l = R.normaliser({"coin": "ETHFI", "viable": False, "motif": "refuse : LIQUIDE"}, ts_ms=T0)
    assert l["viable"] is False and l["motif"] == "refuse : LIQUIDE"


def test_l_alerte_de_rupture_est_reduite_a_son_niveau():
    l = R.normaliser({"coin": "X", "alerte_rupture": {"niveau": "RUPTURE_HAUTE", "note": "…"}},
                     ts_ms=T0)
    assert l["alerte_rupture"] == "RUPTURE_HAUTE"


def test_les_champs_hors_liste_blanche_ne_passent_pas():
    l = R.normaliser({"coin": "X", "secret": "zzz", "cle_privee": "0xdead"}, ts_ms=T0)
    assert "secret" not in l and "cle_privee" not in l
    assert l["real_execution"] is False


def test_un_mode_inconnu_est_une_FAUTE_de_programmation_pas_une_donnee():
    with pytest.raises(ValueError):
        R.normaliser({"coin": "X"}, ts_ms=T0, mode="PROD")


# ------------------------------------------------------------------ écriture

def test_une_ligne_moche_n_annule_pas_les_autres(tmp_path):
    n = R.enregistrer(tmp_path, [_ligne("BTC"), "pas un dict", None, {"coin": ""},
                                 _ligne("ETH")], ts_ms=T0)
    assert n == 2
    assert {l["coin"] for l in R.charger(tmp_path)} == {"BTC", "ETH"}


def test_l_enregistreur_ne_LEVE_jamais_meme_sur_un_chemin_impossible(tmp_path):
    """Un enregistreur qui tue le feeder serait pire que l'absence de données."""
    fichier = tmp_path / "bloque"
    fichier.write_text("je suis un fichier, pas un dossier", encoding="utf-8")
    assert R.enregistrer(fichier, [_ligne()], ts_ms=T0) == 0        # 0 écrit, aucune exception


def test_append_only_une_2e_passe_n_ecrase_pas_la_1re(tmp_path):
    R.enregistrer(tmp_path, [_ligne("BTC")], ts_ms=T0)
    R.enregistrer(tmp_path, [_ligne("BTC"), _ligne("ETH")], ts_ms=T0 + H)
    lignes = R.charger(tmp_path)
    assert len(lignes) == 3
    assert sorted({l["ts_ms"] for l in lignes}) == [T0, T0 + H]


def test_la_rotation_RENOMME_elle_n_efface_pas(tmp_path):
    for i in range(3):
        R.enregistrer(tmp_path, [_ligne()], ts_ms=T0 + i * H, taille_max=1)
    archives = list((tmp_path / "runtime" / "replay").glob("carry_scan.*.jsonl"))
    assert archives, "aucune archive : la rotation a effacé au lieu de renommer"
    total = sum(len(a.read_text(encoding="utf-8").strip().splitlines()) for a in archives)
    total += len(R.charger(tmp_path))
    assert total == 3                                   # aucune observation perdue


def test_ecrire_zero_ligne_ne_cree_rien(tmp_path):
    assert R.enregistrer(tmp_path, []) == 0
    assert not (tmp_path / R.RELPATH).exists()


# ------------------------------------------------------------------ relecture

def test_les_modes_ne_se_melangent_JAMAIS(tmp_path):
    R.enregistrer(tmp_path, [_ligne("BTC")], ts_ms=T0, mode="LIVE")
    R.enregistrer(tmp_path, [_ligne("ETH")], ts_ms=T0, mode="BACKTEST")
    assert [l["coin"] for l in R.charger(tmp_path, mode="LIVE")] == ["BTC"]
    assert [l["coin"] for l in R.charger(tmp_path, mode="BACKTEST")] == ["ETH"]


def test_filtres_depuis_coins_limite(tmp_path):
    R.enregistrer(tmp_path, [_ligne("BTC"), _ligne("ETH")], ts_ms=T0)
    R.enregistrer(tmp_path, [_ligne("BTC")], ts_ms=T0 + 10 * H)
    assert len(R.charger(tmp_path, depuis_ms=T0 + H)) == 1
    assert len(R.charger(tmp_path, coins=["btc"])) == 2
    assert len(R.charger(tmp_path, limite=1)) == 1


def test_fichier_absent_ou_corrompu_donne_une_liste_VIDE_pas_une_exception(tmp_path):
    assert R.charger(tmp_path) == []
    p = tmp_path / R.RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ ceci n'est pas du json\n\n[1,2,3]\n", encoding="utf-8")
    assert R.charger(tmp_path) == []


def test_le_resume_dit_le_volume_reel_et_les_motifs_dominants(tmp_path):
    R.enregistrer(tmp_path, [_ligne("BTC"), _ligne("ETH"),
                             _ligne("PUMP", viable=False, motif="trop volatil")], ts_ms=T0)
    R.enregistrer(tmp_path, [_ligne("BTC")], ts_ms=T0 + 2 * H)
    r = R.resume(tmp_path)
    assert (r["lignes"], r["coins"], r["passes"], r["viables"]) == (4, 3, 2, 3)
    assert r["etendue_h"] == 2.0
    assert r["motifs_de_refus"] == {"trop volatil": 1}
    assert r["octets"] > 0 and r["vide"] is False


def test_le_resume_d_un_journal_vide_le_DIT(tmp_path):
    assert R.resume(tmp_path)["vide"] is True


# ------------------------------------------------------------------ testé ≠ branché

def test_le_feeder_APPELLE_vraiment_l_enregistreur():
    """La maladie du projet : un module testé que personne n'appelle. Le scan doit
    collecter une trace PAR COIN (viable ou refusé) et la passer à l'enregistreur."""
    src = (Path(__file__).resolve().parents[1] / "tools"
           / "ecrire_carry_spot_inputs.py").read_text(encoding="utf-8")
    assert "carry_scan_recorder" in src
    assert "traces.append(trace)" in src
    assert 'trace["motif"]' in src           # les refusés sont tracés, pas seulement les viables


def test_le_feeder_trace_AVANT_de_savoir_si_le_coin_est_viable():
    """La trace est initialisée avant la branche : un coin écarté tôt (base aberrante, spot
    mince) doit quand même laisser une ligne — sinon on n'enregistre que les gagnants,
    et c'est un biais de survivant dans nos propres données."""
    src = (Path(__file__).resolve().parents[1] / "tools"
           / "ecrire_carry_spot_inputs.py").read_text(encoding="utf-8")
    i_trace = src.index("trace = {\"coin\": c")
    i_raison = src.index("raison, inp = \"\", None")
    i_append = src.index("traces.append(trace)")
    assert i_raison < i_trace < i_append
