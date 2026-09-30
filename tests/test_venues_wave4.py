"""[DATA-094..107] Nansen / Dune / Glassnode / DefiLlama : normalisation + registres + PiT + regime,
frontieres honnetes REQUIRES_KEY (payant) vs REQUIRES_NETWORK (gratuit). Aucun reseau, aucune cle."""
import pytest

from hl_observer.venues import nansen, dune, glassnode, defillama
from hl_observer.venues._canon import CleRequiseError, ReseauRequisError


# ---------------- Nansen (payant -> CleRequiseError) ----------------
def test_nansen_labels_et_smart_money():
    reg = nansen.registre_labels([{"address": "0xA", "labels": ["Fund", "Smart Money"]}])
    assert reg["0xA"]["labels"] == ["Fund", "Smart Money"] and reg["0xA"]["source"] == "nansen"
    sm = nansen.smart_money([{"address": "0xA", "smart_money": True}, {"address": "0xB", "smart_money": False}])
    assert sm == ["0xA"]


def test_nansen_pas_de_label_invente():
    n = nansen.normalize_label({"address": "0xC"})
    assert n["labels"] == []


def test_nansen_exige_cle():
    with pytest.raises(CleRequiseError):
        nansen.LiveClientNansen().get_labels("0xA")


# ---------------- Dune (payant, batch) ----------------
def test_dune_registre_et_resultat():
    reg = dune.registre_requetes([{"query_id": 12345, "name": "top_traders", "params": {"chain": "sol"}}])
    assert reg["12345"]["name"] == "top_traders"
    r = dune.normalize_resultat({"state": "QUERY_STATE_COMPLETED", "execution_ended_at": 1000,
                                 "result": {"rows": [{"a": 1}, {"a": 2}]}})
    assert r["n"] == 2 and r["as_of"] == 1000


def test_dune_fraicheur_et_usage():
    assert dune.fraicheur(1000, 1100, ttl_s=50)["expire"] is True
    assert dune.fraicheur(1000, 1020, ttl_s=50)["expire"] is False
    assert dune.usage_autorise("execution")["autorise"] is False
    assert dune.usage_autorise("recherche")["autorise"] is True


def test_dune_exige_cle():
    with pytest.raises(CleRequiseError):
        dune.LiveClientDune().execute_query(1)


# ---------------- Glassnode (payant, point-in-time) ----------------
def test_glassnode_point_in_time_no_lookahead():
    pts = [{"t": 100, "v": "1"}, {"t": 200, "v": "2"}, {"t": 300, "v": "3"}]
    dispo = glassnode.point_in_time(pts, as_of=200)
    assert [p["ts"] for p in dispo] == [100, 200]
    assert glassnode.derniere_valeur_pit(pts, as_of=250) == 2.0
    assert glassnode.derniere_valeur_pit(pts, as_of=50) is None


def test_glassnode_exige_cle():
    with pytest.raises(CleRequiseError):
        glassnode.LiveClientGlassnode().get_metric("sopr", "BTC")


# ---------------- DefiLlama (gratuit -> ReseauRequisError, pas de cle) ----------------
def test_defillama_normalize_et_regime():
    s = defillama.normalize_stablecoin({"symbol": "USDT", "circulating": {"peggedUSD": 90000000000}})
    assert s["circulating_usd"] == 90000000000.0
    up = defillama.regime([100, 100, 100, 110, 111, 112])
    assert up["regime"] == "expansion"
    down = defillama.regime([120, 119, 118, 100, 100, 100])
    assert down["regime"] == "contraction"
    assert defillama.regime([1, 2])["regime"] is None


def test_defillama_reseau_pas_de_cle():
    # gratuit : c'est ReseauRequisError (et surtout PAS CleRequiseError)
    with pytest.raises(ReseauRequisError):
        defillama.LiveClientDefiLlama().get_stablecoins()
