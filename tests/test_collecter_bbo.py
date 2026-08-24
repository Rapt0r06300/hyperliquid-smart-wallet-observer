"""COLLECTEUR BBO RAPIDE HL↔Binance (chantier ARB, 23/07). On prouve le CŒUR qui a manqué au détecteur
d'arb invalide : mapping EXACT des contrats (refus si non mappable), parsers, rejet des quotes PÉRIMÉES,
synchronisation, et mesure de lead-lag. Aucun réseau réel : la boucle WS n'est pas testée ici (I/O)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("bbo", RACINE / "tools" / "collecter_bbo.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_mapping_exact_refuse_le_non_mappable():
    m = _mod()
    assert m.symbole_binance("ETH") == "ETHUSDT"
    assert m.symbole_binance("kPEPE") == "1000PEPEUSDT"       # k-token -> 1000x Binance
    assert m.symbole_binance("PEPE") == "1000PEPEUSDT"        # exception connue
    assert m.symbole_binance("HYPE") is None                  # pas sur Binance perp -> REFUS
    assert m.symbole_binance("") is None


def test_resolution_hyperliquid_preserve_case_and_reject_unknown():
    m = _mod()
    selected, rejected = m.resoudre_symboles_hyperliquid(
        ["BTC", "KPEPE", "kbonk", "BTC", "DELISTED"],
        ["BTC", "kPEPE", "kBONK"],
    )
    assert selected == ["BTC", "kPEPE", "kBONK"]
    assert rejected == ["DELISTED"]


def test_meta_hyperliquid_uses_read_only_post(monkeypatch):
    m = _mod()
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            payload = {"universe": [{"name": "BTC"}, {"name": "kPEPE"}]}
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert m.charger_symboles_hyperliquid(timeout=3.0) == ["BTC", "kPEPE"]
    assert captured == {
        "url": m.INFO_HL,
        "method": "POST",
        "payload": {"type": "meta"},
        "timeout": 3.0,
    }


def test_parser_bbo_hl():
    m = _mod()
    msg = {"channel": "bbo", "data": {"coin": "ETH", "time": 111,
           "bbo": [{"px": "3000.0", "sz": "5"}, {"px": "3000.5", "sz": "4"}]}}
    r = m.parser_bbo_hl(msg)
    assert r["coin"] == "ETH" and r["bid"] == 3000.0 and r["ask"] == 3000.5 and r["ts_ex"] == 111
    assert m.parser_bbo_hl({"channel": "trades"}) is None     # autre canal -> None


def test_parser_bookticker_binance():
    m = _mod()
    msg = {"data": {"s": "ETHUSDT", "b": "3000.1", "a": "3000.4", "B": "10", "A": "9", "T": 222}}
    r = m.parser_bookticker_binance(msg)
    assert r["symbol"] == "ETHUSDT" and r["bid"] == 3000.1 and r["ask"] == 3000.4 and r["ts_ex"] == 222
    assert m.parser_bookticker_binance({"x": 1}) is None


_NS = 1_000_000_000                                            # 1 s en nanosecondes (horloge monotone)


def test_parser_aggtrade_detecte_le_sens_agressif():
    m = _mod()
    # m=True -> l'acheteur est maker -> l'agressif est le VENDEUR
    assert m.parser_aggtrade_binance({"data": {"e": "aggTrade", "s": "ETHUSDT", "p": "3000.0",
                                                "q": "1.5", "m": True, "T": 42}})["side"] == "SELL"
    assert m.parser_aggtrade_binance({"data": {"e": "aggTrade", "s": "ETHUSDT", "p": "3000", "q": "1",
                                                "m": False, "T": 42}})["side"] == "BUY"
    # 🔴 23/07 : @aggTrade ne pousse RIEN sur fstream ici (prouvé au navigateur) -> on lit @trade
    # (e="trade", meme structure p/q/m/T/s). Le parser doit accepter les deux.
    t = m.parser_aggtrade_binance({"data": {"e": "trade", "s": "BTCUSDT", "p": "65138.4", "q": "0.5",
                                            "m": True, "T": 7}})
    assert t["side"] == "SELL" and t["symbol"] == "BTCUSDT" and t["px"] == 65138.4
    assert m.parser_aggtrade_binance({"data": {"e": "bookTicker"}}) is None    # pas un trade


def test_magasin_rejette_les_quotes_PERIMEES_et_non_synchrones():
    m = _mod()
    mag = m.MagasinBBO()
    hl = {"coin": "ETH", "bid": 3000.0, "ask": 3000.5, "bid_sz": 5, "ask_sz": 4, "ts_ex": 1}
    bn = {"symbol": "ETHUSDT", "bid": 3000.1, "ask": 3000.4, "bid_sz": 5, "ask_sz": 4, "ts_ex": 2, "update_id": 7}
    mag.maj_hl(hl, recu_mono_ns=_NS, recu_wall_ms=1000)
    mag.maj_binance(bn, "ETH", recu_mono_ns=_NS, recu_wall_ms=1000)
    assert mag.snapshot("ETH", now_mono_ns=_NS, ts_wall_ms=1000.0) is not None       # frais + synchrones
    assert mag.snapshot("ETH", now_mono_ns=_NS + _NS, ts_wall_ms=2000.0) is None     # âge 1000 ms > 750 -> périmé
    mag.maj_binance(
        bn,
        "ETH",
        recu_mono_ns=_NS + 400_000_000,
        recu_wall_ms=1400,
    )  # Binance 400 ms après HL
    assert mag.snapshot("ETH", now_mono_ns=_NS + 400_000_000, ts_wall_ms=1400.0) is None  # désync 400 > 250
    assert mag.snapshot("SOL", now_mono_ns=_NS, ts_wall_ms=1000.0) is None            # une jambe manque


def test_snapshot_porte_ecart_ages_timestamps_et_update_id():
    m = _mod()
    mag = m.MagasinBBO()
    mag.maj_hl({"coin": "ETH", "bid": 3001, "ask": 3002, "bid_sz": 5, "ask_sz": 4, "ts_ex": 10},
               recu_mono_ns=_NS, recu_wall_ms=1000, connection_id="hl-1", sequence=3)
    mag.maj_binance({"symbol": "ETHUSDT", "bid": 3000, "ask": 3001, "bid_sz": 5, "ask_sz": 4,
                     "ts_ex": 11, "update_id": 9}, "ETH", recu_mono_ns=_NS,
                    recu_wall_ms=1000, connection_id="bin-1", sequence=4)
    s = mag.snapshot("ETH", now_mono_ns=_NS, ts_wall_ms=1000.0)
    assert s["ecart_mid_bps"] > 0 and s["ts_ex_hl"] == 10 and s["update_id_bin"] == 9
    assert "age_hl_ms" in s and "desync_ms" in s and s["real_execution"] is False
    assert s["recv_wall_hl_ms"] == 1000
    assert s["recv_wall_bin_ms"] == 1000
    assert s["write_wall_ts_ms"] == 1000
    assert s["connection_id_hl"] == "hl-1"
    assert s["sequence_bin"] == 4
    assert s["event_id"].startswith("bbo_pair:ETH:")


def test_snapshot_certifie_les_quatre_cotes_et_la_capacite_minimale():
    m = _mod()
    mag = m.MagasinBBO()
    mag.maj_hl(
        {"coin": "ETH", "bid": 100.0, "ask": 101.0, "bid_sz": 20.0, "ask_sz": 0.5, "ts_ex": 10},
        recu_mono_ns=_NS,
        recu_wall_ms=1000,
    )
    mag.maj_binance(
        {"symbol": "ETHUSDT", "bid": 99.0, "ask": 100.0, "bid_sz": 30.0, "ask_sz": 40.0, "ts_ex": 11},
        "ETH",
        recu_mono_ns=_NS + 10_000_000,
        recu_wall_ms=1010,
    )

    snapshot = mag.snapshot("ETH", now_mono_ns=_NS + 20_000_000, ts_wall_ms=1020.0)

    assert snapshot["atomic_bbo_certified"] is True
    assert snapshot["source_mode"] == m.ATOMIC_BBO_SOURCE_MODE
    assert snapshot["instrument_mapping_exact"] is True
    assert snapshot["binance_symbol"] == "ETHUSDT"
    assert snapshot["hl_ask_sz"] == 0.5
    assert snapshot["minimum_four_side_top_capacity_usd"] == 50.5
    assert snapshot["taille_top_usd"] == 50.5


def test_event_id_change_si_le_monotone_change_dans_la_meme_milliseconde():
    m = _mod()
    mag = m.MagasinBBO()
    hl = {"coin": "ETH", "bid": 100.0, "ask": 101.0, "bid_sz": 2.0, "ask_sz": 2.0, "ts_ex": 10}
    bn = {"symbol": "ETHUSDT", "bid": 99.0, "ask": 100.0, "bid_sz": 2.0, "ask_sz": 2.0, "ts_ex": 11}
    mag.maj_hl(hl, recu_mono_ns=_NS, recu_wall_ms=1000)
    mag.maj_binance(bn, "ETH", recu_mono_ns=_NS, recu_wall_ms=1000)
    first = mag.snapshot("ETH", now_mono_ns=_NS, ts_wall_ms=1000.0)
    mag.maj_binance(bn, "ETH", recu_mono_ns=_NS + 1, recu_wall_ms=1000)
    second = mag.snapshot("ETH", now_mono_ns=_NS + 1, ts_wall_ms=1000.0)
    assert first["event_id"] != second["event_id"]


def test_sceller_shard_compresse_immuable_et_retention_bornee(tmp_path):
    m = _mod()
    tape = tmp_path / "runtime" / "data" / "bbo_tape.jsonl"
    tape.parent.mkdir(parents=True, exist_ok=True)
    tape.write_text("x" * 5000 + "\n", encoding="utf-8")          # > seuil de test
    nom = m.sceller_shard(tmp_path, seuil_octets=1000, max_shards=2)
    assert nom and nom.endswith(".jsonl.gz")
    shards = tmp_path / "runtime" / "data" / "bbo_shards"
    assert list(shards.glob("*.jsonl.gz")) and not list(shards.glob("*.tmp"))  # immuable, pas de temp
    assert tape.read_text(encoding="utf-8") == ""                 # la tape vivante repart a zero
    # trop petite -> pas de shard ; retention FIFO : au-dela de max_shards on purge le plus vieux
    tape.write_text("y" * 20, encoding="utf-8")
    assert m.sceller_shard(tmp_path, seuil_octets=1000) is None
    for _ in range(3):
        tape.write_text("z" * 5000, encoding="utf-8")
        m.sceller_shard(tmp_path, seuil_octets=1000, max_shards=2)
    assert len(list(shards.glob("*.jsonl.gz"))) <= 2              # borne respectee


def test_mesurer_lead_lag_detecte_que_binance_MENE():
    m = _mod()
    # HL suit Binance avec 2 pas (200 ms) de retard : hl_mid[i] = bin_mid[i-2]
    bin_mid = [100.0 + (i % 11) * 0.1 for i in range(60)]
    serie = []
    for i in range(2, 60):
        serie.append((i * 100.0, bin_mid[i - 2], bin_mid[i]))   # (ts, hl_mid=bin décalé, bin_mid)
    c_lead = m.mesurer_lead_lag(serie, lag_ms=200.0)            # au bon lag -> forte corrélation
    assert c_lead is not None and c_lead > 0.5
    assert m.mesurer_lead_lag(serie[:5], lag_ms=200.0) is None  # trop peu de points -> None honnête
