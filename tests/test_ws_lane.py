"""Tests du collecteur WS userFills de lane (cœur pur, sans réseau)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import collecter_userfills_ws_lane as L  # noqa: E402

NOW = 1_800_000_000_000


def _brut(**kw):
    base = {"coin": "ETH", "px": "2000.5", "sz": "1.5", "side": "B", "time": NOW - 1000,
            "dir": "Open Long", "tid": 42, "oid": 7, "hash": "0xabc", "startPosition": "0.0"}
    base.update(kw)
    return base


def _parse(fills, user="0xuser"):
    return L._normaliser({"user": user, "isSnapshot": False, "fills": fills},
                         user=user, received_at_ms=NOW, recv_mono_ns=None, connection_id="t")


def test_forward_emet_les_nouveaux():
    parsed = _parse([_brut(time=NOW - 1000, tid=1)])
    nouveaux, hw = L.filtrer_forward(parsed, None)
    assert len(nouveaux) == 1 and hw == parsed[0]["ts_ms"]


def test_forward_ignore_sous_high_water():
    parsed = _parse([_brut(time=NOW - 1000, tid=1)])
    nouveaux, hw = L.filtrer_forward(parsed, parsed[0]["ts_ms"])
    assert nouveaux == [] and hw == parsed[0]["ts_ms"]


def test_forward_high_water_est_le_max():
    parsed = _parse([_brut(time=NOW - 3000, tid=1), _brut(time=NOW - 1000, tid=2)])
    nouveaux, hw = L.filtrer_forward(parsed, NOW - 2000)
    assert len(nouveaux) == 1 and hw == NOW - 1000  # seul le plus récent, hw=max


def test_high_water_snapshot():
    parsed = _parse([_brut(time=NOW - 5000, tid=1), _brut(time=NOW - 2000, tid=2)])
    assert L.high_water_snapshot(parsed, NOW) == NOW - 2000
    assert L.high_water_snapshot([], NOW) == NOW  # snapshot vide -> maintenant


def test_charger_leaders_et_shard(tmp_path):
    cfg = tmp_path / "config" / "copy_vault_leaders.json"
    cfg.parent.mkdir(parents=True)
    vaults = [f"0x{i:040x}" for i in range(20)] + ["pas_une_adresse", "0x"]
    cfg.write_text(json.dumps({"vaults": vaults}), encoding="utf-8")
    lus = L._charger_leaders(tmp_path, "config/copy_vault_leaders.json")
    assert len(lus) == 20 and all(v.startswith("0x") for v in lus)


def test_normaliser_rest_et_ws_identiques():
    # un fill passé par _normaliser (REST ou WS) donne la même identité de dédup
    from hl_observer.collection.userfills_resilience import cle_dedup_fill
    a = _parse([_brut(tid=9)])[0]
    b = _parse([_brut(tid=9)])[0]
    assert cle_dedup_fill(a) == cle_dedup_fill(b)


# ------------------------------------- choix des slots WS (defaut corrige le 21/11/2026)
def test_les_slots_vont_aux_leaders_les_plus_actifs(tmp_path):
    """La lane gardait les 10 PREMIERS DANS L'ORDRE DU FICHIER, sans regarder l'activite.

    Avec 120 leaders suivis et 4 lanes, chaque lane recevait ~30 candidats, en gardait 10
    au hasard de l'ordre et jetait les 20 autres. Le selecteur du depot existait, teste,
    et n'etait appele par AUCUN code de production.
    """
    candidats = ["0x%02d" % i + "a" * 8 for i in range(1, 13)]
    # L'explorer mesure : les trois derniers sont les plus actifs.
    rangs = {candidats[-1].lower(): 900.0, candidats[-2].lower(): 800.0,
             candidats[-3].lower(): 700.0}
    choix = L.choisir_les_slots(candidats, rangs, slots=4, challengers=1)
    assert choix["core"] == [candidats[-1], candidats[-2], candidats[-3]]
    assert len(choix["retenus"]) == 4
    assert choix["source_rang"].endswith("leaders_actifs_classement.json")
    assert choix["classes"] == 3 and choix["candidats"] == 12


def test_un_slot_reste_pour_l_exploration(tmp_path):
    """Un leader devenu actif depuis le dernier classement doit pouvoir etre vu."""
    candidats = ["0x%02d" % i + "b" * 8 for i in range(1, 9)]
    rangs = {c.lower(): float(100 - i) for i, c in enumerate(candidats[:5])}
    choix = L.choisir_les_slots(candidats, rangs, slots=4, challengers=2)
    assert len(choix["core"]) == 2
    assert len(choix["challengers"]) == 2
    # Les challengers ne doublonnent jamais le CORE : un slot rare ne se gaspille pas.
    assert not set(choix["core"]) & set(choix["challengers"])
    assert len(set(choix["retenus"])) == 4


def test_sans_classement_on_garde_l_ordre_ET_on_le_declare(tmp_path):
    """Fail-honest : ne pas savoir classer ne doit pas ressembler a un classement."""
    candidats = ["0x%02d" % i + "c" * 8 for i in range(1, 7)]
    choix = L.choisir_les_slots(candidats, {}, slots=3)
    assert choix["retenus"] == candidats[:3]
    assert "absent" in choix["source_rang"]
    assert choix["classes"] == 0


def test_le_classement_illisible_ne_fabrique_pas_de_rangs(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "leaders_actifs_classement.json").write_text(
        "{ pas du json", encoding="utf-8")
    assert L.charger_rangs(tmp_path) == {}


def test_le_classement_lu_ne_garde_que_des_scores_numeriques(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "leaders_actifs_classement.json").write_text(
        '{"actifs": [{"vault": "0xAAbb", "score": 12.5}, {"vault": "0xcc", "score": "haut"},'
        ' {"vault": "", "score": 3}, {"score": 9}]}', encoding="utf-8")
    assert L.charger_rangs(tmp_path) == {"0xaabb": 12.5}


def test_les_quatre_lanes_couvrent_le_top_global_sans_chevauchement():
    """LE gain mesurable : a nombre de slots egal, on ecoute les leaders les plus actifs.

    Avant, chaque lane prenait `i % 4` des leaders DANS L'ORDRE DU FICHIER puis gardait
    les 10 premiers de sa tranche : l'union etait 40 leaders arbitraires. Avec
    l'orchestrateur, l'union des 4 lanes est le top 40 du classement GLOBAL.
    """
    leaders = ["0x%03d" % i + "d" * 8 for i in range(1, 101)]      # 100 leaders
    # Le classement est l'INVERSE de l'ordre du fichier : le dernier est le meilleur.
    rangs = {c.lower(): float(i) for i, c in enumerate(leaders)}
    attendu = set(sorted(leaders, key=lambda c: -rangs[c.lower()])[:40])

    union, par_lane = set(), []
    for index in range(4):
        choix = L.choisir_les_slots(leaders, rangs, slots=10, shard_count=4,
                                    shard_index=index, challengers=0)
        par_lane.append(set(choix["retenus"]))
        assert len(choix["retenus"]) == 10
        union |= set(choix["retenus"])

    assert union == attendu, "l'union des lanes n'est pas le top 40 du classement"
    for i in range(4):
        for j in range(i + 1, 4):
            assert not par_lane[i] & par_lane[j], "deux lanes ecoutent le meme leader"


def test_un_leader_sans_activite_mesuree_ne_prend_pas_de_slot_rare():
    """Le quota WS est de 10 users/IP : un score nul retombe sur le poll, qui n'en a pas."""
    actifs = ["0x%02d" % i + "e" * 8 for i in range(1, 4)]
    inconnus = ["0x%02d" % i + "f" * 8 for i in range(1, 20)]
    rangs = {c.lower(): float(10 - i) for i, c in enumerate(actifs)}
    choix = L.choisir_les_slots(actifs + inconnus, rangs, slots=10, shard_count=1,
                                shard_index=0, challengers=0)
    assert choix["core"] == actifs          # les 3 mesures actives, dans l'ordre du rang
    assert choix["classes"] == 3
    assert len(choix["retenus"]) == 3, "un score nul ne doit pas acheter un slot WS"


