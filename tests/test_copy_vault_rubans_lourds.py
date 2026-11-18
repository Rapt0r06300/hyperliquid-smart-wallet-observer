"""LES TROIS RUBANS LOURDS DU LABO, PRODUITS EN FLUX — ET IDENTIQUES À L'ANCIEN CHEMIN.

Mesure du 18/11/2026 sur la fenêtre ouverte le 13/11 : 19,2 millions de lignes de fills et de
carnets, soit ~60,5 Go en dictionnaires contre 3 Go en flux. Le labo demandait soixante
gigaoctets à une machine qui en a trente-deux, s'arrêtait en `MEMOIRE_CRITIQUE` après 452 shards
sur 5 570, et concluait « trop peu de jours ».

Ces tests vérifient que le passage en flux ne change NI les octets des rubans, NI les filtres du
pont, NI les compteurs d'audit — et que les deux rubans de fills sortent d'une déduplication
UNIQUE.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

import pytest

from hl_observer.backtesting import copy_vault_rubans_lourds as RL
from hl_observer.backtesting import rubans_tri_externe as RT


def _fill(ts, *, vault="0x" + "a" * 40, coin="ETH", tid=1, px=2000.0, sz=1.0, signe=1,
          snapshot=False, source="LIVE_WS", **extra):
    return {"vault": vault, "coin": coin, "ts_ms": ts, "tid": tid, "px": px, "sz": sz,
            "signe": signe, "isSnapshot": snapshot, "source": source, "hash": f"0x{ts:x}",
            "oid": tid * 10, **extra}


def _carnet(recu, *, coin="ETH"):
    return {"coin": coin, "received_at_ms": recu, "exchange_ts_ms": recu - 400, "bid": 1999.0,
            "ask": 2001.0, "bids5": [[1999.0, 1.0]], "asks5": [[2001.0, 2.0]]}


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _lignes(p):
    texte = p.read_text(encoding="utf-8")
    return [json.loads(l) for l in texte.splitlines() if l.strip()]


# ───────────────────────── les clés, telles que le labo les compare ─────────────────────────

def test_l_identite_d_un_fill_est_celle_du_labo():
    ligne = _fill(100)
    assert RL.identite_fill(ligne) == (ligne["vault"], "ETH", 100, 1, ligne["hash"], 10, 2000.0, 1.0, 1)


def test_un_fill_EN_DIRECT_est_prefere_au_meme_fill_en_SNAPSHOT():
    assert RL.preference_fill(_fill(100, snapshot=False)) < RL.preference_fill(_fill(100, snapshot=True))


def test_l_identite_d_un_carnet_contient_ses_niveaux():
    a, b = _carnet(100), _carnet(100)
    b["bids5"] = [[1999.0, 9.0]]
    assert RT.empreinte(RL.identite_carnet(a)) != RT.empreinte(RL.identite_carnet(b))


# ───────────────────────── les deux rubans de fills ─────────────────────────

def test_les_DEUX_rubans_de_fills_sortent_d_une_SEULE_deduplication(tmp_path):
    """Un fill présent en snapshot ET en direct ne doit compter qu'une fois, dans le bon ruban."""
    lignes = [_fill(100, snapshot=True, source="SNAPSHOT"), _fill(100, snapshot=False),
              _fill(200, snapshot=True, source="SNAPSHOT"), _fill(300, snapshot=False)]
    bilan = RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter(lignes),
                                    fabrique_carnets=lambda: iter(()),
                                    dossier_temporaire=tmp_path / "t")
    assert bilan["identites_fills"] == 3 and bilan["doublons_fills"] == 1
    directs = _lignes(tmp_path / RL.RUBAN_FILLS_DIRECTS)
    historiques = _lignes(tmp_path / RL.RUBAN_FILLS_HISTORIQUES)
    assert [l["ts_ms"] for l in directs] == [100, 300], "le fill 100 est allé au direct, pas au snapshot"
    assert [l["ts_ms"] for l in historiques] == [200]
    assert all(l["isSnapshot"] is False for l in directs)
    assert all(l["isSnapshot"] is True for l in historiques)


