"""Tests du collecteur de contexte leader (positions + TWAP), cœur pur sans réseau."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import collecter_contexte_lane as C  # noqa: E402

NOW = 1_800_000_000_000


def test_parser_positions_filtre_plates():
    data = {"user": "0xABC", "assetPositions": [
        {"position": {"coin": "ETH", "szi": "2.5", "entryPx": "2000", "unrealizedPnl": "120"}},
        {"position": {"coin": "BTC", "szi": "0"}},            # plate -> exclue
        {"position": {"coin": "SOL"}},                         # szi absent -> exclue
    ]}
    r = C.parser_positions(data, user="0xABC", recv_ms=NOW)
    assert [x["coin"] for x in r] == ["ETH"]
    assert r[0]["szi"] == 2.5 and r[0]["vault"] == "0xabc" and r[0]["source"] == "CLEARINGHOUSE_WS"


def test_parser_twap_fills():
    data = {"user": "0xABC", "fills": [
        {"coin": "ETH", "px": "2001", "sz": "0.3", "time": NOW - 5, "side": "B", "tid": 11},
        {"coin": "ETH", "px": "0", "sz": "1", "time": NOW, "side": "A"},   # px<=0 -> rejet
    ]}
    r = C.parser_twap_fills(data, user="0xABC", recv_ms=NOW)
    assert len(r) == 1 and r[0]["signe"] == 1 and r[0]["source"] == "LIVE_TWAP"
    assert r[0]["observed_at_ms"] == NOW and r[0]["is_snapshot"] is False


def test_parser_twap_fills_enveloppe():
    data = {"twapSliceFills": [{"fill": {"coin": "BTC", "px": "50000", "sz": "0.01",
                                         "time": NOW - 10, "side": "A", "tid": 1}}]}
    r = C.parser_twap_fills(data, user="0xZZZ", recv_ms=NOW)
    assert len(r) == 1 and r[0]["coin"] == "BTC" and r[0]["signe"] == -1


def test_dedup_twap(tmp_path):
    lane = C.LaneContexte(tmp_path / "p.jsonl", tmp_path / "t.jsonl")
    rows = C.parser_twap_fills({"user": "0xA", "fills": [
        {"coin": "ETH", "px": "1", "sz": "1", "time": NOW - 1, "side": "B", "tid": 5}]},
        user="0xA", recv_ms=NOW)

    async def go():
        await lane.ecrire_twap(rows)
        await lane.ecrire_twap(list(rows))  # doublon
        await lane.ecrire_positions(C.parser_positions(
            {"user": "0xA", "assetPositions": [{"position": {"coin": "ETH", "szi": "1"}}]},
            user="0xA", recv_ms=NOW))
    asyncio.run(go())
    assert lane.twap == 1 and lane.positions == 1


def test_charger_leaders(tmp_path):
    cfg = tmp_path / "config" / "copy_vault_leaders.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"vaults": ["0xAAA1111111", "court", "0xBBB2222222"]}), encoding="utf-8")
    s = C._charger_leaders(tmp_path, "config/copy_vault_leaders.json")
    assert s == ["0xAAA1111111", "0xBBB2222222"]


# ------------------------------------ le TWAP garde son identite (21/11/2026)
def test_l_identifiant_du_twap_n_est_plus_jete():
    """DEFAUT CORRIGE : `parser_twap_fills` deballait `f["fill"]` et perdait `twapId`.

    On savait donc qu'un fill etait une tranche TWAP, mais plus DE QUEL TWAP. Sans ce
    groupe, le labo lit vingt tranches d'une meme decision comme vingt signaux
    independants -- vingt entrees, vingt couts, ou pire vingt confirmations. La section
    << ne fusionne pas des fills si cette agregation detruit une information necessaire
    aux replays >> l'interdit explicitement.
    """
    message = {"fills": [
        {"twapId": 991, "fill": {"coin": "BTC", "px": "100.5", "sz": "0.4",
                                 "time": 1_700_000_000_000, "side": "B",
                                 "tid": 11, "hash": "0xa", "oid": 5}},
        {"twapId": 992, "fill": {"coin": "ETH", "px": "50.0", "sz": "1.0",
                                 "time": 1_700_000_000_100, "side": "A",
                                 "tid": 12, "hash": "0xb", "oid": 6}},
    ]}
    lignes = C.parser_twap_fills(
        message, user="0x31ca8395cf837de08b24da3f660e77761dfb974b",
        recv_ms=1_700_000_000_500)
    assert [item["twap_id"] for item in lignes] == [991, 992]
    # Deux TWAP distincts ne doivent JAMAIS se confondre.
    assert len({item["twap_id"] for item in lignes}) == 2


def test_une_tranche_sans_identifiant_vaut_None_et_non_zero():
    """`None` dit << l'enveloppe ne portait pas l'identifiant >>. Un 0 fabriquerait un
    groupe commun, donc fusionnerait des tranches de TWAP differents."""
    message = {"fills": [{"coin": "SOL", "px": "10.0", "sz": "2.0",
                          "time": 1_700_000_000_200, "side": "B",
                          "tid": 13, "hash": "0xc", "oid": 7}]}
    lignes = C.parser_twap_fills(
        message, user="0x31ca8395cf837de08b24da3f660e77761dfb974b",
        recv_ms=1_700_000_000_500)
    assert len(lignes) == 1
    assert lignes[0]["twap_id"] is None


def test_la_forme_twap_id_de_l_enveloppe_est_aussi_acceptee():
    """Certaines reponses utilisent `twap_id` : on lit les deux, sans supposer."""
    message = {"twapSliceFills": [
        {"twap_id": 777, "fill": {"coin": "BTC", "px": "1.0", "sz": "1.0",
                                  "time": 1_700_000_000_000, "side": "B", "tid": 21}},
    ]}
    lignes = C.parser_twap_fills(
        message, user="0x31ca8395cf837de08b24da3f660e77761dfb974b",
        recv_ms=1_700_000_000_500)
    assert lignes and lignes[0]["twap_id"] == 777


# ------------------- horodatage SOURCE des positions (mesure du 21/11/2026)
def _etat_positions(time_ms=1_700_000_000_000):
    etat = {"assetPositions": [{"position": {"coin": "BTC", "szi": "1.5", "entryPx": "100",
                                             "positionValue": "150", "unrealizedPnl": "5"}}]}
    if time_ms is not None:
        etat["time"] = time_ms
    return etat


def test_une_position_porte_l_horodatage_de_la_BOURSE_et_pas_que_le_notre():
    """La preuve etait INTERNE au depot : deux parseurs du meme flux, deux comportements.

    `portefeuille_compte.construire_portefeuille` gardait deja `exchange_ts_ms =
    etat["time"]` ; `parser_positions` ne gardait que `received_at_ms`. Or c'est la lane
    contexte qui tourne reellement, toutes les heures. Ses positions ne pouvaient donc
    pas dire QUAND la bourse avait calcule cet etat -- seulement quand nous l'avions vu,
    ce qui melange notre latence avec un fait de marche.
    """
    ligne = C.parser_positions(_etat_positions(),
                               user="0x31ca8395cf837de08b24da3f660e77761dfb974b",
                               recv_ms=1_700_000_000_500)[0]
    assert ligne["exchange_ts_ms"] == 1_700_000_000_000
    assert ligne["received_at_ms"] == 1_700_000_000_500
    # La latence devient MESURABLE, ce qui est tout l'objet de la section 6.
    assert ligne["received_at_ms"] - ligne["exchange_ts_ms"] == 500


def test_l_horodatage_source_est_un_ENTIER_de_millisecondes():
    """Une date flottante invite aux faux ecarts de causalite a la demi-milliseconde."""
    ligne = C.parser_positions(_etat_positions(),
                               user="0x31ca8395cf837de08b24da3f660e77761dfb974b",
                               recv_ms=1_700_000_000_500)[0]
    assert isinstance(ligne["exchange_ts_ms"], int)
    assert not isinstance(ligne["exchange_ts_ms"], bool)


def test_une_source_sans_horodatage_vaut_None_et_jamais_notre_reception():
    """Mettre notre instant de reception a la place ferait passer notre latence pour
    un fait de marche -- un faux zero d'ecart."""
    for absent in (None, 0, -5, "abc", float("inf")):
        ligne = C.parser_positions(_etat_positions(absent),
                                   user="0x31ca8395cf837de08b24da3f660e77761dfb974b",
                                   recv_ms=1_700_000_000_500)[0]
        assert ligne["exchange_ts_ms"] is None, absent
        assert ligne["received_at_ms"] == 1_700_000_000_500