# ------------------------- prediction locale : DEMOTION seulement (biais de selection)
def test_un_leader_ecoute_et_devenu_muet_libere_son_slot():
    """`activite_predictive` est cable en DEMOTION, jamais en promotion.

    Classer par les fills deja captes nourrirait le signal avec sa propre selection :
    seuls les leaders deja ecoutes auraient un historique, et les slots se figeraient sur
    eux pour toujours. La prediction ne sert donc qu'a LIBERER un slot.
    """
    leaders = ["0x%02d" % i + "g" * 8 for i in range(1, 6)]
    rangs = {c.lower(): float(100 - i) for i, c in enumerate(leaders)}
    # Le mieux classe est ecoute depuis longtemps mais n'a plus rien produit.
    vieux = 1_000_000_000_000
    historiques = {leaders[0].lower(): [vieux, vieux + 1000]}
    choix = L.choisir_les_slots(leaders, rangs, slots=2, challengers=0,
                                historiques=historiques, now_ms=vieux + 50 * 3_600_000)
    assert leaders[0] in choix["demis_sans_activite"]
    assert leaders[0] not in choix["retenus"], "le muet garde son slot rare"
    assert choix["retenus"][0] == leaders[1], "le suivant au classement ne monte pas"


def test_un_leader_jamais_ecoute_n_est_jamais_demis():
    """Sans historique, aucun jugement : c'est ce qui empeche le biais de selection."""
    leaders = ["0x%02d" % i + "h" * 8 for i in range(1, 4)]
    rangs = {c.lower(): 10.0 for c in leaders}
    choix = L.choisir_les_slots(leaders, rangs, slots=3, challengers=0, historiques={})
    assert choix["demis_sans_activite"] == []
    assert set(choix["retenus"]) == set(leaders)