def test_les_octets_sont_IDENTIQUES_a_l_ancien_chemin(tmp_path):
    """Le contrat : la référence en mémoire reproduit exactement l'ancien labo."""
    lignes = [_fill(300), _fill(100, snapshot=True, source="SNAPSHOT"), _fill(100), _fill(200, tid=7),
              _fill(200, tid=7, px=1.0), _fill(50, vault="0x" + "b" * 40)]
    RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter(lignes),
                            fabrique_carnets=lambda: iter(()), dossier_temporaire=tmp_path / "t")
    reference = tmp_path / "reference.jsonl"
    RT.ecrire_ruban_en_memoire(reference, lignes, cle_tri=RL.tri_fill, cle_identite=RL.identite_fill,
                               rang_preference=RL.preference_fill)
    attendu = [l for l in _lignes(reference) if l["isSnapshot"] is False]
    assert _lignes(tmp_path / RL.RUBAN_FILLS_DIRECTS) == attendu


def test_les_carnets_passent_par_le_meme_contrat(tmp_path):
    carnets = [_carnet(300), _carnet(100), _carnet(200, coin="BTC"), _carnet(100)]
    bilan = RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter(()),
                                    fabrique_carnets=lambda: iter(carnets),
                                    dossier_temporaire=tmp_path / "t")
    ruban = bilan["carnets"][RL.RUBAN_CARNETS]
    assert ruban["lignes_ecrites"] == 3 and ruban["doublons_ecartes"] == 1
    assert [l["received_at_ms"] for l in _lignes(tmp_path / RL.RUBAN_CARNETS)] == [100, 200, 300]


def test_un_corpus_vide_produit_trois_rubans_vides(tmp_path):
    bilan = RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter(()),
                                    fabrique_carnets=lambda: iter(()), dossier_temporaire=tmp_path / "t")
    for nom in (RL.RUBAN_FILLS_DIRECTS, RL.RUBAN_FILLS_HISTORIQUES, RL.RUBAN_CARNETS):
        assert (tmp_path / nom).read_bytes() == b""
    assert bilan["identites_fills"] == 0


# ───────────────────────── le tier SAFE, sans dupliquer les transformations ─────────────────────────

def _asset(famille, dataset="ds-1", sha="ab" * 32, connexion=None, continuite=True):
    manifeste = {"synchronization": {"connection_ids": [connexion]}} if connexion else {}
    return {"family": famille, "dataset_id": dataset, "sha256": sha, "manifest": manifeste,
            "_heartbeat_evidence_missing": not continuite}


def test_lignes_safe_appelle_la_transformation_DU_LABO_avec_la_provenance(tmp_path):
    vus = []

    def transformer(enveloppe, *, family, audit, **meta):
        vus.append((family, meta))
        return [{"n": enveloppe["i"]}]

    assets = [(tmp_path / "a.gz", _asset("copy_vault_fills", connexion="conn-1"))]
    compteurs: dict[str, int] = {}
    lignes = list(RL.lignes_safe(assets, familles=RL.FAMILLES_SAFE_FILLS, index_sha="cat-sha",
                                 transformer=transformer,
                                 charger_enveloppes=lambda _p: [{"i": 1}, {"i": 2}],
                                 payload_audit=Counter(), compteurs=compteurs))
    assert [l["n"] for l in lignes] == [1, 2] and compteurs["raw_frames"] == 2
    famille, meta = vus[0]
    assert famille == "copy_vault_fills"
    assert meta == {"source_dataset_id": "ds-1", "source_shard_sha256": "ab" * 32,
                    "source_catalog_sha256": "cat-sha", "source_continuity_proven": True,
                    "expected_connection_id": "conn-1"}


def test_lignes_safe_IGNORE_les_familles_non_demandees(tmp_path):
    assets = [(tmp_path / "a.gz", _asset("copy_vault_l2")),
              (tmp_path / "b.gz", _asset("copy_vault_fills"))]
    appels = []
    list(RL.lignes_safe(assets, familles=RL.FAMILLES_SAFE_FILLS, index_sha="x",
                        transformer=lambda e, **kw: [{"n": 1}],
                        charger_enveloppes=lambda p: appels.append(p) or [{"i": 0}]))
    assert appels == [tmp_path / "b.gz"], "le shard de carnets n'est même pas ouvert"


