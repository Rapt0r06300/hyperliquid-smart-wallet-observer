"""L'INSTRUMENT de la comparaison avant/après sur la découverte des rafales (17/11/2026).

Un instrument qui se trompe ferait croire à un progrès, ou en cacherait un. On le teste sur des cas
dont on connaît la réponse à la main.
"""
from __future__ import annotations

import json

import mesurer_decouverte_rafales as M

MIN = 60_000


def test_decoupage_un_silence_de_45_min_ouvre_une_nouvelle_rafale():
    instants = [0, 1 * MIN, 2 * MIN, 47 * MIN, 48 * MIN, 200 * MIN]
    assert M.decouper_en_rafales(instants) == [[0, 1 * MIN, 2 * MIN], [47 * MIN, 48 * MIN], [200 * MIN]]


def test_decoupage_la_borne_du_silence_est_incluse():
    assert M.decouper_en_rafales([0, 45 * MIN]) == [[0], [45 * MIN]]
    assert M.decouper_en_rafales([0, 45 * MIN - 1]) == [[0, 45 * MIN - 1]]


def test_decoupage_ecarte_les_rafales_commencees_avant_le_direct():
    assert M.decouper_en_rafales([0, MIN, 100 * MIN], debut_ms=50 * MIN) == [[100 * MIN]]


def test_decoupage_vide():
    assert M.decouper_en_rafales([]) == []


def test_rafale_vue_en_retard_les_fills_d_avant_sont_manques():
    complet = {"0xa": [0, 10, 20, 30, 40]}
    bilan = M.mesurer(complet, {"0xa": [30, 40]})
    assert bilan["fills"] == 5 and bilan["fills_manques"] == 3
    assert bilan["part_manquee"] == 0.6 and bilan["rafales_jamais_vues"] == 0
    assert bilan["plus_grosses_rafales"][0]["decouverte_ms"] == 30


def test_rafale_jamais_vue_tout_est_manque_et_c_est_compte_a_part():
    bilan = M.mesurer({"0xa": [0, 10, 20]}, {})
    assert bilan["fills_manques"] == 3 and bilan["rafales_jamais_vues"] == 1
    assert bilan["plus_grosses_rafales"][0]["decouverte_ms"] is None


def test_rafale_vue_des_le_premier_fill_rien_n_est_manque():
    bilan = M.mesurer({"0xa": [0, 10]}, {"0xa": [0, 10]})
    assert bilan["fills_manques"] == 0 and bilan["part_manquee"] == 0.0


def test_un_fill_direct_d_une_AUTRE_rafale_ne_compte_pas_pour_celle_ci():
    complet = {"0xa": [0, 10, 100 * MIN, 100 * MIN + 5]}
    bilan = M.mesurer(complet, {"0xa": [100 * MIN]})
    assert bilan["rafales"] == 2 and bilan["rafales_jamais_vues"] == 1
    assert bilan["fills_manques"] == 2, "la première rafale entière ; rien de la seconde"


def test_l_alerte_promeut_a_la_page_suivante_pas_avant():
    complet = {"0xa": [0, 100_000, 200_000, 300_000, 400_000]}
    bilan = M.mesurer(complet, {}, {"0xa": [60_000]}, page_ms=150_000)
    # alerte à 60 s, abonné à 210 s : les fills à 0, 100 et 200 s restent manqués
    assert bilan["fills_manques"] == 5 and bilan["fills_manques_avec_alerte"] == 3
    assert bilan["part_manquee_avec_alerte"] == 0.6 and bilan["rafales_sans_alerte"] == 0


def test_l_alerte_ne_fait_jamais_pire_que_le_direct_reel():
    complet = {"0xa": [0, 10, 20, 30]}
    bilan = M.mesurer(complet, {"0xa": [10]}, {"0xa": [25]}, page_ms=150_000)
    assert bilan["fills_manques"] == 1 and bilan["fills_manques_avec_alerte"] == 1


def test_sans_alerte_la_borne_egale_le_reel_et_le_dit():
    bilan = M.mesurer({"0xa": [0, 10]}, {"0xa": [10]}, {})
    assert bilan["fills_manques_avec_alerte"] == bilan["fills_manques"] == 1
    assert bilan["rafales_sans_alerte"] == 1


def test_aucun_fill_les_parts_sont_INCONNUES_pas_nulles():
    bilan = M.mesurer({}, {})
    assert bilan["fills"] == 0 and bilan["part_manquee"] is None and bilan["part_manquee_avec_alerte"] is None


def test_le_bilan_est_marque_paper():
    bilan = M.mesurer({"0xa": [0]}, {})
    assert bilan["paper_read_only"] is True and bilan["real_execution"] is False
    assert bilan["schema_version"] == M.SCHEMA


def _ecrire(chemin, lignes):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="") as flux:
        flux.write("\n".join(json.dumps(l) for l in lignes) + "\n")


def test_bout_en_bout_sur_des_rubans(tmp_path, capsys):
    t0 = 1_800_000_000_000
    _ecrire(tmp_path / M.RUBAN_DIRECT, [
        {"vault": "0xA", "ts_ms": t0, "source": "LIVE_WS", "isSnapshot": False, "tid": 1},
        {"vault": "0xA", "ts_ms": t0 + 100 * MIN + 40, "source": "LIVE_WS", "isSnapshot": False, "tid": 13},
        {"vault": "0xA", "ts_ms": t0 + 100 * MIN + 41, "source": "LIVE_WS", "isSnapshot": True, "tid": 99},
    ])
    _ecrire(tmp_path / M.RUBAN_COMPLET, [
        {"vault": "0xa", "ts_ms": t0, "tid": 1},
        {"vault": "0xa", "ts_ms": t0 + 100 * MIN, "tid": 10},
        {"vault": "0xa", "ts_ms": t0 + 100 * MIN + 20, "tid": 11},
        {"vault": "0xa", "ts_ms": t0 + 100 * MIN + 20, "tid": 11},          # doublon de rattrapage
        {"vault": "0xa", "ts_ms": t0 + 100 * MIN + 40, "tid": 13},
        {"vault": "0xinconnu", "ts_ms": t0 + 5, "tid": 50},                   # jamais suivi en direct
    ])
    _ecrire(tmp_path / M.RUBAN_POLL, [{"vault": "0xa", "received_at_ms": t0 + 100 * MIN + 10, "time": t0 + 100 * MIN}])
    assert M.main(["--root", str(tmp_path)]) == 0
    rapport = json.loads((tmp_path / M.RAPPORT).read_text(encoding="utf-8"))
    assert rapport["leaders"] == 1 and rapport["rafales"] == 2 and rapport["fills"] == 4
    assert rapport["fills_manques"] == 2, "les deux fills avant le premier vu de la seconde rafale"
    assert rapport["rafales_jamais_vues"] == 0 and rapport["debut_du_direct_ms"] == t0
    assert "manqués par le direct" in capsys.readouterr().out


def test_sans_leader_commun_l_outil_le_dit_et_n_ecrit_rien(tmp_path, capsys):
    assert M.main(["--root", str(tmp_path)]) == 2
    assert not (tmp_path / M.RAPPORT).exists()
    assert "rien à mesurer" in capsys.readouterr().out
