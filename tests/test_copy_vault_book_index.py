"""L'index des carnets rend exactement ce que le replay recalculait à chaque décision — et rien d'autre.

Cas réel du 2026-11-11 : le labo principal n'aboutissait plus, parce que chaque décision rejouée
reparcourait dix fois la liste entière des carnets de son marché.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_book_index as INDEX  # noqa: E402
from hl_observer.backtesting import copy_vault_executable as cv  # noqa: E402
from hl_observer.backtesting.copy_vault_book_loader import load_observed_books  # noqa: E402

PROTO = cv.CHECKPOINT_COLLECTOR_PROTOCOL
BASE = 1_794_000_000_000


@pytest.fixture(autouse=True)
def _index_vide():
    INDEX.oublier_les_index()
    yield
    INDEX.oublier_les_index()


def _book(ts, bid=100.0, *, line=1, causal=True):
    ask = bid + 2.0
    row = {"coin": "BTC", "ts_ms": ts, "bid": bid, "ask": ask, "capacity_usd": 1_000.0,
           "bids5": [[bid, 1_000.0 / bid]], "asks5": [[ask, 1_000.0 / ask]], "source_line": line,
           "causal_observation": causal}
    if causal:
        row["connection_id"] = "fixture-causal-connection"
        row["l2_gap_epoch"] = 0
    return row


def _carnets(n, *, pas_ms=1_000, debut=BASE):
    return [_book(debut + i * pas_ms, 100.0 + (i % 7) * 0.1, line=i + 1) for i in range(n)]


def _metaordres(n, *, debut=BASE, pas_ms=7_000):
    entrees = [{"event_id": f"e{i}", "ts_ms": debut + 5_000 + i * pas_ms, "coin": "BTC", "direction": 1 if i % 2 else -1,
                "action": "ADD", "dir": "Open Long" if i % 2 else "Open Short", "vault": f"0x{i % 3:x}",
                "taille_usd": 100.0, "move_frac": 0.01, "source": "LIVE_WS", "is_snapshot": False,
                "observed_at_ms": debut + 5_025 + i * pas_ms, "received_at_ms": debut + 5_025 + i * pas_ms}
               for i in range(n)]
    return cv.cluster_metaorders(entrees, gap_ms=1)[0]


# --- l'oracle : les parcours d'origine, recopiés tels qu'ils étaient dans execute_metaorder -------------------

def _oracle_controles(books, metaorder_id):
    return [row for row in books
            if str(row.get("metaorder_id") or "") == metaorder_id
            and str(row.get("collector_protocol") or "") == PROTO
            and row.get("checkpoint_id")]


def _oracle_continus(books):
    rows = [row for row in books if not row.get("checkpoint_id")]
    if not rows:
        return rows, "MISSING_EXACT_METAORDER_CHECKPOINT"
    try:
        horodatages = [int(row["ts_ms"]) for row in rows]
    except (KeyError, TypeError, ValueError, OverflowError):
        return rows, "INVALID_OBSERVED_BOOK"
    if any(droite < gauche for gauche, droite in zip(horodatages, horodatages[1:], strict=False)):
        return rows, "UNSORTED_BOOK_TIMESTAMPS"
    return rows, None


def _oracle_exacts(rows):
    exacts = [ts if type(ts) is int and ts > 0 else None for ts in (row.get("ts_ms") for row in rows)]
    return None if any(ts is None for ts in exacts) else exacts


def _oracle_reference(rows):
    """Le début d'origine de ``_reference_depth_features`` (moteur gelé v21), recopié tel quel."""
    horodatages = [None if isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0 else ts
                   for ts in (row.get("ts_ms") for row in rows)]
    if any(ts is None for ts in horodatages):
        return None
    if any(droite < gauche for gauche, droite in zip(horodatages, horodatages[1:], strict=False)):
        return None
    return horodatages