def test_un_shard_SAFE_illisible_est_COMPTE_et_n_arrete_pas_la_lecture(tmp_path):
    def charger(chemin):
        if chemin.name == "casse.gz":
            raise OSError("gzip tronque")
        return [{"i": 1}]

    assets = [(tmp_path / "casse.gz", _asset("copy_vault_fills")),
              (tmp_path / "bon.gz", _asset("copy_vault_fills"))]
    compteurs: dict[str, int] = {}
    lignes = list(RL.lignes_safe(assets, familles=RL.FAMILLES_SAFE_FILLS, index_sha="x",
                                 transformer=lambda e, **kw: [{"n": e["i"]}],
                                 charger_enveloppes=charger, compteurs=compteurs))
    assert [l["n"] for l in lignes] == [1] and compteurs["wrapper_rejections"] == 1


def test_les_observations_historiques_des_snapshots_sont_comptees(tmp_path):
    enveloppe = {"_raw": {"data": {"isSnapshot": True, "fills": [{}, {}, {}]}}}
    compteurs: dict[str, int] = {}
    list(RL.lignes_safe([(tmp_path / "s.gz", _asset("copy_vault_snapshot"))],
                        familles=RL.FAMILLES_SAFE_FILLS, index_sha="x",
                        transformer=lambda e, **kw: [], charger_enveloppes=lambda p: [enveloppe],
                        compteurs=compteurs))
    assert compteurs["historical_snapshot_shards"] == 1
    assert compteurs["historical_fill_observations"] == 3


def test_un_carnet_SAFE_refuse_est_compte_dans_l_audit(tmp_path):
    audit: Counter[str] = Counter()
    lignes = list(RL.lignes_safe([(tmp_path / "l.gz", _asset(RL.FAMILLE_SAFE_CARNETS))],
                                 familles=[RL.FAMILLE_SAFE_CARNETS], index_sha="x",
                                 transformer=lambda e, **kw: None,
                                 charger_enveloppes=lambda p: [{"_raw": {}}, {"_raw": {}}],
                                 payload_audit=audit, rend_une_liste=False))
    assert lignes == [] and audit["INVALID_OR_NONCAUSAL_L2_REJECTED"] == 2


# ───────────────────────── le tier LOCAL, avec les filtres du pont ─────────────────────────

def _faux_flux(lignes):
    def flux(_root, _retenus, *, famille, debut_ms=None, fin_ms=None, compteurs=None):
        return iter(lignes)
    return flux


def test_les_filtres_du_pont_LOCAL_sont_les_memes(tmp_path):
    lignes = [_fill(100), {"ts_ms": 1, "coin": "ETH"}, {"ts_ms": 2, "vault": "0xa"},
              {"vault": "0xa", "coin": "ETH", "ts_ms": "pas un entier"}]
    compteurs: dict[str, int] = {}
    gardees = list(RL.lignes_locales(tmp_path, [], famille="fills_forward", compteurs=compteurs,
                                     flux=_faux_flux(lignes)))
    assert len(gardees) == 1 and compteurs["lignes_refusees"] == 3
    assert gardees[0]["provenance_tier"] == "LOCAL"


def test_un_carnet_LOCAL_incomplet_est_refuse(tmp_path):
    bon = _carnet(100)
    sans_niveaux = {**_carnet(200), "bids5": []}
    sans_horloge = {**_carnet(300), "exchange_ts_ms": None}
    compteurs: dict[str, int] = {}
    gardees = list(RL.lignes_locales(tmp_path, [], famille="book_l2", compteurs=compteurs,
                                     flux=_faux_flux([bon, sans_niveaux, sans_horloge])))
    assert [l["received_at_ms"] for l in gardees] == [100] and compteurs["lignes_refusees"] == 2


def test_les_adresses_classees_ARCHIVE_ne_sont_jamais_rejouees(tmp_path):
    robot = "0x" + "b" * 40
    lignes = [_fill(100), _fill(200, vault=robot), _fill(300, vault=robot.upper())]
    compteurs: dict[str, int] = {}
    gardees = list(RL.lignes_locales(tmp_path, [], famille="fills_forward", archivees={robot},
                                     compteurs=compteurs, flux=_faux_flux(lignes)))
    assert len(gardees) == 1 and compteurs["fills_archive"] == 2, "la casse de l'adresse ne doit pas protéger un robot"