def test_l_historique_se_lit_borne_et_sans_ligne_coupee(tmp_path):
    """Le ruban atteint des gigaoctets : la lecture est bornee par la FIN du fichier."""
    tape = tmp_path / "ruban.jsonl"
    maintenant = 1_700_000_000_000
    lignes = [json.dumps({"vault": "0xAA", "ts_ms": maintenant - 1000}),
              json.dumps({"vault": "0xbb", "ts_ms": maintenant - 2000}),
              json.dumps({"vault": "0xcc", "ts_ms": maintenant - 99 * 3_600_000}),
              "{ ligne tronquee"]
    tape.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    hist = L.historiques_recents(tmp_path, tape, now_ms=maintenant)
    assert set(hist) == {"0xaa", "0xbb"}, hist      # minuscules, hors fenetre exclu
    assert hist["0xaa"] == [maintenant - 1000]


def test_un_ruban_absent_ne_fabrique_pas_d_historique(tmp_path):
    assert L.historiques_recents(tmp_path, tmp_path / "rien.jsonl") == {}


def test_le_seuil_de_mutisme_est_encadre_par_la_mesure():
    """Comparer la prediction a ZERO ne marche pas : c'est une moyenne exponentielle.

    Mesures du 21/11/2026 : 2 fills dans la derniere minute => 42,7 fills prevus sur la
    fenetre ; muet depuis 50 h => 3,7e-91. Le seuil doit vivre ENTRE les deux, et assez
    bas pour ne rien decider dans la zone grise.
    """
    assert 0.0 < L.SEUIL_PREVU_MUET < 1.0
    assert L.SEUIL_PREVU_MUET > 3.7e-91


def test_un_leader_actif_garde_son_slot_malgre_l_historique():
    """La demotion ne doit frapper que les muets : un actif observe reste ecoute."""
    leaders = ["0x%02d" % i + "i" * 8 for i in range(1, 4)]
    rangs = {c.lower(): float(50 - i) for i, c in enumerate(leaders)}
    maintenant = 1_700_000_000_000
    historiques = {leaders[0].lower(): [maintenant - 60_000, maintenant - 30_000]}
    choix = L.choisir_les_slots(leaders, rangs, slots=2, challengers=0,
                                historiques=historiques, now_ms=maintenant)
    assert choix["demis_sans_activite"] == []
    assert leaders[0] in choix["retenus"]