def _liste_au_hasard(rng, taille):
    rows = _carnets(taille, pas_ms=rng.choice((250, 1_000, 5_000)))
    defaut = rng.choice(("aucun", "aucun", "flottant", "texte", "absent", "nul", "zero", "booleen", "desordre",
                         "controles", "controles_seuls"))
    if not rows:
        return rows
    k = rng.randrange(len(rows))
    if defaut == "flottant":
        rows[k]["ts_ms"] = rows[k]["ts_ms"] + 0.5
    elif defaut == "texte":
        rows[k]["ts_ms"] = str(rows[k]["ts_ms"])
    elif defaut == "absent":
        del rows[k]["ts_ms"]
    elif defaut == "nul":
        rows[k]["ts_ms"] = None
    elif defaut == "zero":
        rows[k]["ts_ms"] = 0
    elif defaut == "booleen":
        rows[k]["ts_ms"] = True
    elif defaut == "desordre":
        j = rng.randrange(len(rows))
        rows[k], rows[j] = rows[j], rows[k]
    elif defaut in ("controles", "controles_seuls"):
        for i in rng.sample(range(len(rows)), k=min(len(rows), 9)):
            rows[i].update(checkpoint_id=f"m{i % 3}:ENTRY" if i % 4 else "", metaorder_id=f"m{i % 3}" if i % 5 else None,
                           collector_protocol=PROTO if i % 2 else "autre")
        if defaut == "controles_seuls":
            rows = [row for row in rows if row.get("checkpoint_id")]
    return rows


@pytest.mark.parametrize("graine", range(12))
def test_l_index_rend_exactement_les_parcours_d_origine(graine):
    rng = random.Random(graine)
    for taille in (0, 1, 5, 255, 256, 257, 700):
        rows = _liste_au_hasard(rng, taille)
        for _relecture in range(2):                                   # deuxième tour : index mémorisé
            index = INDEX.index_des_carnets(rows)
            assert index.continus() == _oracle_continus(rows)
            assert index.horodatages_exacts() == _oracle_exacts(rows)
            assert index.horodatages_de_reference() == _oracle_reference(rows)
            for mid in ("m0", "m1", "m2", "", "inconnu"):
                assert index.points_de_controle(mid) == _oracle_controles(rows, mid)
            continus = index.continus()[0]
            assert INDEX.index_des_carnets(continus).horodatages_exacts() == _oracle_exacts(continus)


def test_une_grande_liste_est_indexee_une_fois_une_petite_jamais_memorisee():
    grande, petite = _carnets(INDEX.SEUIL_INDEX), _carnets(INDEX.SEUIL_INDEX - 1)
    assert INDEX.index_des_carnets(grande) is INDEX.index_des_carnets(grande)
    assert INDEX.index_des_carnets(petite) is not INDEX.index_des_carnets(petite)   # recalcul, comme à l'origine
    assert INDEX.index_des_carnets(tuple(grande)) is not INDEX.index_des_carnets(tuple(grande))
    assert len(INDEX._INDEX) == 1
    INDEX.oublier_les_index()
    assert INDEX._INDEX == {}


@pytest.mark.parametrize("geste", ["ajout", "retrait", "remplacement_sonde", "horodatage_sonde", "controle_sonde"])
def test_une_liste_modifiee_en_place_est_reindexee(geste):
    rows = _carnets(1_000)
    avant = INDEX.index_des_carnets(rows)
    assert avant.continus()[1] is None and len(avant.horodatages_exacts()) == 1_000
    if geste == "ajout":
        rows.append(_book(BASE + 5_000_000, line=1_001))
    elif geste == "retrait":
        rows.pop(500)
    elif geste == "remplacement_sonde":
        rows[0] = dict(rows[0])
    elif geste == "horodatage_sonde":
        rows[-1]["ts_ms"] = 12                                        # devient désordonné
    else:
        rows[0].update(checkpoint_id="m:ENTRY", metaorder_id="m", collector_protocol=PROTO)
    apres = INDEX.index_des_carnets(rows)
    assert apres is not avant
    assert apres.continus() == _oracle_continus(rows)
    assert apres.horodatages_exacts() == _oracle_exacts(rows)
    assert apres.points_de_controle("m") == _oracle_controles(rows, "m")