def test_un_carnet_n_est_jamais_ecarte_comme_une_adresse_archivee(tmp_path):
    """Le filtre des archives ne vaut que pour les fills : un carnet n'a pas de vault."""
    compteurs: dict[str, int] = {}
    gardees = list(RL.lignes_locales(tmp_path, [], famille="book_l2", archivees={"0xb" * 13},
                                     compteurs=compteurs, flux=_faux_flux([_carnet(100)])))
    assert len(gardees) == 1 and compteurs["fills_archive"] == 0


def test_la_lecture_LOCALE_est_deleguee_au_point_unique_du_coffre(tmp_path):
    """On ne duplique ni la vérification des SHA ni la fenêtre : `coffre_tranches` les porte."""
    import inspect

    source = inspect.getsource(RL.lignes_locales)
    assert "TR.selectionner" in source and "TR.flux" in source


@pytest.mark.parametrize("famille", list(RL.FAMILLES_LOCALES_FILLS))
def test_toutes_les_familles_de_fills_LOCALES_sont_filtrees_comme_des_fills(tmp_path, famille):
    gardees = list(RL.lignes_locales(tmp_path, [], famille=famille, flux=_faux_flux([_fill(1)])))
    assert len(gardees) == 1


# ───────── la préférence reproduit EXACTEMENT l'ordre d'entrée du labo ─────────
#
# Le labo insérait d'abord les lignes SAFE (en remplaçant un snapshot par un fill vu en direct),
# PUIS les lignes LOCAL par `setdefault` — donc une ligne LOCAL ne délogeait jamais une ligne SAFE,
# pas même un snapshot. Trois rangs, pas deux.

def _local(ligne):
    return {**ligne, "provenance_tier": "LOCAL"}


def test_les_trois_rangs_de_preference():
    assert RL.preference_fill(_fill(1)) == RL.RANG_SAFE_DIRECT
    assert RL.preference_fill(_fill(1, snapshot=True)) == RL.RANG_SAFE_SNAPSHOT
    assert RL.preference_fill(_local(_fill(1))) == RL.RANG_LOCAL
    assert RL.RANG_SAFE_DIRECT < RL.RANG_SAFE_SNAPSHOT < RL.RANG_LOCAL


def test_une_ligne_LOCALE_ne_deloge_JAMAIS_une_ligne_SAFE_meme_en_snapshot(tmp_path):
    lignes = [_fill(100, snapshot=True, source="SNAPSHOT"), _local(_fill(100, snapshot=False))]
    RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter(lignes),
                            fabrique_carnets=lambda: iter(()), dossier_temporaire=tmp_path / "t")
    historiques = _lignes(tmp_path / RL.RUBAN_FILLS_HISTORIQUES)
    assert len(historiques) == 1 and "provenance_tier" not in historiques[0], \
        "la ligne SAFE en snapshot garde la place, comme avec setdefault"
    assert _lignes(tmp_path / RL.RUBAN_FILLS_DIRECTS) == []


def test_un_fill_SAFE_en_direct_deloge_bien_un_snapshot_SAFE(tmp_path):
    lignes = [_fill(100, snapshot=True, source="SNAPSHOT"), _fill(100, snapshot=False)]
    RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter(lignes),
                            fabrique_carnets=lambda: iter(()), dossier_temporaire=tmp_path / "t")
    assert len(_lignes(tmp_path / RL.RUBAN_FILLS_DIRECTS)) == 1
    assert _lignes(tmp_path / RL.RUBAN_FILLS_HISTORIQUES) == []


def test_une_ligne_LOCALE_comble_un_trou_que_SAFE_ne_couvre_pas(tmp_path):
    lignes = [_fill(100), _local(_fill(500, tid=9))]
    RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter(lignes),
                            fabrique_carnets=lambda: iter(()), dossier_temporaire=tmp_path / "t")
    assert [l["ts_ms"] for l in _lignes(tmp_path / RL.RUBAN_FILLS_DIRECTS)] == [100, 500]


def test_un_carnet_SAFE_n_est_pas_deloge_par_le_meme_carnet_LOCAL(tmp_path):
    carnets = [_carnet(100), _local(_carnet(100))]
    RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter(()),
                            fabrique_carnets=lambda: iter(carnets), dossier_temporaire=tmp_path / "t")
    ecrits = _lignes(tmp_path / RL.RUBAN_CARNETS)
    assert len(ecrits) == 1 and "provenance_tier" not in ecrits[0]


