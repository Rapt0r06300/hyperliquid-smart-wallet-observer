"""Couverture du certificateur : TOUT ce que les collecteurs écrivent est certifié ou expliqué.

Constat d'origine (audit du 2026-11-11) : les cotations BBO Hyperliquid, les fills WebSocket et
les portefeuilles de vaults étaient rejetés à tort, et neuf fichiers étaient ignorés sans trace.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.datasets import coffre_certifie as C  # noqa: E402
import sceller_coffre_local as scl  # noqa: E402

NOW = 1_800_000_000_000
VAULT = "0xca230e816bdb34a46960c2f978a30a563d1ae9e0"


def _quote(**kw):
    base = {"venue": "HL", "coin": "BTC", "mid": 73765.5, "bid": 73765.0, "ask": 73766.0, "bid_sz": 1.33,
            "ask_sz": 9.64, "ts_wall_ms": NOW - 50, "recv_wall_ts_ms": NOW - 50, "sequence": 7, "event_id": "hl-7"}
    base.update(kw)
    return base


def _trade(**kw):
    base = {"venue": "BIN_TRADE", "coin": "ETH", "px": 2063.92, "sz": 0.035, "side": "BUY",
            "ts_wall_ms": NOW - 60, "recv_wall_ts_ms": NOW - 60, "sequence": 9, "event_id": "bin-9"}
    base.update(kw)
    return base


def _ws_fill(**kw):
    base = {"vault": VAULT, "coin": "HYPE", "px": 72.929, "sz": 186.28, "signe": -1, "ts_ms": NOW - 500,
            "received_at_ms": NOW - 273, "dir": "Close Long", "tid": 322, "oid": 601, "start_position": 143503.16,
            "isSnapshot": False, "source": "LIVE_WS"}
    base.update(kw)
    return base


def _certifier(record, famille):
    return C.certifier_record(record, famille=famille, source="TEST", now_ms=NOW)


def test_cotation_bbo_hyperliquid_est_certifiee_et_distinguee_d_une_transaction():
    norm, decision, _ = _certifier(_quote(), C.FAMILLE_BBO)
    assert decision == C.PASS and norm["type_ligne"] == "QUOTE"
    assert (norm["bid"], norm["ask"], norm["bid_sz"]) == (73765.0, 73766.0, 1.33)
    norm, decision, _ = _certifier(_trade(), C.FAMILLE_BBO)
    assert decision == C.PASS and norm["type_ligne"] == "TRADE" and norm["px"] == 2063.92
    # marché verrouillé (bid == ask) : observation réelle, acceptée ; carnet croisé : rejet
    assert _certifier(_quote(bid=100.0, ask=100.0), C.FAMILLE_BBO)[1] == C.PASS
    assert _certifier(_quote(bid=101.0, ask=100.0), C.FAMILLE_BBO)[1:] == (C.QUARANTAINE, "bbo_croise")
    assert _certifier(_quote(ask=None), C.FAMILLE_BBO)[1:] == (C.QUARANTAINE, "bbo_cotation_invalide")
    assert _certifier(_quote(bid_sz=-1), C.FAMILLE_BBO)[1:] == (C.QUARANTAINE, "bbo_taille_invalide")
    assert _certifier(_trade(px=None), C.FAMILLE_BBO)[1:] == (C.QUARANTAINE, "px_invalide")   # ni cotation ni trade


def test_fill_websocket_l_heure_de_reception_reelle_vaut_observation():
    norm, decision, _ = _certifier(_ws_fill(), C.FAMILLE_FILLS_FORWARD)
    assert decision == C.REPARE and norm["observed_at_ms"] == NOW - 273
    assert norm["observation_field"] == "received_at_ms" and norm["causal_forward_eligible"] is True
    # un vrai observed_at_ms est toujours conservé tel quel
    norm, _, _ = _certifier(_ws_fill(observed_at_ms=NOW - 100), C.FAMILLE_FILLS_FORWARD)
    assert norm["observed_at_ms"] == NOW - 100 and "observation_field" not in norm
    # aucun des deux instants : toujours rejeté (on n'invente pas une observation)
    sans = _ws_fill()
    del sans["received_at_ms"]
    assert _certifier(sans, C.FAMILLE_FILLS_FORWARD)[1:] == (C.QUARANTAINE, "forward_sans_observed_at_ms")


def test_transactions_explorer_et_flux_de_capital_des_vaults_sont_certifies():
    tx = {"user": VAULT.upper().replace("0X", "0x"), "action_type": "order", "block": 1, "hash": "0xabc",
          "time": NOW - 900, "observed_at_ms": NOW - 700, "source": "EXPLORER_TX"}
    norm, decision, _ = _certifier(tx, C.FAMILLE_EXPLORER_TX)
    assert decision == C.REPARE and norm["user"] == VAULT and norm["ts_ms"] == NOW - 900
    assert _certifier({**tx, "observed_at_ms": None}, C.FAMILLE_EXPLORER_TX)[1:] == (C.QUARANTAINE, "observation_absente")
    assert _certifier({**tx, "user": "x"}, C.FAMILLE_EXPLORER_TX)[1:] == (C.QUARANTAINE, "user_absent_ou_invalide")
    flux = {"ts_ms": NOW - 5_000, "vault": VAULT, "type": "vaultDeposit", "delta_usd": 423.33, "hash": "0xcf"}
    norm, decision, _ = _certifier(flux, C.FAMILLE_VAULT_LEDGER)
    assert decision == C.PASS and norm["delta_usd"] == 423.33 and norm["causal_forward_eligible"] is False
    # retrait dont l'API ne donne pas le montant : événement réel, montant laissé inconnu (jamais 0)
    retrait, decision, _ = _certifier({**flux, "type": "vaultWithdraw", "delta_usd": None}, C.FAMILLE_VAULT_LEDGER)
    assert decision == C.PASS and retrait["delta_usd"] is None and retrait["montant_connu"] is False
    assert norm["montant_connu"] is True
    assert _certifier({**flux, "delta_usd": "beaucoup"}, C.FAMILLE_VAULT_LEDGER)[1:] == (C.QUARANTAINE, "montant_invalide")
    assert C.identite(norm, C.FAMILLE_VAULT_LEDGER) != C.identite({**norm, "delta_usd": 1.0}, C.FAMILLE_VAULT_LEDGER)


def test_chaque_flux_connu_des_collecteurs_a_une_regle_ou_un_motif_explicite():
    """Liste relevée sur un run réel des collecteurs : aucun nom ne doit rester sans réponse."""
    observes = [
        "asset_ctx_tape.jsonl", "bbo_tape.jsonl", "carnet_venues.jsonl", "copy_vault_candle_lane.jsonl",
        "copy_vault_l2_tape.jsonl", "copy_vault_trades_lane.jsonl", "dispersion_venues.jsonl",
        "explorer_inferred_fills.jsonl", "explorer_tx_tape.jsonl", "fills_journal.jsonl", "hl_allmids_tape.jsonl",
        "lead_lag_event_decisions.jsonl", "liquidations_confirmees.jsonl", "metaorder_l2_tape.jsonl",
        "metaorder_shadow_ledger.jsonl", "overshoots_liquidation.jsonl", "raw_l2_lifecycle.jsonl",
        "userfills_integrity_diagnostics.jsonl", "vault_fills.jsonl", "vault_fills_live.jsonl",
        "vault_fills_poll.jsonl", "vault_ledger.jsonl", "vault_snapshots.jsonl",
        # microstructure (runtime/research_lab/data) et fichiers relevés dans les sessions archivées
        "micro_bbo.jsonl", "micro_l2book.jsonl", "micro_trades.jsonl", "micro_bbo_1794306635046325200.jsonl.gz",
        "userfills_unclassified.jsonl", "recap_historique.jsonl", "raw_probe_ledger.jsonl",
        "exploratory_paper_ledger.jsonl", "discovery_probe_ledger.jsonl",
    ]
    sans_reponse = [n for n in observes if C.detecter_famille(n) is None and C.motif_non_certifie(n) is None]
    assert sans_reponse == []
    # un fichier ne peut pas être à la fois certifié et « écarté par conception »
    assert [n for n in observes if C.detecter_famille(n) and C.motif_non_certifie(n)] == []
    assert C.motif_non_certifie("explorer_inferred_fills.jsonl")[0] == "INFERENCE"
    assert C.motif_non_certifie("lead_lag_event_decisions.jsonl.gz")[0] == "HORS_PERIMETRE"


def _ecrire(path: Path, lignes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(l) + "\n" for l in lignes), encoding="utf-8")


def _deposes(root: Path) -> dict[str, int]:
    index = json.loads((root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    total: dict[str, int] = {}
    for shard in index["shards"]:
        total[shard["famille"]] = total.get(shard["famille"], 0) + shard["deposes"]
    return total


def test_le_scelleur_signale_tout_fichier_non_certifie_et_distingue_l_inconnu(tmp_path):
    data = tmp_path / "runtime" / "data"
    _ecrire(data / "bbo_tape.jsonl", [_quote(), _trade()])
    _ecrire(data / "vault_fills_live.jsonl", [_ws_fill()])
    _ecrire(data / "explorer_inferred_fills.jsonl", [{"vault": VAULT, "source": "EXPLORER_INFERRED", "certifie": False}])
    _ecrire(data / "nouveau_flux_jamais_vu.jsonl", [{"mystere": 1}])
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    assert _deposes(tmp_path) == {"bbo": 2, "fills_forward": 1}
    couverture = json.loads((tmp_path / "runtime" / "coffre_certifie" / "COUVERTURE.json").read_text(encoding="utf-8"))
    par_nom = {l["fichier"]: l["categorie"] for l in couverture["non_certifies"]}
    assert par_nom == {"nouveau_flux_jamais_vu.jsonl": "INCONNU", "explorer_inferred_fills.jsonl": "INFERENCE"}
    assert couverture["inconnus"] == 1 and couverture["non_certifies"][0]["fichier"] == "nouveau_flux_jamais_vu.jsonl"
    manifeste = next((tmp_path / "runtime" / "coffre_certifie" / "local" / "manifests").glob("*.json"))
    assert len(json.loads(manifeste.read_text(encoding="utf-8"))["non_certifies"]) == 2


def test_rattrapage_des_archives_sans_dupliquer_ce_qui_etait_deja_au_coffre(tmp_path):
    """Un ruban BBO scellé avec l'ancienne règle (transactions seules), puis archivé : le
    rattrapage dépose les cotations manquantes et ne redépose pas les transactions."""
    coffre = tmp_path / "runtime" / "coffre_certifie"
    archive = tmp_path / "runtime" / "archive" / "session_1"
    ruban = archive / "bbo_tape.jsonl"
    _ecrire(ruban, [_trade(event_id="bin-1"), _quote(event_id="hl-1"), _quote(event_id="hl-2"), _trade(event_id="bin-2")])
    # état hérité : ce contenu a été scellé par le lot « ancien » sous runtime/data, règle v1
    shard = coffre / "local" / "shards" / "bbo" / "ancien__bbo_tape.jsonl.gz"
    shard.parent.mkdir(parents=True)
    with gzip.open(shard, "wt", encoding="utf-8") as h:
        for t in (_trade(event_id="bin-1"), _trade(event_id="bin-2")):
            h.write(json.dumps({**t, "tier": "LOCAL"}) + "\n")
    (coffre / "SOURCES_TRAITEES.json").write_text(json.dumps({
        "runtime/data/bbo_tape.jsonl": {"sha256": scl._sha256_fichier(ruban), "batch": "ancien"}}), encoding="utf-8")
    # sans --archives, une session archivée n'est pas relue
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    assert not (coffre / "LOCAL_INDEX.json").exists()
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives", "--nom", "bbo_tape.jsonl"]) == 0
    index = json.loads((coffre / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert [(s["famille"], s["deposes"]) for s in index["shards"]] == [("bbo", 2)]
    with gzip.open(tmp_path / index["shards"][0]["shard"], "rt", encoding="utf-8") as h:
        assert [json.loads(l)["event_id"] for l in h] == ["hl-1", "hl-2"]     # cotations seules, zéro doublon
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives"]) == 0   # idempotent
    assert len(json.loads((coffre / "LOCAL_INDEX.json").read_text(encoding="utf-8"))["shards"]) == 1


def test_rattrapage_d_une_archive_dont_le_lot_d_origine_est_inconnu(tmp_path):
    """Session ancienne : son SHA n'est plus dans l'état. Le rattrapage ne dépose que ce que
    l'ancienne règle rejetait (cotations BBO, fills WebSocket sans observed_at_ms)."""
    archive = tmp_path / "runtime" / "archive" / "session_ancienne"
    _ecrire(archive / "bbo_tape.jsonl", [_trade(event_id="bin-1"), _quote(event_id="hl-1"), _trade(event_id="bin-2")])
    _ecrire(archive / "vault_fills_live.jsonl", [_ws_fill(tid=1), _ws_fill(tid=2, observed_at_ms=NOW - 100)])
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives"]) == 0
    assert _deposes(tmp_path) == {"bbo": 1, "fills_forward": 1}
    manifeste = next((tmp_path / "runtime" / "coffre_certifie" / "local" / "manifests").glob("*.json"))
    raisons = {Path(f["source"]).name: f["stats"] for f in json.loads(manifeste.read_text(encoding="utf-8"))["fichiers"]}
    assert raisons["bbo_tape.jsonl"]["doublons"] == 2 and raisons["vault_fills_live.jsonl"]["doublons"] == 1
    # le même fichier vu comme collecte EN COURS (jamais scellé) est déposé en entier
    autre = tmp_path / "x"
    _ecrire(autre / "runtime" / "data" / "bbo_tape.jsonl", [_trade(event_id="bin-1"), _quote(event_id="hl-1")])
    assert scl.main(["--root", str(autre), "--now-ms", str(NOW)]) == 0
    assert _deposes(autre) == {"bbo": 2}