def test_le_replay_n_indexe_qu_une_fois_par_marche_et_rend_les_memes_trades(monkeypatch):
    """300 décisions sur 20 000 carnets : deux index construits, pas 300 parcours ; résultats inchangés."""
    rows = _carnets(20_000)
    metaordres = _metaordres(300, pas_ms=60_000)
    constructions = []
    origine = INDEX.IndexCarnets.__init__

    def compter(self, source, empreinte=None):
        constructions.append(len(source))
        origine(self, source, empreinte)

    monkeypatch.setattr(INDEX.IndexCarnets, "__init__", compter)
    trades, audit = cv.replay_metaorders(metaordres, {"BTC": rows}, horizon_ms=60_000, require_causal_observation=True)
    placebo, _ = cv.replay_metaorders(metaordres, {"BTC": rows}, horizon_ms=60_000, direction_multiplier=-1,
                                      require_causal_observation=True)
    assert audit["metaorders_considered"] == 300 and len(trades) > 50 and len(placebo) == len(trades)
    assert constructions == [20_000, 20_000]                          # la liste, puis ses carnets continus
    # mêmes trades sans aucune mémorisation (chaque appel recalcule tout, comme le moteur d'origine)
    monkeypatch.setattr(INDEX, "SEUIL_INDEX", 10**9)
    INDEX.oublier_les_index()
    constructions.clear()
    sans_memoire, audit_sans = cv.replay_metaorders(metaordres, {"BTC": rows}, horizon_ms=60_000,
                                                    require_causal_observation=True)
    assert sans_memoire == trades and audit_sans == audit
    assert len(constructions) > 600                                   # c'était le coût payé à chaque décision


def test_un_nouveau_chargement_de_carnets_libere_les_index_precedents(tmp_path):
    rows = _carnets(INDEX.SEUIL_INDEX + 10)
    INDEX.index_des_carnets(rows)
    assert len(INDEX._INDEX) == 1
    load_observed_books(tmp_path, coins={"BTC"})
    assert INDEX._INDEX == {}


def test_une_liste_abandonnee_par_son_appelant_n_est_pas_retenue_par_l_index():
    """Des variantes du replay recopient les carnets à chaque appel : l'index ne doit pas garder ces copies."""
    durable = _carnets(INDEX.SEUIL_INDEX + 5)
    INDEX.index_des_carnets(durable).continus()
    INDEX.index_des_carnets(INDEX.index_des_carnets(durable).continus()[0]).horodatages_exacts()
    assert len(INDEX._INDEX) == 2                                     # la liste et ses carnets continus

    def un_appel_qui_recopie():
        copie = [dict(row) for row in durable]
        INDEX.index_des_carnets(copie).continus()
        INDEX.index_des_carnets(INDEX.index_des_carnets(copie).continus()[0]).horodatages_exacts()

    for _ in range(6):
        un_appel_qui_recopie()
        assert len(INDEX._INDEX) <= 4                                 # jamais plus que la copie du dernier appel
    assert INDEX.oublier_les_listes_abandonnees() == 2 and len(INDEX._INDEX) == 2
    assert INDEX.index_des_carnets(durable) is INDEX._INDEX[id(durable)]   # la liste encore tenue reste indexée
    # sans nouvelle liste, le balayage périodique libère quand même la dernière copie
    un_appel_qui_recopie()
    assert len(INDEX._INDEX) == 4
    for _ in range(INDEX.BALAYAGE_TOUS_LES):
        INDEX.index_des_carnets(durable)
    assert len(INDEX._INDEX) == 2