def test_une_identite_de_fill_INCOMPLETE_ne_leve_pas(tmp_path):
    """Les lignes du tier LOCAL n'ont que vault, coin et ts_ms garantis."""
    assert RL.identite_fill({"vault": "0xa", "coin": "ETH", "ts_ms": 1}) == (
        "0xa", "ETH", 1, None, None, None, None, None, None)


def test_un_carnet_LOCAL_sans_bid_est_ECARTE_comme_par_le_labo(tmp_path):
    sans_bid = {k: v for k, v in _carnet(100).items() if k != "bid"}
    niveaux_invalides = {**_carnet(200), "bids5": [None]}
    gardees = list(RL.lignes_locales(tmp_path, [], famille="book_l2",
                                     flux=_faux_flux([_carnet(300), sans_bid, niveaux_invalides])))
    assert [l["received_at_ms"] for l in gardees] == [300]


def test_les_deux_rubans_de_fills_sont_ecrits_en_UNE_SEULE_passe(tmp_path):
    """Relire onze millions de lignes pour chaque ruban coûtait 709 s de plus par passe."""
    lignes = [_fill(100), _fill(200, snapshot=True, source="SNAPSHOT")]
    passes = []

    def fabrique():
        passes.append(1)
        return iter(lignes)

    RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=fabrique, fabrique_carnets=lambda: iter(()),
                            dossier_temporaire=tmp_path / "t")
    assert len(passes) == 2, "une passe pour les gagnants, une pour les DEUX rubans"


def test_aucun_morceau_temporaire_ne_survit_a_l_ecriture(tmp_path):
    RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter([_fill(1), _fill(2)]),
                            fabrique_carnets=lambda: iter([_carnet(3)]),
                            dossier_temporaire=tmp_path / "t", lignes_par_morceau=1)
    assert not list((tmp_path / "t").glob("morceau_*.jsonl"))


# ───────── les filtres des deux rubans, EXACTEMENT ceux du labo ─────────

def test_un_fill_non_snapshot_mais_NON_CAUSAL_n_entre_dans_AUCUN_ruban(tmp_path):
    """Il compte dans les identités sans être rejoué : c'est la règle du labo, et elle est voulue."""
    lignes = [_fill(100, source="LIVE_WS"), _fill(200, source="EXPLORER_INFERRED"),
              _fill(300, source="LIVE_POLL")]
    bilan = RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter(lignes),
                                    fabrique_carnets=lambda: iter(()),
                                    dossier_temporaire=tmp_path / "t")
    assert bilan["identites_fills"] == 3, "les trois comptent comme identités"
    assert [l["ts_ms"] for l in _lignes(tmp_path / RL.RUBAN_FILLS_DIRECTS)] == [100, 300]
    assert _lignes(tmp_path / RL.RUBAN_FILLS_HISTORIQUES) == []


def test_un_isSnapshot_ABSENT_ou_nul_n_entre_dans_aucun_ruban(tmp_path):
    """`is True` / `is False` et non « quelque chose de vrai » : un drapeau manquant est un refus."""
    sans = {k: v for k, v in _fill(100).items() if k != "isSnapshot"}
    nul = {**_fill(200), "isSnapshot": None}
    entier = {**_fill(300), "isSnapshot": 1}
    bilan = RL.ecrire_rubans_lourds(tmp_path, fabrique_fills=lambda: iter([sans, nul, entier]),
                                    fabrique_carnets=lambda: iter(()),
                                    dossier_temporaire=tmp_path / "t")
    assert bilan["identites_fills"] == 3
    assert _lignes(tmp_path / RL.RUBAN_FILLS_DIRECTS) == []
    assert _lignes(tmp_path / RL.RUBAN_FILLS_HISTORIQUES) == []


def test_les_predicats_sont_exclusifs_et_explicites():
    assert RL.est_un_fill_historique(_fill(1, snapshot=True))
    assert not RL.est_un_fill_historique(_fill(1, snapshot=False))
    assert not RL.est_un_fill_historique({"isSnapshot": 1})
    assert RL.est_un_fill_direct_causal(_fill(1, source="LIVE_POLL"))
    assert not RL.est_un_fill_direct_causal(_fill(1, source="SNAPSHOT"))
    assert not RL.est_un_fill_direct_causal(_fill(1, snapshot=True))