def test_fichiers_homonymes_de_plusieurs_sessions_ne_s_ecrasent_pas(tmp_path):
    """Régression : dix sessions archivées ont chacune un ``vault_ledger.jsonl``. Dans un même
    lot, chaque source doit avoir SON shard ; avant, le dernier écrasait tous les autres."""
    flux = lambda i: {"ts_ms": NOW - 5_000 - i, "vault": VAULT, "type": "vaultDeposit", "delta_usd": float(i), "hash": f"0x{i}"}   # noqa: E731
    for session, rang in (("session_1", range(0, 3)), ("session_2", range(10, 12)), ("session_3", range(20, 24))):
        _ecrire(tmp_path / "runtime" / "archive" / session / "vault_ledger.jsonl", [flux(i) for i in rang])
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives"]) == 0
    coffre = tmp_path / "runtime" / "coffre_certifie"
    index = json.loads((coffre / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    chemins = [s["shard"] for s in index["shards"]]
    assert len(chemins) == len(set(chemins)) == 3                    # trois shards distincts
    assert sorted(s["deposes"] for s in index["shards"]) == [2, 3, 4]
    for shard in index["shards"]:                                    # l'index dit vrai, octet pour octet
        assert scl._sha256_fichier(tmp_path / shard["shard"]) == shard["sha256"]
    manifeste = json.loads(next((coffre / "local" / "manifests").glob("*.json")).read_text(encoding="utf-8"))
    assert manifeste["integrite"] == {"verifie": True, "anomalies": []}


def test_un_shard_depose_n_est_jamais_ecrase_et_une_alteration_est_detectee(tmp_path):
    import pytest

    source = tmp_path / "runtime" / "data" / "vault_ledger.jsonl"
    _ecrire(source, [{"ts_ms": NOW - 5_000, "vault": VAULT, "type": "vaultDeposit", "delta_usd": 1.0, "hash": "0x1"}])
    coffre = tmp_path / "runtime" / "coffre_certifie"
    entree = scl.sceller_fichier(source, coffre, "lot", source_tag="T", famille=C.FAMILLE_VAULT_LEDGER,
                                 now_ms=NOW, deja_vus=set(), log=None)
    assert scl.verifier_lot(tmp_path, [entree]) == []
    with pytest.raises(FileExistsError):                             # même lot, même source : refus
        scl.sceller_fichier(source, coffre, "lot", source_tag="T", famille=C.FAMILLE_VAULT_LEDGER,
                            now_ms=NOW, deja_vus=set(), log=None)
    assert scl.verifier_lot(tmp_path, [entree, entree]) == [f"deux sources pointent vers le meme shard : {entree['shard']}"]
    (tmp_path / entree["shard"]).write_bytes(b"altere")
    assert scl.verifier_lot(tmp_path, [entree]) == [f"empreinte differente du manifeste : {entree['shard']}"]
    (tmp_path / entree["shard"]).unlink()
    assert scl.verifier_lot(tmp_path, [entree]) == [f"shard absent : {entree['shard']}"]


def test_archives_seules_les_regles_modifiees_sont_reprises_jamais_les_rubans_deja_scelles(tmp_path):
    """``--archives`` sans ``--nom`` doit être sans danger : un ruban archivé dont la règle n'a pas
    changé a été scellé à l'arrêt de sa session ; le relire créerait des doublons."""
    archive = tmp_path / "runtime" / "archive" / "session_1"
    poll = {"coin": "MINA", "px": "0.05", "sz": "3.0", "side": "B", "time": NOW - 1000, "vault": VAULT,
            "source": "LIVE_POLL", "isSnapshot": False, "observed_at_ms": NOW - 500, "tid": 1}
    _ecrire(archive / "vault_fills_poll.jsonl", [poll])            # règle inchangée (v1)
    _ecrire(archive / "vault_fills_live.jsonl", [_ws_fill()])      # règle corrigée (v2)
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives"]) == 0
    index = json.loads((tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert [Path(s["shard"]).name.split("__")[1] for s in index["shards"]] == ["vault_fills_live"]
    # forcer explicitement un ruban reste possible (session dont le scellage aurait échoué)
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives", "--nom", "vault_fills_poll.jsonl"]) == 0
    assert _deposes(tmp_path) == {"fills_forward": 2}


def test_mode_tout_du_lanceur_couvre_aussi_la_microstructure(tmp_path):
    """Le lanceur appelle ``--tout``, dont le scan récursif exclut ``research_lab``."""
    import hashlib

    ligne = {"flux": "trade", "coin": "ETH", "px": 2063.2, "sz": 0.006, "side": -1, "ts_ex": NOW - 5_000, "tid": 8,
             "ts_wall_ms": NOW - 4_000, "seq": 1, "gap": None, "schema_version": 2, "source": "hl_ws_public"}
    ligne["checksum"] = hashlib.sha256(json.dumps(ligne, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    _ecrire(tmp_path / "runtime" / "research_lab" / "data" / "micro_trades.jsonl", [ligne])
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--tout"]) == 0
    assert _deposes(tmp_path) == {"micro_trades": 1}


def test_bougies_de_backfill_certifiees_depuis_runtime_history(tmp_path):
    """``runtime/history/candles_5m.jsonl`` : format compact, dossier jamais visité auparavant."""
    bougie = {"coin": "ATOM", "t_ms": NOW - 600_000, "o": 1.6462, "h": 1.6472, "l": 1.6452, "c": 1.6456, "v": 184.55}
    # la source est celle du ruban (REST_BACKFILL_5M) : c'est elle qui dit l'intervalle d'une bougie compacte
    norm, decision, _ = C.certifier_record(bougie, famille=C.FAMILLE_CANDLE, source="REST_BACKFILL_5M", now_ms=NOW)
    assert decision == C.REPARE and (norm["open"], norm["close"], norm["open_ts_ms"]) == (1.6462, 1.6456, NOW - 600_000)
    assert norm["causal_forward_eligible"] is False and norm["interval"] == "5m"      # récupérée après coup
    # sans intervalle ni source qui le dise, une bougie 5 min et une bougie 1 h de même ouverture auraient la
    # même identité au coffre : elle est refusée plutôt qu'admise sous une identité ambiguë
    assert _certifier(bougie, C.FAMILLE_CANDLE)[1:] == (C.QUARANTAINE, "intervalle_absent")
    assert _certifier({**bougie, "h": 1.0, "interval": "5m"}, C.FAMILLE_CANDLE)[1:] == (C.QUARANTAINE, "ohlc_incoherent")
    _ecrire(tmp_path / "runtime" / "history" / "candles_5m.jsonl", [bougie, {**bougie, "t_ms": NOW - 300_000}])
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    index = json.loads((tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert [(s["famille"], s["deposes"], s["ts_min_ms"]) for s in index["shards"]] == [("candle", 2, NOW - 600_000)]
    with gzip.open(tmp_path / index["shards"][0]["shard"], "rt", encoding="utf-8") as h:
        assert json.loads(h.readline())["interval"] == "5m"


def test_bbo_des_lanes_meme_grandeurs_autres_noms_et_journal_de_votes_ecarte():
    lane = {"schema_version": "hypersmart.copy_vault_bbo.v1", "coin": "ZRO", "received_at_ms": NOW - 800,
            "exchange_ts_ms": NOW - 2_000, "bid_px": 1.5797, "bid_sz": 151.0, "ask_px": 1.5799, "ask_sz": 97.5,
            "source": "HYPERLIQUID_BBO_WS"}
    norm, decision, _ = _certifier(lane, C.FAMILLE_BBO)
    assert decision == C.PASS and norm["type_ligne"] == "QUOTE" and norm["venue"] == "HL"
    assert (norm["bid"], norm["ask"], norm["bid_px"], norm["ask_px"]) == (1.5797, 1.5799, 1.5797, 1.5799)
    assert norm["recv_wall_ts_ms"] == NOW - 800 and norm["ts_ex"] == NOW - 2_000
    assert norm["schema_version"] == "hypersmart.copy_vault_bbo.v1"     # le labo le relit tel quel
    assert _certifier({**lane, "ask_px": 1.0}, C.FAMILLE_BBO)[1:] == (C.QUARANTAINE, "bbo_croise")
    assert C.nouvellement_accepte("copy_vault_bbo_tape.jsonl", norm) is True
    # le journal de votes du moteur (lignes de test, ni prix ni taille) n'est jamais un fill certifié
    assert C.detecter_famille("leader_fills_bruts.jsonl") is None
    assert C.motif_non_certifie("leader_fills_bruts.jsonl")[0] == "DERIVE"
